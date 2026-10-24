"""Sample files for upload demos (generated on demand, also committed under assets/samples/).

The files are harmless and self-made; an upload step only calls set_input_files with one of them.
Run `uv run python -m app.explorer.samples` to (re)create them.
"""

import io
import random
from pathlib import Path

from PIL import Image, ImageDraw

SAMPLES_DIR = Path(__file__).resolve().parents[2] / "assets" / "samples"

# name -> (mime type, what it is, accepted extensions)
CATALOG: dict[str, tuple[str, str, tuple[str, ...]]] = {
    "sample.jpg": ("image/jpeg", "ảnh JPG ~1.5MB", (".jpg", ".jpeg", ".png", ".webp", "image/")),
    "sample.pdf": ("application/pdf", "tệp PDF nhỏ (1 trang)", (".pdf", "application/pdf")),
    "sample.csv": ("text/csv", "tệp CSV nhỏ (5 dòng)", (".csv", "text/csv", ".txt")),
}


def _make_jpg(path: Path) -> None:
    """Gradient + noise + caption: noise keeps the JPEG around 1.5MB at this size."""
    rng = random.Random(7)
    w, h = 2400, 1600
    img = Image.new("RGB", (w, h))
    px = img.load()
    assert px is not None
    for y in range(h):
        for x in range(w):
            n = rng.randint(-40, 40)
            px[x, y] = (
                max(0, min(255, int(40 + 180 * x / w) + n)),
                max(0, min(255, int(90 + 120 * y / h) + n)),
                max(0, min(255, int(220 - 160 * x / w) + n)),
            )
    draw = ImageDraw.Draw(img)
    draw.rectangle((w // 2 - 600, h // 2 - 120, w // 2 + 600, h // 2 + 120), fill=(255, 255, 255))
    draw.text((w // 2 - 560, h // 2 - 20), "SAMPLE IMAGE FOR DEMO UPLOADS", fill=(20, 20, 60))
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=84)
    path.write_bytes(buf.getvalue())


def _make_pdf(path: Path) -> None:
    text = "Sample document for demo uploads"
    stream = f"BT /F1 18 Tf 72 720 Td ({text}) Tj ET"
    objects = [
        "<< /Type /Catalog /Pages 2 0 R >>",
        "<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R "
        "/Resources << /Font << /F1 5 0 R >> >> >>",
        f"<< /Length {len(stream)} >>\nstream\n{stream}\nendstream",
        "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    out = b"%PDF-1.4\n"
    offsets = []
    for i, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += f"{i} 0 obj\n{body}\nendobj\n".encode("latin-1")
    xref = len(out)
    out += f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode()
    out += b"".join(f"{o:010d} 00000 n \n".encode() for o in offsets)
    out += (
        f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    )
    path.write_bytes(out)


def _make_csv(path: Path) -> None:
    rows = ["name,email,amount", "An,an@example.com,120", "Binh,binh@example.com,80",
            "Chi,chi@example.com,200", "Dung,dung@example.com,45"]  # fmt: skip
    path.write_text("\n".join(rows) + "\n", encoding="utf-8")


def ensure_samples() -> Path:
    """Create any missing sample file and return the directory."""
    SAMPLES_DIR.mkdir(parents=True, exist_ok=True)
    for name, make in (
        ("sample.jpg", _make_jpg),
        ("sample.pdf", _make_pdf),
        ("sample.csv", _make_csv),
    ):
        if not (SAMPLES_DIR / name).is_file():
            make(SAMPLES_DIR / name)
    return SAMPLES_DIR


def sample_path(name: str) -> Path:
    if name not in CATALOG:
        raise KeyError(f"unknown sample file {name!r}")
    return ensure_samples() / name


def pick_sample(accept: str | None, hint: str = "") -> str:
    """Sample file for an <input type=file accept=...>; falls back to a guess from the hint text."""
    wanted = (accept or "").lower()
    if wanted:
        for name, (_, _, kinds) in CATALOG.items():
            if any(k in wanted for k in kinds):
                return name
    low = hint.lower()
    if any(w in low for w in ("pdf", "tài liệu", "document", "văn bản")):
        return "sample.pdf"
    if any(w in low for w in ("csv", "excel", "bảng", "spreadsheet", "dữ liệu")):
        return "sample.csv"
    return "sample.jpg"


def catalog_text() -> str:
    """One line per file, for the synthesizer prompt."""
    return "\n".join(f"- {name}: {what}" for name, (_, what, _) in CATALOG.items())


if __name__ == "__main__":
    print(ensure_samples())
