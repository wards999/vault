"""Generates icons/vault.png and icons/vault.ico (the app icon) from the bundled padlock icon.

Run from the project folder:  python tools/make_icon.py
"""
import sys
from pathlib import Path

from PIL import Image
from PySide6.QtCore import QRectF
from PySide6.QtGui import QGuiApplication, QImage, QPainter, Qt
from PySide6.QtSvg import QSvgRenderer

ROOT = Path(__file__).resolve().parent.parent
SOURCE = ROOT / "icons" / "database" / "C52_Encrypted.svg"

app = QGuiApplication(sys.argv)
size, margin = 256, 16
image = QImage(size, size, QImage.Format_ARGB32)
image.fill(Qt.transparent)
painter = QPainter(image)
painter.setRenderHint(QPainter.Antialiasing)
QSvgRenderer(str(SOURCE)).render(painter, QRectF(margin, margin, size - 2 * margin, size - 2 * margin))
painter.end()

png = ROOT / "icons" / "vault.png"
image.save(str(png))
Image.open(png).save(ROOT / "icons" / "vault.ico",
                     sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
print("wrote", png, "and vault.ico")
