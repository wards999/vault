"""Full-screen shortcut (F11 here; ⌃⌘F on macOS). In-app key events only, temporary settings, test database."""
import os, shutil, sys
from pathlib import Path
import helpers  # repo path; temporary folder, settings and test databases
from PySide6.QtCore import QSettings, Qt, QProcess
from PySide6.QtGui import QKeySequence
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
s = helpers.WORK
fails = []
def ok(label, cond, extra=""):
    print(("OK   " if cond else "FAIL ") + label + ("" if cond else f"  [{extra}]"), flush=True)
    if not cond: fails.append(label)

app = QApplication(sys.argv)
import vault, store
QProcess.startDetached = staticmethod(lambda *a, **k: (_ for _ in ()).throw(RuntimeError("no processes from tests")))
ini = s / "fullscreen.ini"; ini.unlink(missing_ok=True)
vault.settings = QSettings(str(ini), QSettings.IniFormat)
shutil.copy(s / "rt41.kdbx", s / "fullscreen41.kdbx")
w = vault.MainWindow(); w.setMicaEffectEnabled(False); w.resize(1100, 650); w.show(); QTest.qWaitForWindowExposed(w)
db = store.Database(s / "fullscreen41.kdbx", "test-pw-123", ""); w.vault.load(db); w.locked = False; QTest.qWait(300)
ok("F11 is the full-screen key here", "F11" in [k.toString() for k in QKeySequence.keyBindings(QKeySequence.StandardKey.FullScreen)])
normal = w.geometry()

w.vault.table.setFocus()
QTest.keyClick(w.vault.table, Qt.Key_F11); QTest.qWait(600)
ok("F11 (focus in the list) → full screen", w.isFullScreen())
w.grab().save(str(s / "fullscreen.png"))
w.save_geometry()
QTest.keyClick(w.vault.search, Qt.Key_F11); QTest.qWait(600)
ok("F11 again (focus in search) → back to the normal window", not w.isFullScreen() and not w.isMaximized())
ok("same size and place as before", w.geometry() == normal, (w.geometry(), normal))
r = QApplication.instance(); g = QSettings(str(ini), QSettings.IniFormat).value("window_geometry")
w2 = vault.QWidget(); w2.restoreGeometry(g)
ok("saved geometry isn't full screen", not (w2.windowState() & Qt.WindowFullScreen))

w.showMaximized(); QTest.qWait(500)
w.toggle_full_screen(); QTest.qWait(600)
ok("maximised → full screen", w.isFullScreen())
w.toggle_full_screen(); QTest.qWait(600)
ok("…and back to maximised", w.isMaximized() and not w.isFullScreen())
w.switchTo(w.settings_view); QTest.qWait(200)
QTest.keyClick(w.settings_view, Qt.Key_F11); QTest.qWait(600)
ok("works from the Settings page too", w.isFullScreen())
w.toggle_full_screen(); QTest.qWait(400)
print(f"--- {'ALL PASSED' if not fails else str(len(fails)) + ' FAILED'}", flush=True)
sys.stdout.flush(); os._exit(1 if fails else 0)
