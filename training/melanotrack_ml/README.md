# MelanoTrack - Week 5, 7 and 9 implementation code

Code behind the Week-5 (segmentation and registration), Week-7 (temporal features and change analysis)
and Week-9 (deep learning and temporal models) documents. Everything runs on a CPU.

## Data (public)
* ISIC 2017 Parts 1/3 and ISIC 2018 Task 1 images and lesion masks, 256 x 256 copies
  (GitHub mirror `BB-yu/ISIC-data`).
* ISIC 2017 diagnosis labels and near-duplicate groups (RECOD `learningtitans/data-depth-design`, `data/`).
* Pretrained ImageNet weights from the timm GitHub releases (ResNet-18/34/50, EfficientNet-B0/B3)
  and the official Swin Transformer release (Swin-Tiny).

Edit the paths at the top of `src/data.py` and `src/unet.py` (`WEIGHTS`) to match your machine.

## Layout
```
src/
  data.py           dataset index, ISIC 2018/2017 de-duplication, lesion-level splits
  seg_classical.py  Otsu (automatic) and GrabCut (semi-automatic) segmentation, Dice/IoU/HD95
  unet.py           U-Net with ImageNet ResNet-34 encoder, test-time augmentation, confidence score
  simulate.py       follow-up simulation: camera pose, illumination, blur, noise, lesion growth, colour change
  register.py       registration methods; proposed = SIFT on skin + RANSAC + inlier-based acceptance
  features.py       29 per-visit descriptors (size, asymmetry, border, shape, colour, texture)
  sequences.py      4-visit progressing / stable sequences built from a real image
scripts/
  w5_train_unet.py          train the U-Net
  w5_segmentation_eval.py   Otsu / GrabCut / U-Net evaluation on the held-out test split
  w5_registration.py        registration benchmark on simulated follow-ups
  w5_figures.py             segmentation and visit-to-visit comparison figures
  build_sequences.py        simulate sequences and run segmentation -> registration -> features per visit
                            (features measured in each visit's own frame, sizes rescaled by the registration scale)
  w7_analysis.py, w7_figures.py   change accuracy, trajectories, feature separation, example lesion
  w9_embed.py               frozen CNN / Transformer embeddings (real images and visit images)
  w9_baselines.py           single-visit baselines (melanoma vs benign)
  w9_temporal.py            temporal models (GRU + attention, Transformer) and image + temporal fusion
  w9_figures.py, export_numbers.py
results/  week5/, week7/, week9/  (CSV / JSON results and figures used in the documents)
```

## Order to run
```
python src/data.py
python scripts/w5_train_unet.py            # EPOCHS=6 MAX_MIN=40 used for the report
python scripts/w5_segmentation_eval.py
python scripts/w5_registration.py
python scripts/w5_figures.py
WRITE_IMG=1 python scripts/build_sequences.py   # sequences + per-visit features; also writes the visit images
python scripts/w7_analysis.py && python scripts/w7_figures.py
python scripts/w9_embed.py real effb0   # also resnet50, effb3, swin_t
NOFLIP=1 python scripts/w9_embed.py visits effb0   # single view for the 17,200 visit images
python scripts/w9_baselines.py && python scripts/w9_temporal.py && python scripts/w9_figures.py
python scripts/export_numbers.py
```

Requirements: python 3.11+, torch, timm, opencv-python, scikit-image, scikit-learn, scipy, pandas, matplotlib.

## Important
Follow-up visits are **simulated** from real single images (no public serial dermoscopy dataset was
available). Registration, change-measurement and temporal-model results are therefore results on
simulated sequences with known ground truth, not clinical performance.
