"""Regenerate ``icon.ico`` from ``icon.svg``.

One vector source and a raster artefact that cannot disagree with it, because it
is rendered from it rather than redrawn by hand. Each size is rendered from the
SVG directly — no resampling of a larger raster, which is what keeps a 16 px
icon crisp — through Qt's own SVG renderer, and the sizes are packed into one
multi-resolution .ico with Pillow.

A development tool, not part of the application: PySide6's SVG module and Pillow
are needed to run it, never to run the app. Usage::

    python -m presscontroller.app.resources.generate_icon
"""

from __future__ import annotations

import io

from PIL import Image
from PySide6.QtCore import QBuffer, QIODevice
from PySide6.QtGui import QImage, QPainter
from PySide6.QtSvg import QSvgRenderer

from presscontroller.app.resources import ICON_ICO, ICON_SVG

#: What Windows asks for: 16 in a menu, 32 in the title bar, 48 in the taskbar
#: at 150 %, 256 for a large-icon folder view.
SIZES = (16, 24, 32, 48, 64, 128, 256)


def render(svg_path, size: int) -> Image.Image:
    """The SVG drawn at ``size`` px square, as a Pillow image."""
    renderer = QSvgRenderer(str(svg_path))
    image = QImage(size, size, QImage.Format.Format_ARGB32)
    image.fill(0)
    painter = QPainter(image)
    renderer.render(painter)
    painter.end()

    buffer = QBuffer()
    buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    image.save(buffer, "PNG")
    data = bytes(buffer.data())
    buffer.close()
    return Image.open(io.BytesIO(data)).convert("RGBA")


def main() -> None:
    largest = max(SIZES)
    frames = [render(ICON_SVG, s) for s in SIZES if s != largest]
    render(ICON_SVG, largest).save(ICON_ICO, format="ICO",
                                   sizes=[(s, s) for s in SIZES],
                                   append_images=frames)
    print(f"wrote {ICON_ICO} ({len(SIZES)} sizes: {SIZES})")


if __name__ == "__main__":
    main()
