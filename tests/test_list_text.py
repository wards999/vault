"""List text size: entry list, folder tree and notes change straight away; Ctrl+wheel, Ctrl+=/-/0 and
the Settings choice stay in step; the choice is remembered. In-app Qt events only (no OS input)."""
import os, shutil, sys
from pathlib import Path
import helpers  # repo path; temporary folder, settings and test databases
from PySide6.QtCore import QPoint, QPointF, QSettings, Qt
from PySide6.QtGui import QWheelEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

s = helpers.WORK
fails = []


def ok(label, cond, extra=""):
    print(("OK   " if cond else "FAIL ") + label + ("" if cond else f"  [{extra}]"), flush=True)
    if not cond:
        fails.append(label)


db_path = s / "listtext41.kdbx"
shutil.copy(s / "foldericons41.kdbx", db_path)
app = QApplication(sys.argv)
import vault, store
from PySide6.QtCore import QProcess
QProcess.startDetached = staticmethod(lambda *a, **k: (_ for _ in ()).throw(RuntimeError("test tried to start a process")))
ini = s / "listtext.ini"; ini.unlink(missing_ok=True)
vault.settings = QSettings(str(ini), QSettings.IniFormat)
store.backup_dir = lambda: s / "listtext_backups"
w = vault.MainWindow(); w.setMicaEffectEnabled(False); w.resize(1250, 720); w.show(); QTest.qWaitForWindowExposed(w)
db = store.Database(db_path, "test-pw-123", "")
w.vault.load(db); w.saver.attach(db); w.locked = False
v = w.vault
QTest.qWait(300)
v.table.selectRow(0); QTest.qWait(200)


def sizes():
    return dict(table=v.delegate.font.pixelSize(), small=v.delegate.small.pixelSize(), tile=v.delegate.tile, tree=(v.tree.topLevelItem(0).data(0, Qt.FontRole) or vault.getFont(13)).pixelSize(), tree_row=v.tree.visualItemRect(v.tree.topLevelItem(0)).height(),
                notes=v.notes.notes.fontInfo().pixelSize(), row=v.table.verticalHeader().defaultSectionSize(),
                setting=w.settings_view.list_text.currentText())


normal = sizes()
print("      normal:", normal, flush=True)
ok("starts at 100%", normal["setting"] == "100%" and v._list_text == 100)
v.set_list_text_size(125); QTest.qWait(200)
big = sizes()
print("      125%:  ", big, flush=True)
ok("125%: entry titles, usernames, icons, folders and notes all bigger",
   big["table"] > normal["table"] and big["small"] > normal["small"] and big["tile"] > normal["tile"]
   and big["tree"] > normal["tree"] and big["notes"] > normal["notes"], (normal, big))
ok("125%: folder rows taller too", big["tree_row"] > normal["tree_row"], (normal["tree_row"], big["tree_row"]))
ok("125%: rows taller so text isn't clipped", big["row"] > normal["row"])
ok("Settings shows 125%", big["setting"] == "125%")
ok("remembered", vault.settings.value("list_text_size") in (125, "125"))
item = v.tree.topLevelItem(0)
ok("folder rows fit the bigger text", v.tree.visualItemRect(item).height() >= big["tree"] * 1.2,
   (v.tree.visualItemRect(item).height(), big["tree"]))

# Ctrl + wheel over the entry list
def wheel(widget, dy):
    pos = QPointF(widget.rect().center())
    ev = QWheelEvent(pos, QPointF(widget.mapToGlobal(pos.toPoint())), QPoint(0, 0), QPoint(0, dy), Qt.NoButton,
                     Qt.ControlModifier, Qt.NoScrollPhase, False)
    QApplication.sendEvent(widget, ev)

wheel(v.table.viewport(), 120); QTest.qWait(100)
ok("Ctrl + wheel up -> 140%", v._list_text == 140 and w.settings_view.list_text.currentText() == "140%", v._list_text)
wheel(v.tree.viewport(), -120); wheel(v.tree.viewport(), -120); QTest.qWait(100)
ok("Ctrl + wheel down over the folders -> 110%", v._list_text == 110, v._list_text)
wheel(v.notes.notes.viewport(), 40); wheel(v.notes.notes.viewport(), 40); QTest.qWait(50)
ok("small touchpad scrolls add up (2 x 40 = no step yet)", v._list_text == 110, v._list_text)
wheel(v.notes.notes.viewport(), 40); QTest.qWait(50)
ok("…third one completes a step -> 125%", v._list_text == 125, v._list_text)
w.activateWindow(); w.raise_(); QTest.qWaitForWindowActive(w, 3000)  # shortcuts only fire in the active window
v.table.setFocus(); QTest.qWait(50)
QTest.keyClick(v.table, Qt.Key_0, Qt.ControlModifier); QTest.qWait(100)
ok("Ctrl+0 -> back to 100%", v._list_text == 100 and sizes() == normal, sizes())
QTest.keyClick(v.table, Qt.Key_Minus, Qt.ControlModifier); QTest.qWait(100)
ok("Ctrl+- -> 90%", v._list_text == 90, v._list_text)
QTest.keyClick(v.table, Qt.Key_Equal, Qt.ControlModifier); QTest.keyClick(v.table, Qt.Key_Equal, Qt.ControlModifier); QTest.qWait(100)
ok("Ctrl+= twice -> 110%", v._list_text == 110, v._list_text)
for _ in range(10):
    v.zoom_list_text(1)
ok("can't go past 160%", v._list_text == 160)
w.settings_view.list_text.setCurrentText("80%"); QTest.qWait(100)
ok("choosing 80% in Settings applies at once", v._list_text == 80 and sizes()["table"] < normal["table"])
ok("plain wheel (no Ctrl) still scrolls, doesn't zoom", (lambda before: (QApplication.sendEvent(v.table.viewport(), QWheelEvent(
    QPointF(10, 10), QPointF(10, 10), QPoint(0, 0), QPoint(0, -120), Qt.NoButton, Qt.NoModifier, Qt.NoScrollPhase, False)), v._list_text == before)[1])(v._list_text))
for size in (140, 80):
    v.set_list_text_size(size); QTest.qWait(300)
    w.grab().save(str(s / f"listtext_{size}.png"))
print(f"--- {'ALL PASSED' if not fails else str(len(fails)) + ' FAILED'}", flush=True)
sys.stdout.flush(); os._exit(1 if fails else 0)
