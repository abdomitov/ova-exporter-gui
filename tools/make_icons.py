"""Render the project's own geometric brand into PNG/Windows ICO assets (and a macOS icon source)."""

from pathlib import Path
import sys
from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]


def render(scale=4):
    image = Image.new("RGBA", (128 * scale, 128 * scale), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((0, 0, 128 * scale, 128 * scale), radius=28 * scale, fill="#087f8c")

    def line(points, color="#ffffff", width=6):
        points = [(x * scale, y * scale) for x, y in points]
        draw.line(points, fill=color, width=width * scale, joint="curve")
        radius = width * scale / 2
        for x, y in points:
            draw.ellipse((x - radius, y - radius, x + radius, y + radius), fill=color)

    line([(29, 41), (64, 21), (99, 41), (64, 61), (29, 41), (29, 82), (64, 102), (64, 61)])
    line([(99, 41), (99, 68)])
    line([(82, 88), (110, 88), (99, 77)], "#a0f0cd", 7)
    line([(110, 88), (99, 99)], "#a0f0cd", 7)
    return image


def mac_icon(path):
    """A 1024 px PNG with the margin macOS icons use; build_macos.sh turns it into .icns."""
    canvas = Image.new("RGBA", (1024, 1024), (0, 0, 0, 0))
    canvas.paste(render(8).resize((824, 824), Image.Resampling.LANCZOS), (100, 100))
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    canvas.save(path)
    print("Created", path)


def build():
    image = render()
    target = ROOT / "assets"
    image.resize((128, 128), Image.Resampling.LANCZOS).save(target / "logo.png")
    image.save(
        target / "app.ico",
        format="ICO",
        sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)],
    )
    print("Created logo.png and app.ico")


if __name__ == "__main__":
    if sys.argv[1:2] == ["--mac-png"]:
        mac_icon(sys.argv[2])
    else:
        build()
