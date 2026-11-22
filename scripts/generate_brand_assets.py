from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter


ROOT = Path(__file__).resolve().parents[1]
ASSET_DIR = ROOT / "assets" / "brand"
WEB_PUBLIC_DIR = ROOT / "frontend" / "public"

ICON_SIZE = 256
BG = "#101826"
CREAM = "#FFF6EA"
ORANGE = "#EC8E54"
TEAL = "#2F8FA5"
SLATE = "#233246"


def rounded_panel(draw: ImageDraw.ImageDraw, box: tuple[int, int, int, int], radius: int, fill: str) -> None:
    draw.rounded_rectangle(box, radius=radius, fill=fill)


def build_icon() -> Image.Image:
    base = Image.new("RGBA", (ICON_SIZE, ICON_SIZE), (0, 0, 0, 0))

    shadow = Image.new("RGBA", (ICON_SIZE, ICON_SIZE), (0, 0, 0, 0))
    shadow_draw = ImageDraw.Draw(shadow)
    shadow_draw.rounded_rectangle((26, 30, 230, 234), radius=54, fill=(10, 15, 24, 180))
    shadow = shadow.filter(ImageFilter.GaussianBlur(12))
    base.alpha_composite(shadow)

    panel = Image.new("RGBA", (ICON_SIZE, ICON_SIZE), (0, 0, 0, 0))
    draw = ImageDraw.Draw(panel)
    rounded_panel(draw, (22, 18, 234, 230), radius=52, fill=BG)

    draw.ellipse((36, 150, 78, 192), fill=ORANGE)
    draw.ellipse((176, 54, 218, 96), fill=TEAL)

    draw.rounded_rectangle((86, 64, 168, 190), radius=28, fill=CREAM)
    draw.polygon([(128, 58), (170, 194), (148, 194), (128, 130), (108, 194), (86, 194)], fill=CREAM)

    draw.rounded_rectangle((74, 126, 182, 144), radius=9, fill=BG)
    draw.rounded_rectangle((120, 72, 136, 196), radius=8, fill=BG)

    draw.rounded_rectangle((48, 58, 94, 74), radius=8, fill=ORANGE)
    draw.rounded_rectangle((160, 178, 208, 194), radius=8, fill=TEAL)
    draw.rounded_rectangle((182, 104, 206, 120), radius=8, fill=SLATE)

    base.alpha_composite(panel)
    return base


def save_outputs(icon: Image.Image) -> None:
    ASSET_DIR.mkdir(parents=True, exist_ok=True)
    WEB_PUBLIC_DIR.mkdir(parents=True, exist_ok=True)

    png_path = ASSET_DIR / "autosocial-icon.png"
    ico_path = ASSET_DIR / "autosocial-icon.ico"
    favicon_path = WEB_PUBLIC_DIR / "favicon.ico"
    web_png_path = WEB_PUBLIC_DIR / "icon-192.png"

    icon.save(png_path, format="PNG")
    icon.save(web_png_path, format="PNG")
    icon.save(ico_path, format="ICO", sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
    icon.save(favicon_path, format="ICO", sizes=[(16, 16), (32, 32), (48, 48)])


def main() -> None:
    icon = build_icon()
    save_outputs(icon)
    print("Generated brand assets:")
    print(ASSET_DIR / "autosocial-icon.png")
    print(ASSET_DIR / "autosocial-icon.ico")
    print(WEB_PUBLIC_DIR / "favicon.ico")
    print(WEB_PUBLIC_DIR / "icon-192.png")


if __name__ == "__main__":
    main()
