"""Checks Vault's window after resizing from the left / maximising with the smooth-resize fix:
right geometry, and the screen shows exactly what Vault painted (no blank or stale areas).
Uses window-management calls only (SetWindowPos/ShowWindow), never keyboard or mouse input."""
import os, shutil, sys, time
from pathlib import Path
import helpers  # repo path; temporary folder, settings and test databases
helpers.need_desktop()
from PySide6.QtCore import QSettings
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
import win32con, win32gui

s = helpers.WORK
PW = "test-pw-123"
db_path = s / "resize41.kdbx"
shutil.copy(s / "rt41.kdbx", db_path)
ini = s / "resize_settings.ini"
ini.unlink(missing_ok=True)
fails = []


def ok(label, cond, extra=""):
    print(("OK   " if cond else "FAIL ") + label + ("" if cond else f"  [{extra}]"), flush=True)
    if not cond:
        fails.append(label)


app = QApplication(sys.argv)
import vault, store
BASELINE = os.environ.get('BASELINE') == '1'
if BASELINE:  # the library's behaviour, without Vault's smooth-resize fix
    vault.MainWindow.nativeEvent = lambda self, t, m: vault.MainWindow.__mro__[1].nativeEvent(self, t, m)
tag = 'base' if BASELINE else 'fix'
vault.settings = QSettings(str(ini), QSettings.IniFormat)
store.backup_dir = lambda: s / "resize_backups"
w = vault.MainWindow()
w.setMicaEffectEnabled(False)
w.resize(1100, 700)
w.move(300, 150)
w.show()
QTest.qWaitForWindowExposed(w)
db = store.Database(db_path, PW, "")
w.vault.load(db); w.saver.attach(db); w.health.set_db(db); w.locked = False
hwnd = int(w.winId())
win32gui.SetWindowPos(hwnd, win32con.HWND_TOPMOST, 0, 0, 0, 0, win32con.SWP_NOMOVE | win32con.SWP_NOSIZE)


def settle(ms=600):
    QTest.qWait(ms)


def screen_matches_render(label):
    """Compares what's on screen (composited) with Vault's own rendering, sampling a grid of pixels."""
    settle()
    shot = w.screen().grabWindow(0, w.x(), w.y(), w.width(), w.height()).toImage()
    own = w.grab().toImage()
    ratio = shot.width() / max(1, own.width())
    diff = total = 0
    for y in range(12, own.height() - 12, 9):
        for x in range(12, own.width() - 12, 9):
            a, b = own.pixelColor(x, y), shot.pixelColor(int(x * ratio), int(y * ratio))
            total += 1
            if abs(a.red() - b.red()) + abs(a.green() - b.green()) + abs(a.blue() - b.blue()) > 60:
                diff += 1
    shot.save(str(s / f"rs_{tag}_{label[:12].replace(chr(32), chr(95))}_screen.png")); own.save(str(s / f"rs_{tag}_{label[:12].replace(chr(32), chr(95))}_own.png"))
    ok(f"{label}: screen matches what Vault drew", diff / total < 0.02, f"{diff}/{total} pixels differ")


def client_rect():
    l, t, r, b = win32gui.GetClientRect(hwnd)
    return r - l, b - t


screen_matches_render("start")
# Grow from the left in steps, like dragging the left edge (window moves left while getting wider).
x, y, r, b = win32gui.GetWindowRect(hwnd); width, height = r - x, b - y  # Windows coordinates
for step in range(1, 9):
    win32gui.SetWindowPos(hwnd, 0, x - 25 * step, y, width + 25 * step, height, win32con.SWP_NOZORDER)
    QTest.qWait(30)
settle()
ok("left-edge grow: position and size right", win32gui.GetWindowRect(hwnd)[:3] == (x - 200, y, x + width), win32gui.GetWindowRect(hwnd))
ok("left-edge grow: client area = window size", client_rect() == (w.width(), w.height()), (client_rect(), w.size()))
screen_matches_render("after growing from the left")
for step in range(1, 9):  # shrink from the left
    win32gui.SetWindowPos(hwnd, 0, x - 200 + 40 * step, y, width + 200 - 40 * step, height, win32con.SWP_NOZORDER)
    QTest.qWait(30)
settle()
ok("left-edge shrink: position and size right", win32gui.GetWindowRect(hwnd)[:3] == (x + 120, y, x + width), win32gui.GetWindowRect(hwnd))
screen_matches_render("after shrinking from the left")
win32gui.ShowWindow(hwnd, win32con.SW_MAXIMIZE)
settle(900)
ok("maximised", w.isMaximized())
screen_matches_render("maximised")
win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
settle(900)
ok("restored to the previous size", not w.isMaximized() and win32gui.GetWindowRect(hwnd)[:3] == (x + 120, y, x + width), win32gui.GetWindowRect(hwnd))
screen_matches_render("restored")

print(f"--- {'ALL PASSED' if not fails else str(len(fails)) + ' FAILED'}", flush=True)
os._exit(1 if fails else 0)
