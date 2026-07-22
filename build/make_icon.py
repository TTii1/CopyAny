"""生成打包图标: build/icon.ico (Windows) 与 build/icon.png (Linux)。
与 copyany/icons.py 的运行时设计保持一致: 蓝色圆角方块 + 白色剪贴板。
仅构建期使用 (Pillow), 不属于运行时依赖。
"""
from pathlib import Path

from PIL import Image, ImageDraw

OUT = Path(__file__).resolve().parent


def draw(size: int) -> Image.Image:
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    m = size * 0.06
    d.rounded_rectangle([m, m, size - m, size - m], radius=size * 0.22, fill=(79, 140, 255, 255))
    w, h = size * 0.42, size * 0.50
    x, y = (size - w) / 2, size * 0.30
    d.rounded_rectangle([x, y, x + w, y + h], radius=size * 0.04, fill=(255, 255, 255, 255))
    cw = size * 0.20
    d.rounded_rectangle([(size - cw) / 2, y - size * 0.05, (size + cw) / 2, y + size * 0.05],
                        radius=size * 0.03, fill=(255, 255, 255, 255))
    lw, lh = w * 0.62, max(2, size * 0.035)
    lx = x + (w - lw) / 2
    d.rounded_rectangle([lx, y + h * 0.30, lx + lw, y + h * 0.30 + lh],
                        radius=lh / 2, fill=(79, 140, 255, 255))
    d.rounded_rectangle([lx, y + h * 0.52, lx + lw * 0.7, y + h * 0.52 + lh],
                        radius=lh / 2, fill=(79, 140, 255, 255))
    return img


def main() -> None:
    draw(256).save(OUT / "icon.ico",
                   sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
    draw(512).save(OUT / "icon.png")
    print(f"图标已生成: {OUT / 'icon.ico'} , {OUT / 'icon.png'}")


if __name__ == "__main__":
    main()
