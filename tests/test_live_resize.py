"""Right-aligned controls hide while the LEFT edge is dragged and come back afterwards; nothing else
moves; right-edge drags and plain moves don't hide anything. Sends the window messages Windows sends
during a drag (WM_SIZING / WM_EXITSIZEMOVE) - window messages, not keyboard or mouse input."""
import ctypes, os, shutil, sys
from ctypes.wintypes import RECT
from pathlib import Path
import helpers  # repo path; temporary folder, settings and test databases
from PySide6.QtCore import QSettings
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

s = helpers.WORK
db_path = s / "live41.kdbx"
shutil.copy(s / "rt41.kdbx", db_path)
ini = s / "live_settings.ini"
ini.unlink(missing_ok=True)
fails = []


def ok(label, cond, extra=""):
    print(("OK   " if cond else "FAIL ") + label + ("" if cond else f"  [{extra}]"), flush=True)
    if not cond:
        fails.append(label)


app = QApplication(sys.argv)
import vault, store
vault.settings = QSettings(str(ini), QSettings.IniFormat)
store.backup_dir = lambda: s / "live_backups"
w = vault.MainWindow()
w.setMicaEffectEnabled(False)
w.resize(1300, 760)
w.show()
QTest.qWaitForWindowExposed(w)
db = store.Database(db_path, "test-pw-123", "")
w.vault.load(db); w.saver.attach(db); w.health.set_db(db); w.locked = False
QTest.qWait(300)
hwnd = int(w.winId())
send = ctypes.windll.user32.SendMessageW
send.argtypes = [ctypes.c_void_p, ctypes.c_uint, ctypes.c_size_t, ctypes.c_void_p]
rect = RECT(*w.geometry().getCoords())
v = w.vault
controls = w._live_resize_widgets()
geometry = lambda: [(c.isVisible(), c.geometry().getRect()) for c in [v.list_title, v.tree] + controls]
before = geometry()


def sizing(edge):
    send(hwnd, 0x0214, edge, ctypes.addressof(rect)); QTest.qWait(80)


def end_drag():
    send(hwnd, 0x0232, 0, None); QTest.qWait(80)


sizing(1)  # WMSZ_LEFT
ok("dragging the left edge hides search, buttons and window controls", not any(c.isVisible() for c in controls),
   [c.isVisible() for c in controls])
ok("…keeping their space (title and folders don't move)",
   [g for _, g in geometry()[:2]] == [g for _, g in before[:2]] and [c.geometry().getRect() for c in controls] == [g for _, g in before[2:]])
end_drag()
ok("drag finished -> everything back exactly as before", geometry() == before)
for edge, name in ((4, "top-left corner"), (7, "bottom-left corner")):
    sizing(edge)
    ok(f"{name} also hides them", not any(c.isVisible() for c in controls))
    end_drag()
ok("…and back again", geometry() == before)
for edge, name in ((2, "right edge"), (6, "bottom edge"), (8, "bottom-right corner")):
    sizing(edge)
    ok(f"{name}: nothing hidden", all(c.isVisible() for c in controls))
    end_drag()
send(hwnd, 0x0231, 0, None); QTest.qWait(50); end_drag()  # WM_ENTERSIZEMOVE + exit: just moving the window
ok("moving the window hides nothing", geometry() == before)
print(f"--- {'ALL PASSED' if not fails else str(len(fails)) + ' FAILED'}", flush=True)
os._exit(1 if fails else 0)
