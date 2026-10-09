"""Editing from the Health screen stays on the Health screen. Temporary settings, test database, no processes."""
import os, shutil, sys, time
from pathlib import Path
import helpers  # repo path; temporary folder, settings and test databases
from PySide6.QtCore import QSettings, QTimer, QProcess
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from pykeepass import PyKeePass

s = helpers.WORK
fails = []
def ok(label, cond, extra=""):
    print(("OK   " if cond else "FAIL ") + label + ("" if cond else f"  [{extra}]"), flush=True)
    if not cond: fails.append(label)
def wait(cond, timeout=20):
    end = time.time() + timeout
    while not cond() and time.time() < end: QTest.qWait(50)
    return cond()

path = s / "healthedit41.kdbx"
shutil.copy(s / "rt41.kdbx", path)
kp = PyKeePass(str(path), password="test-pw-123")
kp.add_entry(kp.root_group, "WeakOne", "me", "abc")
kp.save()

app = QApplication(sys.argv)
import vault, store
QProcess.startDetached = staticmethod(lambda *a, **k: (_ for _ in ()).throw(RuntimeError("no processes from tests")))
ini = s / "healthedit.ini"; ini.unlink(missing_ok=True)
vault.settings = QSettings(str(ini), QSettings.IniFormat)
vault.settings.setValue("icons_auto", False)

w = vault.MainWindow(); w.setMicaEffectEnabled(False); w.resize(1200, 700); w.show(); QTest.qWaitForWindowExposed(w)
db = store.Database(path, "test-pw-123", "")
w.vault.load(db); w.saver.attach(db); w.health.set_db(db); w.locked = False
h = w.health
w.switchTo(h)
weak = lambda: [i for i in h.issues if i["entry"]["title"] == "WeakOne"]
ok("WeakOne listed on Health", wait(lambda: bool(weak())), h.issues)

def act():
    dlg = next((d for d in w.findChildren(vault.EntryEditor) if d.isVisible()), None)
    if dlg is None:
        QTimer.singleShot(50, act); return
    ok("editor opened while still on Health", w.stackedWidget.currentWidget() is h)
    dlg.password.setText("Xq7#mZ2!pLx9$Rw-long-enough")
    QTest.qWait(100)
    dlg.yesButton.click()
QTimer.singleShot(80, act)
row = next(r for r, i in enumerate(h.rows) if i["entry"]["title"] == "WeakOne")
h._open(h.table.model().index(row, 1))
ok("still on Health after saving", w.stackedWidget.currentWidget() is h)
ok("password changed", wait(lambda: next(e for e in w.saver.db.entries if e["title"] == "WeakOne")["password"].startswith("Xq7")))
ok("WeakOne gone from the Health list", wait(lambda: not weak() and not h.dirty), [i["issue"] for i in weak()])

# Cancel also stays put
def cancel():
    dlg = next((d for d in w.findChildren(vault.EntryEditor) if d.isVisible()), None)
    if dlg is None:
        QTimer.singleShot(50, cancel); return
    dlg.cancelButton.click()
if h.rows:
    QTimer.singleShot(80, cancel)
    h._open(h.table.model().index(0, 1))
    ok("cancel stays on Health", w.stackedWidget.currentWidget() is h)
print(f"--- {'ALL PASSED' if not fails else str(len(fails)) + ' FAILED'}", flush=True)
sys.stdout.flush(); os._exit(1 if fails else 0)
