"""Draws launcher/paperlab.ico: white serif "P" on the app's seal-red tile."""
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

SEAL = (140, 47, 40, 255)      # #8C2F28 from DESIGN.md
PAPER = (250, 247, 240, 255)   # #FAF7F0
OUT = Path(__file__).with_name("paperlab.ico")


def tile(size: int) -> Image.Image:
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([0, 0, size - 1, size - 1], radius=int(size * 0.22), fill=SEAL)
    font = None
    for name in ("georgiab.ttf", "timesbd.ttf", "arialbd.ttf"):
        try:
            font = ImageFont.truetype(f"C:/Windows/Fonts/{name}", int(size * 0.72))
            break
        except OSError:
            continue
    font = font or ImageFont.load_default()
    box = d.textbbox((0, 0), "P", font=font)
    x = (size - (box[2] - box[0])) / 2 - box[0]
    y = (size - (box[3] - box[1])) / 2 - box[1]
    d.text((x, y), "P", font=font, fill=PAPER)
    return img


if __name__ == "__main__":
    base = tile(256)
    base.save(OUT, format="ICO", sizes=[(s, s) for s in (16, 24, 32, 48, 64, 128, 256)])
    print("wrote", OUT)
