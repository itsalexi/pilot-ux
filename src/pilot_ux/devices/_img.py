import io

from PIL import Image


def fit_width(png: bytes, width: int) -> bytes:
    img = Image.open(io.BytesIO(png))
    if img.width != width:
        h = round(img.height * width / img.width)
        img = img.resize((width, h), Image.LANCZOS)
    out = io.BytesIO()
    img.convert("RGB").save(out, "PNG", optimize=True)
    return out.getvalue()
