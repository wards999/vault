"""After unlocking, the cursor is in the search box; typing + Down/Enter reaches the results; Ctrl+F returns.
In-app key events only, temporary settings, test database, no processes."""
import os, shutil, sys, time
from pathlib import Path
import helpers  # repo path; temporary folder, settings and test databases
from PySide6.QtCore import QSettings, Qt, QTimer, QProcess
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
s = helpers.WORK
fails = []
def ok(label, cond, extra=""):
    print(("OK   " if cond else "FAIL ") + label + ("" if cond else f"  [{extra}]"), flush=True)
    if not cond: fails.append(label)
def wait(cond, timeout=20):
    end = time.time() + timeout
    while not cond() and time.time() < end: QTest.qWait(50)
    return cond()

app = QApplication(sys.argv)
import vault
QProcess.startDetached = staticmethod(lambda *a, **k: (_ for _ in ()).throw(RuntimeError("no processes from tests")))
ini = s / "searchfocus.ini"; ini.unlink(missing_ok=True)
vault.settings = QSettings(str(ini), QSettings.IniFormat)
db_path = s / "searchfocus41.kdbx"; shutil.copy(s / "rt41.kdbx", db_path)
vault.settings.setValue("last_file", str(db_path))
vault.settings.setValue("quick_unlock", False)

w = vault.MainWindow(); w.setMicaEffectEnabled(False); w.resize(1100, 650); w.show(); QTest.qWaitForWindowExposed(w)
def fill():
    d = next((d for d in w.findChildren(vault.UnlockDialog) if d.isVisible()), None)
    if d is None: QTimer.singleShot(50, fill); return
    d.pw.setText("test-pw-123"); QTest.qWait(100); d.yesButton.click()
QTimer.singleShot(100, fill)
w._show_unlock()
ok("unlocked", wait(lambda: not w.locked))
ok("cursor is in the search box", wait(lambda: w.focusWidget() is w.vault.search, 5), w.focusWidget())
v = w.vault
QTest.keyClicks(v.search, "git")
QTest.keyClick(v.search, Qt.Key_Down); QTest.qWait(100)
ok("Down → results list, first row selected", w.focusWidget() is v.table and v.current_entry() and v.current_entry()["title"] == "GitHub",
   (w.focusWidget(), v.current_entry() and v.current_entry()["title"]))
QTest.keyClick(v.table, Qt.Key_F, Qt.ControlModifier); QTest.qWait(100)
ok("Ctrl+F → back to search, text selected", w.focusWidget() is v.search and v.search.selectedText() == "git")
QTest.keyClicks(v.search, "net"); QTest.keyClick(v.search, Qt.Key_Return); QTest.qWait(100)
ok("typing replaces the search; Enter → results", w.focusWidget() is v.table and v.current_entry()["title"] == "Netflix",
   v.current_entry() and v.current_entry()["title"])
w.switchTo(w.settings_view); QTest.qWait(100)
QTimer.singleShot(100, fill)
w.lock()  # locks, asks again; unlocked by fill()
ok("after lock + unlock: main view, cursor in search", wait(lambda: w.focusWidget() is w.vault.search, 10)
   and w.stackedWidget.currentWidget() is v, w.focusWidget())
print("debug: locked", w.locked, "active", w.isActiveWindow(), "activeWindow", QApplication.activeWindow(), "search enabled/visible", v.search.isEnabled(), v.search.isVisible(), "page", w.stackedWidget.currentWidget().objectName(), flush=True)
print(f"--- {'ALL PASSED' if not fails else str(len(fails)) + ' FAILED'}", flush=True)
sys.stdout.flush(); os._exit(1 if fails else 0)
