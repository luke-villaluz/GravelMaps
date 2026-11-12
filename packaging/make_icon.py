"""Draws the app icon and writes packaging/icon.icns (macOS only: uses iconutil).

    .venv/bin/python packaging/make_icon.py

A rounded square with mountains under a night sky and an orange dirt road winding toward them.
"""
import math
import os
import shutil
import subprocess
import tempfile

from PIL import Image, ImageDraw, ImageFilter

HERE = os.path.dirname(os.path.abspath(__file__))
S = 1024


def lerp(a, b, t):
    return tuple(round(x + (y - x) * t) for x, y in zip(a, b))


def draw():
    # Big Sur style: the artwork fills a rounded square inset from the canvas edge.
    inset, radius = 100, 185
    box = (inset, inset, S - inset, S - inset)
    art = Image.new("RGBA", (S, S))

    sky = Image.new("RGBA", (S, S))
    sd = ImageDraw.Draw(sky)
    for y in range(S):
        sd.line([(0, y), (S, y)], fill=lerp((22, 34, 56), (78, 92, 120), min(1, y / 620)) + (255,))
    art.alpha_composite(sky)
    d = ImageDraw.Draw(art)

    d.ellipse((640, 230, 730, 320), fill=(244, 236, 214, 255))  # moon

    # Back range, then a nearer and darker one.
    back = [(inset, 640), (300, 420), (420, 520), (560, 360), (760, 560), (S - inset, 470), (S - inset, 760), (inset, 760)]
    d.polygon(back, fill=(58, 74, 96, 255))
    d.polygon([(560, 360), (615, 415), (592, 405), (572, 425), (552, 404), (525, 400)], fill=(214, 222, 232, 255))  # snow
    d.polygon([(inset, 700), (260, 560), (420, 650), (600, 540), (S - inset, 690), (S - inset, S), (inset, S)],
              fill=(44, 58, 52, 255))

    # Ground.
    d.rectangle((inset, 700, S - inset, S), fill=(52, 64, 44, 255))
    for y in range(700, S - inset):
        d.line([(inset, y), (S - inset, y)], fill=lerp((60, 72, 48), (36, 44, 30), (y - 700) / 224) + (255,))

    # The road: a wide S-curve from the bottom edge to the foot of the mountains.
    def centre(t):  # t: 0 at the bottom, 1 at the horizon
        y = S - inset - t * (S - inset - 690)
        x = 512 + 150 * math.sin(t * math.pi * 1.6) * (1 - t) + 40 * t
        w = 230 * (1 - t) ** 1.25 + 8
        return x, y, w

    steps = 220
    left = [(centre(i / steps)[0] - centre(i / steps)[2] / 2, centre(i / steps)[1]) for i in range(steps + 1)]
    right = [(centre(i / steps)[0] + centre(i / steps)[2] / 2, centre(i / steps)[1]) for i in range(steps + 1)]
    d.polygon(left + right[::-1], fill=(200, 140, 82, 255))
    d.line(left, fill=(150, 98, 54, 255), width=6)
    d.line(right, fill=(150, 98, 54, 255), width=6)
    # Dashes down the middle, in the app's dirt-road orange.
    for i in range(0, steps - 20, 18):
        a, b = centre(i / steps), centre((i + 9) / steps)
        d.line([(a[0], a[1]), (b[0], b[1])], fill=(255, 106, 0, 255), width=max(3, round(a[2] / 14)))

    mask = Image.new("L", (S, S))
    ImageDraw.Draw(mask).rounded_rectangle(box, radius, fill=255)
    out = Image.new("RGBA", (S, S))
    shadow = Image.new("RGBA", (S, S))
    ImageDraw.Draw(shadow).rounded_rectangle((box[0], box[1] + 12, box[2], box[3] + 12), radius, fill=(0, 0, 0, 110))
    out.alpha_composite(shadow.filter(ImageFilter.GaussianBlur(18)))
    clipped = Image.new("RGBA", (S, S))
    clipped.paste(art, mask=mask)
    out.alpha_composite(clipped)
    return out


def main():
    img = draw()
    img.save(os.path.join(HERE, "icon.png"))
    tmp = tempfile.mkdtemp()
    iconset = os.path.join(tmp, "icon.iconset")
    os.makedirs(iconset)
    for size in (16, 32, 128, 256, 512):
        for scale in (1, 2):
            px = size * scale
            name = f"icon_{size}x{size}{'@2x' if scale == 2 else ''}.png"
            img.resize((px, px), Image.LANCZOS).save(os.path.join(iconset, name))
    subprocess.run(["iconutil", "-c", "icns", iconset, "-o", os.path.join(HERE, "icon.icns")], check=True)
    shutil.rmtree(tmp)
    print("wrote packaging/icon.icns and packaging/icon.png")


if __name__ == "__main__":
    main()
