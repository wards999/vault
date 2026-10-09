"""Menus must appear fully formed (no growing mask) and in the right place."""
import sys
import helpers  # repo path; temporary folder, settings and test databases
from pathlib import Path
from PySide6.QtCore import QPoint, QSettings, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

s = helpers.WORK
app = QApplication(sys.argv)
import vault, store
from qfluentwidgets import RoundMenu, Action, FluentIcon as FIF, ComboBox
vault.settings = QSettings(str(s / "menu_test.ini"), QSettings.IniFormat)
vault.settings.clear()
ok = lambda c: "OK  " if c else "FAIL"

w = vault.MainWindow()
w.setMicaEffectEnabled(False)
w.show(); QTest.qWaitForWindowExposed(w)
# Down at the bottom of the screen, so a dropdown near the window's bottom has to open upwards.
screen = w.screen().availableGeometry()
w.resize(1100, min(700, screen.height() - 60))
w.move(screen.left() + 20, screen.bottom() - w.frameGeometry().height() + 1)
w.vault.load(store.Database(s / "test.kdbx", "test123", ""))
QTest.qWait(200)


def check(menu, label):
    QTest.qWait(30)  # well within the old reveal animation (~150-250 ms)
    full = menu.mask().isEmpty() and menu.isVisible()
    QTest.qWait(400)
    settled = menu.geometry()
    print(ok(full), f"{label}: fully drawn immediately (no partial mask) at {settled.getRect()}")
    menu.close()
    QTest.qWait(100)
    return settled


# 1. a right-click style menu
menu = RoundMenu(parent=w)
for t in ("Copy username", "Copy password", "Copy website", "Open website", "Edit…", "Duplicate"):
    menu.addAction(Action(FIF.COPY, t))
pos = w.mapToGlobal(QPoint(400, 300))
menu.exec(pos, ani=True)
g = check(menu, "right-click menu")
print(ok(abs(g.top() - pos.y()) < 12), "  opens at the cursor")

# 2. a dropdown that opens downwards and one that has to open upwards
combo = ComboBox(w)
combo.addItems([f"Option {i}" for i in range(6)])
for y, label in ((150, "dropdown near the top"), (w.height() - 60, "dropdown near the bottom")):
    combo.move(500, y)
    combo.resize(200, 32)
    combo.show()
    QTest.qWait(100)
    QTest.mouseClick(combo, Qt.LeftButton)
    menu = combo.dropMenu
    g = check(menu, label)
    combo_top = combo.mapToGlobal(QPoint(0, 0)).y()
    if "bottom" in label:
        print(ok(g.bottom() <= combo_top + 12), f"  opens upwards (menu bottom {g.bottom()} vs dropdown top {combo_top})")
    else:
        print(ok(g.top() >= combo_top), f"  opens downwards")

# 3. a menu the library asks to open upwards (as it does when there's no room below on screen)
from qfluentwidgets.components.widgets.menu import MenuAnimationType
menu = RoundMenu(parent=w)
for t in ("One", "Two", "Three", "Four"):
    menu.addAction(Action(FIF.COPY, t))
anchor = w.mapToGlobal(QPoint(400, 500))
menu.exec(anchor, aniType=MenuAnimationType.PULL_UP)
g = check(menu, "upward menu")
print(ok(abs(g.bottom() - anchor.y()) < 20 and g.top() < anchor.y()), f"  sits above the anchor (bottom {g.bottom()} vs anchor {anchor.y()})")
