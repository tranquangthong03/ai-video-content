import base64
import hashlib
import io
from pathlib import Path

from PIL import Image

MAX_SIDE = 1280
JPEG_QUALITY = 80


def prepare_image(source: Path | bytes) -> tuple[str, str]:
    """Resize (long side <= 1280px), JPEG q80, return (data_url, sha256 of the encoded bytes)."""
    raw = source if isinstance(source, bytes) else Path(source).read_bytes()
    img = Image.open(io.BytesIO(raw)).convert("RGB")
    img.thumbnail((MAX_SIDE, MAX_SIDE))  # keeps aspect ratio, never upscales
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=JPEG_QUALITY)
    data = buf.getvalue()
    return "data:image/jpeg;base64," + base64.b64encode(data).decode(), hashlib.sha256(
        data
    ).hexdigest()
