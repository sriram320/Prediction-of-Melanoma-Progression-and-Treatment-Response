"""U-Net with an ImageNet-pretrained ResNet-34 encoder (timm), trained for lesion segmentation."""
import os
import numpy as np
import torch
import torch.nn as nn
import torch.nn.functional as F
import timm

WEIGHTS = os.environ.get("MELANO_WEIGHTS", "/home/claude/melanotrack_ml/cache/weights")
MEAN = np.array([0.485, 0.456, 0.406], np.float32)
STD = np.array([0.229, 0.224, 0.225], np.float32)


def load_timm_backbone(name, ckpt, **kw):
    if not os.path.exists(f"{WEIGHTS}/{ckpt}"):
        # No local copy (e.g. on Colab): timm downloads its default ImageNet weights. For resnet34 that is the same
        # 'a1' checkpoint (resnet34_a1_0-46f8f793) used in Weeks 5-9.
        return timm.create_model(name, pretrained=True, **kw), [], []
    m = timm.create_model(name, pretrained=False, **kw)
    sd = torch.load(f"{WEIGHTS}/{ckpt}", map_location="cpu", weights_only=False)
    if isinstance(sd, dict) and "model" in sd:
        sd = sd["model"]
    if "swin" in name:
        from timm.models.swin_transformer import checkpoint_filter_fn
        sd = checkpoint_filter_fn(sd, m)
    missing, unexpected = m.load_state_dict(sd, strict=False)
    return m, missing, unexpected


class ConvBlock(nn.Sequential):
    def __init__(self, cin, cout):
        super().__init__(nn.Conv2d(cin, cout, 3, padding=1, bias=False), nn.BatchNorm2d(cout), nn.ReLU(inplace=True),
                         nn.Conv2d(cout, cout, 3, padding=1, bias=False), nn.BatchNorm2d(cout), nn.ReLU(inplace=True))


class UNet(nn.Module):
    """U-Net decoder on a timm encoder. Default: ImageNet-pretrained ResNet-34 (as in the detailed design)."""

    def __init__(self, encoder="resnet34", ckpt="resnet34_a1_0-46f8f793.pth", pretrained=True,
                 dec=(128, 64, 32, 16), freeze_stem=True):
        super().__init__()
        if pretrained:
            self.enc, missing, _ = load_timm_backbone(encoder, ckpt, features_only=True)
            self.n_missing = len(missing)
        else:
            self.enc = timm.create_model(encoder, pretrained=False, features_only=True)
            self.n_missing = -1
        if freeze_stem:
            for n, p in self.enc.named_parameters():
                if n.startswith(("conv1", "bn1", "layer1", "conv_stem", "blocks.0", "blocks.1")):
                    p.requires_grad = False
        ch = self.enc.feature_info.channels()
        self.up = nn.ModuleList()
        cin = ch[-1]
        for skip, cout in zip(reversed(ch[:-1]), dec):
            self.up.append(ConvBlock(cin + skip, cout))
            cin = cout
        self.head = nn.Conv2d(cin, 1, 1)

    def forward(self, x):
        feats = self.enc(x)
        y = feats[-1]
        for blk, skip in zip(self.up, reversed(feats[:-1])):
            y = F.interpolate(y, size=skip.shape[-2:], mode="bilinear", align_corners=False)
            y = blk(torch.cat([y, skip], 1))
        y = self.head(y)
        return F.interpolate(y, size=x.shape[-2:], mode="bilinear", align_corners=False)


UNetEffB0 = UNet  # backwards-compatible name


def to_tensor(imgs, size=192):
    """uint8 HxWx3 (list or array) -> normalised NCHW float tensor at the model size."""
    import cv2
    arr = np.stack([cv2.resize(im, (size, size), interpolation=cv2.INTER_AREA) for im in imgs]).astype(np.float32) / 255.0
    arr = (arr - MEAN) / STD
    return torch.from_numpy(arr.transpose(0, 3, 1, 2).copy())


@torch.no_grad()
def predict_prob(model, imgs, size=192, tta=False, out_size=256):
    """Lesion probability maps at out_size. tta=True averages 8 dihedral transforms and returns
    the per-transform maps as well (used for the confidence score)."""
    model.eval()
    x = to_tensor(imgs, size)
    if not tta:
        p = torch.sigmoid(model(x))
        p = F.interpolate(p, size=(out_size, out_size), mode="bilinear", align_corners=False)
        return p[:, 0].numpy(), None
    maps = []
    for k in range(4):
        for flip in (False, True):
            xx = torch.rot90(x, k, dims=(2, 3))
            if flip:
                xx = torch.flip(xx, dims=(3,))
            p = torch.sigmoid(model(xx))
            if flip:
                p = torch.flip(p, dims=(3,))
            p = torch.rot90(p, -k, dims=(2, 3))
            maps.append(F.interpolate(p, size=(out_size, out_size), mode="bilinear", align_corners=False)[:, 0])
    maps = torch.stack(maps, 1).numpy()          # N x 8 x H x W
    return maps.mean(1), maps


def tta_confidence(mean_map, maps):
    """Mean IoU between each augmented mask and the fused mask (per image)."""
    fused = mean_map > 0.5
    conf = []
    for i in range(len(mean_map)):
        f = fused[i]
        ious = []
        for m in maps[i] > 0.5:
            u = np.logical_or(m, f).sum()
            ious.append(np.logical_and(m, f).sum() / u if u else 1.0)
        conf.append(float(np.mean(ious)))
    return np.array(conf)
