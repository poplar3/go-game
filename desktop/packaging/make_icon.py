"""Рисует значок игры (gogame/icon.png 512×512 и packaging/icon.ico для Windows). Нужен Pillow:
    python packaging/make_icon.py
Готовые файлы лежат в репозитории, запускать нужно только если хотите изменить значок."""
from pathlib import Path

from PIL import Image, ImageDraw

HERE = Path(__file__).resolve().parent
S = 4  # рисуем в 4 раза крупнее и уменьшаем — так края получаются гладкими
N = 512 * S


def draw() -> Image.Image:
    img = Image.new("RGBA", (N, N), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    pad = 24 * S
    d.rounded_rectangle([pad, pad, N - pad, N - pad], radius=72 * S, fill=(222, 177, 104, 255),
                        outline=(150, 105, 45, 255), width=8 * S)
    lines = 5
    m0, m1 = 104 * S, N - 104 * S
    step = (m1 - m0) / (lines - 1)
    for i in range(lines):
        x = round(m0 + i * step)
        d.line([(x, m0), (x, m1)], fill=(60, 40, 20, 255), width=7 * S)
        d.line([(m0, x), (m1, x)], fill=(60, 40, 20, 255), width=7 * S)
    r = int(step * 0.47)

    def stone(cx, cy, black):
        x, y = round(m0 + cx * step), round(m0 + cy * step)
        d.ellipse([x - r + 6 * S, y - r + 10 * S, x + r + 6 * S, y + r + 10 * S], fill=(0, 0, 0, 70))
        if black:
            d.ellipse([x - r, y - r, x + r, y + r], fill=(25, 25, 28, 255))
            d.ellipse([x - r * 0.55, y - r * 0.6, x - r * 0.05, y - r * 0.15], fill=(85, 85, 92, 255))
        else:
            d.ellipse([x - r, y - r, x + r, y + r], fill=(246, 244, 238, 255), outline=(150, 145, 135, 255), width=4 * S)

    stone(1, 1, True)
    stone(2, 2, False)
    stone(3, 1, True)
    stone(2, 3, True)
    stone(3, 3, False)
    return img.resize((512, 512), Image.LANCZOS)


if __name__ == "__main__":
    icon = draw()
    icon.save(HERE.parent / "gogame" / "icon.png")
    icon.save(HERE / "icon.ico", sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
    print("icon.png, icon.ico готовы")
