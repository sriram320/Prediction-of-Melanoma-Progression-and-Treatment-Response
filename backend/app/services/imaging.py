"""Upload validation (magic bytes), metadata stripping, DICOM conversion and the M2 image-quality pre-check.

The quality check is a fast heuristic on a downscaled copy (sharpness, exposure, glare, resolution). It warns the
technician at upload time; it is not the model's own quality assessment.
"""
import io
from dataclasses import dataclass, field

import numpy as np
from PIL import Image as PILImage
from PIL import ImageOps, UnidentifiedImageError

MAX_PIXELS = 64_000_000  # ~8000 x 8000; larger images are rejected (decompression-bomb guard)
THUMBNAIL_SIZES = (128, 256, 512)

JPEG, PNG, TIFF, PDF, DICOM = "image/jpeg", "image/png", "image/tiff", "application/pdf", "application/dicom"
SCAN_TYPES = {JPEG, PNG, TIFF, DICOM}
DOCUMENT_TYPES = {PDF, JPEG, PNG, TIFF}
TYPE_NAMES = {JPEG: "JPEG", PNG: "PNG", TIFF: "TIFF", PDF: "PDF", DICOM: "DICOM"}


class UploadRejected(Exception):
    """A user-facing reason why one uploaded file was not accepted."""


@dataclass
class PreparedImage:
    data: bytes                      # sanitised bytes that are stored and shown
    mime: str
    width: int
    height: int
    quality_score: float
    quality_flags: list[str] = field(default_factory=list)
    device_model: str | None = None  # from DICOM ManufacturerModelName
    source: bytes | None = None      # original DICOM, kept encrypted alongside the PNG


def sniff_mime(data: bytes) -> str | None:
    """Identifies the file from its content, never from the name or the client's Content-Type."""
    if data[:3] == b"\xff\xd8\xff":
        return JPEG
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return PNG
    if data[:4] in (b"II*\x00", b"MM\x00*"):
        return TIFF
    if data[:5] == b"%PDF-":
        return PDF
    if len(data) > 132 and data[128:132] == b"DICM":
        return DICOM
    return None


def _open(data: bytes) -> PILImage.Image:
    try:
        with PILImage.open(io.BytesIO(data)) as probe:
            if probe.width * probe.height > MAX_PIXELS:
                raise UploadRejected("Image is too large (over 64 megapixels)")
            probe.verify()
        img = PILImage.open(io.BytesIO(data))
        img.load()
        return img
    except UploadRejected:
        raise
    except (UnidentifiedImageError, OSError, SyntaxError, ValueError, PILImage.DecompressionBombError) as exc:
        raise UploadRejected("The image is corrupt or cannot be read") from exc


def _to_display_mode(img: PILImage.Image) -> PILImage.Image:
    if img.mode in ("RGB", "RGBA", "L"):
        return img
    if img.mode in ("I;16", "I;16B", "I;16L", "I", "F"):
        arr = np.asarray(img, dtype=np.float64)
        lo, hi = float(arr.min()), float(arr.max())
        scaled = np.zeros_like(arr) if hi <= lo else (arr - lo) / (hi - lo) * 255.0
        return PILImage.fromarray(scaled.astype(np.uint8))
    has_alpha = "A" in img.mode or "transparency" in img.info
    return img.convert("RGBA" if has_alpha else "RGB")


def _save_png(img: PILImage.Image, icc: bytes | None) -> bytes:
    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=False, **({"icc_profile": icc} if icc else {}))
    return buf.getvalue()


def _sanitise_raster(data: bytes, mime: str) -> tuple[PILImage.Image, bytes, str]:
    """Re-encodes without EXIF/GPS, comments or XMP. Keeps the ICC colour profile (colour matters here).

    JPEGs without a rotation flag are re-saved with their own quantisation tables, so pixels barely change.
    TIFFs are stored as lossless PNG.
    """
    img = _open(data)
    icc = img.info.get("icc_profile")
    orientation = img.getexif().get(0x0112, 1)
    if mime == JPEG:
        buf = io.BytesIO()
        clean = dict(icc_profile=icc) if icc else {}
        if orientation in (None, 1) and img.mode in ("RGB", "L", "CMYK"):
            img.save(buf, format="JPEG", quality="keep", subsampling="keep", comment=b"", **clean)
        else:
            img = _to_display_mode(ImageOps.exif_transpose(img))
            if img.mode == "RGBA":
                img = img.convert("RGB")
            img.save(buf, format="JPEG", quality=95, comment=b"", **clean)
        out = buf.getvalue()
        return PILImage.open(io.BytesIO(out)), out, JPEG
    img = _to_display_mode(ImageOps.exif_transpose(img))
    out = _save_png(img, icc)
    return img, out, PNG


def _from_dicom(data: bytes) -> tuple[PILImage.Image, bytes, str | None]:
    import pydicom

    try:
        ds = pydicom.dcmread(io.BytesIO(data))
        frames = int(getattr(ds, "NumberOfFrames", 1) or 1)
        if frames > 1:
            raise UploadRejected("Multi-frame DICOM files are not supported; export a single image")
        arr = ds.pixel_array
    except UploadRejected:
        raise
    except Exception as exc:  # pydicom raises many types for compressed / malformed data
        raise UploadRejected("This DICOM file cannot be decoded (compressed DICOM is not supported; "
                             "export it as PNG or JPEG)") from exc
    arr = np.asarray(arr)
    if arr.ndim == 2:
        arr = arr.astype(np.float64)
        lo, hi = float(arr.min()), float(arr.max())
        arr = np.zeros_like(arr) if hi <= lo else (arr - lo) / (hi - lo) * 255.0
        if str(getattr(ds, "PhotometricInterpretation", "")) == "MONOCHROME1":
            arr = 255.0 - arr
        img = PILImage.fromarray(arr.astype(np.uint8))
    elif arr.ndim == 3 and arr.shape[2] in (3, 4):
        img = PILImage.fromarray(np.ascontiguousarray(arr[:, :, :3]).astype(np.uint8))
    else:
        raise UploadRejected("Unsupported DICOM pixel layout")
    if img.width * img.height > MAX_PIXELS:
        raise UploadRejected("Image is too large (over 64 megapixels)")
    device = str(getattr(ds, "ManufacturerModelName", "") or "").strip()[:100] or None
    return img, _save_png(img, None), device


def assess_quality(img: PILImage.Image) -> tuple[float, list[str]]:
    """Returns (score 0..1, flags). Flags: blur, glare, too_dark, overexposed, low_resolution."""
    width, height = img.size
    small = img.convert("RGB")
    small.thumbnail((512, 512))
    rgb = np.asarray(small, dtype=np.float32)
    gray = rgb @ np.array([0.299, 0.587, 0.114], dtype=np.float32)

    lap = 4 * gray[1:-1, 1:-1] - gray[:-2, 1:-1] - gray[2:, 1:-1] - gray[1:-1, :-2] - gray[1:-1, 2:]
    sharpness = float(lap.var()) if lap.size else 0.0
    brightness = float(gray.mean())
    glare = float((rgb.min(axis=2) > 245).mean())
    short_side = min(width, height)

    flags = []
    if sharpness < 12:
        flags.append("blur")
    if glare > 0.05:
        flags.append("glare")
    if brightness < 45:
        flags.append("too_dark")
    elif brightness > 230:
        flags.append("overexposed")
    if short_side < 600:
        flags.append("low_resolution")

    score = (0.4 * min(sharpness / 60.0, 1.0)
             + 0.3 * max(0.0, 1.0 - abs(brightness - 140.0) / 140.0)
             + 0.2 * max(0.0, 1.0 - glare / 0.10)
             + 0.1 * min(short_side / 1024.0, 1.0))
    return round(score, 2), flags


def prepare_scan(data: bytes, mime: str) -> PreparedImage:
    if mime == DICOM:
        img, out, device = _from_dicom(data)
        score, flags = assess_quality(img)
        return PreparedImage(out, PNG, img.width, img.height, score, flags, device_model=device, source=data)
    img, out, out_mime = _sanitise_raster(data, mime)
    score, flags = assess_quality(img)
    return PreparedImage(out, out_mime, img.width, img.height, score, flags)


def prepare_document(data: bytes, mime: str) -> tuple[bytes, str]:
    if mime == PDF:
        if b"%%EOF" not in data[-2048:]:
            raise UploadRejected("The PDF looks incomplete or damaged")
        return data, PDF
    _, out, out_mime = _sanitise_raster(data, mime)
    return out, out_mime


def make_thumbnail(data: bytes, size: int) -> bytes:
    img = _to_display_mode(PILImage.open(io.BytesIO(data)))
    img = img.convert("RGB")
    img.thumbnail((size, size))
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=85)
    return buf.getvalue()
