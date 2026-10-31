"""Synthetic, clearly fake demo data: dermoscopy-like lesion images that grow over visits, and a tiny PDF.

Used by the demo seed and the tests. No real patient data. Run `python -m app.scripts.synthetic <dir>` to write
three sample JPEGs for trying the upload page.
"""
import io
import sys
from pathlib import Path

import numpy as np
from PIL import Image as PILImage


def lesion_image(visit_index: int, *, width: int = 1024, height: int = 768, seed: int = 7) -> bytes:
    """A pigmented 'lesion' on skin inside a dermoscope circle. Size and asymmetry increase with visit_index."""
    rng = np.random.default_rng(seed * 100 + visit_index)
    yy, xx = np.mgrid[0:height, 0:width].astype(np.float32)
    cx, cy = width / 2, height / 2

    coarse = rng.normal(0, 1, (height // 64 + 2, width // 64 + 2)).astype(np.float32)
    low = np.asarray(PILImage.fromarray(coarse).resize((width, height), PILImage.BICUBIC))
    skin = np.array([198, 152, 122], np.float32) + low[..., None] * 7 + rng.normal(0, 6, (height, width, 1))

    theta = np.arctan2(yy - cy, xx - cx)
    r = np.hypot(xx - cx, yy - cy)
    growth = 1.0 + 0.32 * visit_index
    radius = 105 * growth * (1 + 0.12 * np.sin(3 * theta + 0.4) + 0.07 * np.sin(5 * theta + 1.3)
                             + 0.05 * visit_index * np.sin(2 * theta + 0.9))
    alpha = np.clip((radius - r) / 10, 0, 1)[..., None]
    t = np.clip(r / np.maximum(radius, 1), 0, 1)[..., None]
    pigment = np.array([62, 36, 28], np.float32) * (1 - t) + np.array([142, 94, 68], np.float32) * t
    pigment = pigment + rng.normal(0, 5, (height, width, 1))
    img = skin * (1 - alpha) + pigment * alpha

    for _ in range(4 * visit_index):  # darker dots appear in later visits
        a, d = rng.uniform(0, 2 * np.pi), rng.uniform(0.2, 0.7) * 105 * growth
        dot = np.hypot(xx - (cx + d * np.cos(a)), yy - (cy + d * np.sin(a))) < rng.uniform(4, 8)
        img[dot] = [40, 24, 20]

    img[r > 0.47 * width] = [12, 10, 10]  # the dark ring of a contact dermoscope
    buf = io.BytesIO()
    PILImage.fromarray(np.clip(img, 0, 255).astype(np.uint8)).save(buf, format="JPEG", quality=92)
    return buf.getvalue()


def _pdf_text(s: str) -> str:
    return s.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def simple_pdf(title: str, lines: list[str]) -> bytes:
    """A minimal valid one-page PDF with Helvetica text."""
    body = " T* ".join(f"({_pdf_text(line)}) Tj" for line in lines)
    content = (f"BT /F1 18 Tf 72 740 Td ({_pdf_text(title)}) Tj ET\n"
               f"BT /F1 11 Tf 72 706 Td 16 TL {body} ET")
    objects = [
        "<< /Type /Catalog /Pages 2 0 R >>",
        "<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 4 0 R >> >> "
        "/Contents 5 0 R >>",
        "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        f"<< /Length {len(content.encode('latin-1'))} >>\nstream\n{content}\nendstream",
    ]
    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for i, obj in enumerate(objects, start=1):
        offsets.append(len(out))
        out += f"{i} 0 obj\n{obj}\nendobj\n".encode("latin-1")
    xref = len(out)
    out += f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode()
    out += "".join(f"{o:010d} 00000 n \n" for o in offsets).encode()
    out += f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    return bytes(out)


if __name__ == "__main__":
    target = Path(sys.argv[1] if len(sys.argv) > 1 else "sample_scans")
    target.mkdir(parents=True, exist_ok=True)
    for i in range(3):
        (target / f"synthetic_visit_{i + 1}.jpg").write_bytes(lesion_image(i, seed=11))
    print(f"Wrote 3 synthetic scans to {target.resolve()}")
