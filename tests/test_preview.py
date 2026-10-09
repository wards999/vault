"""Settings → List text size shows a live preview that follows the choice (and Ctrl+wheel changes)."""
import os, sys
from pathlib import Path
import helpers  # repo path; temporary folder, settings and test databases
from PySide6.QtCore import QSettings
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

s = helpers.WORK
fails = []


def ok(label, cond, extra=""):
    print(("OK   " if cond else "FAIL ") + label + ("" if cond else f"  [{extra}]"), flush=True)
    if not cond:
        fails.append(label)


app = QApplication(sys.argv)
import vault
from PySide6.QtCore import QProcess
QProcess.startDetached = staticmethod(lambda *a, **k: (_ for _ in ()).throw(RuntimeError("no processes from tests")))
ini = s / "preview.ini"; ini.unlink(missing_ok=True)
vault.settings = QSettings(str(ini), QSettings.IniFormat)
w = vault.MainWindow(); w.setMicaEffectEnabled(False); w.resize(1250, 800); w.show(); QTest.qWaitForWindowExposed(w)
sv = w.settings_view
w.switchTo(sv); QTest.qWait(400)
px = lambda: (sv.preview_title.fontInfo().pixelSize(), sv.preview_pass.fontInfo().pixelSize())
ok("preview at 100%: list font sizes (13 / 14)", px() == (13, 14), px())
sv.list_text.setCurrentText("140%"); QTest.qWait(200)
ok("choosing 140% enlarges the preview straight away", px() == (18, 20), px())
ok("…and the list behind it", w.vault._list_text == 140)
w.vault.zoom_list_text(-1); QTest.qWait(100)
ok("Ctrl+wheel/shortcut changes show in the preview too", sv.list_text.currentText() == "125%" and px() == (16, 18), px())
sv.list_text.setCurrentText("140%"); QTest.qWait(200)
row = next(r for r in sv.findChildren(vault.SimpleCardWidget) if r.isAncestorOf(sv.list_text))
row.grab().save(str(s / "preview_row.png"))
print(f"--- {'ALL PASSED' if not fails else str(len(fails)) + ' FAILED'}", flush=True)
sys.stdout.flush(); os._exit(1 if fails else 0)
