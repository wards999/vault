"""Draws the Vault app icon: a white safe door with a combination dial on a teal rounded square.

Writes:
  icons/vault.png      1024 px, laid out on Apple's icon grid (824 px body, soft shadow) for macOS
  icons/vault.ico      Windows sizes 16-256 px, drawn edge to edge so it isn't tiny in the taskbar
  icons/vault_app.png  edge-to-edge 512 px version used for the window / taskbar icon at runtime
Run from the project folder:  python tools/make_icon.py   (needs Pillow for the .ico)
"""
import math
import sys
from pathlib import Path

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QBrush, QColor, QGuiApplication, QImage, QLinearGradient, QPainter, QPen, QRadialGradient

ROOT = Path(__file__).resolve().parent.parent
TOP, BOTTOM = QColor("#23bac6"), QColor("#06566e")  # teal, matching the default accent colour
WHITE = QColor("#ffffff")


def draw(size=1024, mac_grid=True, simple=False):
    """The icon at `size` px. mac_grid: Apple's margins and shadow; otherwise edge to edge.
    simple: bolder lines and no dial ticks, for tiny sizes (16-32 px)."""
    img = QImage(size, size, QImage.Format_ARGB32)
    img.fill(Qt.transparent)
    p = QPainter(img)
    p.setRenderHint(QPainter.Antialiasing)
    s = size / 1024
    if mac_grid:
        body = QRectF(100 * s, 90 * s, 824 * s, 824 * s)
        for i in range(12, 0, -1):  # soft shadow
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(0, 0, 0, 5))
            p.drawRoundedRect(body.adjusted(-i * s, -i * s + 10 * s, i * s, i * s + 14 * s),
                              185 * s + i * s, 185 * s + i * s)
    else:
        body = QRectF(16 * s, 16 * s, 992 * s, 992 * s)
    u = body.width() / 824  # design units: everything below is laid out on the 824 px body
    radius = 185 * u

    gradient = QLinearGradient(body.topLeft(), body.bottomRight())
    gradient.setColorAt(0, TOP)
    gradient.setColorAt(1, BOTTOM)
    p.setPen(Qt.NoPen)
    p.setBrush(QBrush(gradient))
    p.drawRoundedRect(body, radius, radius)
    shine = QRadialGradient(QPointF(body.center().x(), body.top()), body.width() * 0.8)
    shine.setColorAt(0, QColor(255, 255, 255, 46))
    shine.setColorAt(1, QColor(255, 255, 255, 0))
    p.setBrush(QBrush(shine))
    p.drawRoundedRect(body, radius, radius)

    # safe door outline with two hinges on the left
    inset, stroke = (130, 76) if simple else (118, 40)
    door = body.adjusted(inset * u, inset * u, -inset * u, -inset * u)
    p.setBrush(Qt.NoBrush)
    p.setPen(QPen(WHITE, stroke * u))
    p.drawRoundedRect(door, 70 * u, 70 * u)
    p.setPen(Qt.NoPen)
    p.setBrush(WHITE)
    if not simple:
        for fy in (0.27, 0.73):
            y = door.top() + door.height() * fy
            p.drawRoundedRect(QRectF(door.left() - 46 * u, y - 46 * u, 62 * u, 92 * u), 18 * u, 18 * u)

    # combination dial: white disc, teal face with ticks, pointer and knob
    c = door.center()
    p.drawEllipse(c, (200 if simple else 182) * u, (200 if simple else 182) * u)
    p.setBrush(QColor(BOTTOM))
    p.drawEllipse(c, (120 if simple else 140) * u, (120 if simple else 140) * u)
    for k in range(0 if simple else 12):
        a = math.radians(k * 30 - 90)
        inner, outer = (92 if k % 3 else 78) * u, 122 * u
        p.setPen(QPen(WHITE, (16 if k % 3 == 0 else 10) * u, Qt.SolidLine, Qt.RoundCap))
        p.drawLine(QPointF(c.x() + math.cos(a) * inner, c.y() + math.sin(a) * inner),
                   QPointF(c.x() + math.cos(a) * outer, c.y() + math.sin(a) * outer))
    p.setPen(Qt.NoPen)
    p.setBrush(WHITE)
    p.drawEllipse(c, (58 if simple else 46) * u, (58 if simple else 46) * u)
    p.end()
    return img


def main():
    app = QGuiApplication(sys.argv)
    icons = ROOT / "icons"
    draw(1024, mac_grid=True).save(str(icons / "vault.png"))
    draw(512, mac_grid=False).save(str(icons / "vault_app.png"))

    # Windows .ico: each size drawn separately; the smallest use the bolder, simpler design.
    from PIL import Image
    tmp = icons / "_ico_tmp.png"
    frames = []
    for px in (256, 128, 64, 48, 40, 32, 24, 20, 16):
        draw(px * 4, mac_grid=False, simple=px <= 32).scaled(
            px, px, Qt.KeepAspectRatio, Qt.SmoothTransformation).save(str(tmp))
        frames.append(Image.open(tmp).copy())
    tmp.unlink()
    frames[0].save(icons / "vault.ico", sizes=[f.size for f in frames], append_images=frames[1:])
    print("wrote vault.png (macOS), vault_app.png and vault.ico (Windows)")
    return app


if __name__ == "__main__":
    main()
