"""Locking while minimised (the 5-minute idle lock) must not bring the window back; reopening it shows
the unlock screen. Temporary settings and a test database. Steps run from timers (the unlock dialog
runs its own event loop)."""
import os, shutil, sys, time
from pathlib import Path
import helpers  # repo path; temporary folder, settings and test databases
from PySide6.QtCore import QSettings, QTimer
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

s = helpers.WORK
PW = "test-pw-123"
db_path = s / "minlock41.kdbx"
shutil.copy(s / "rt41.kdbx", db_path)
ini = s / "minlock_settings.ini"
ini.unlink(missing_ok=True)
fails = []


def ok(label, cond, extra=""):
    print(("OK   " if cond else "FAIL ") + label + ("" if cond else f"  [{extra}]"), flush=True)
    if not cond:
        fails.append(label)


app = QApplication(sys.argv)
import vault, store
vault.settings = QSettings(str(ini), QSettings.IniFormat)
vault.settings.setValue("last_file", str(db_path))
vault.settings.setValue("last_keyfile", "")
store.backup_dir = lambda: s / "minlock_backups"
w = vault.MainWindow()
w.setMicaEffectEnabled(False)
w.show()
QTest.qWaitForWindowExposed(w)
dialog = lambda: next((d for d in w.findChildren(vault.UnlockDialog) if d.isVisible()), None)


def steps():
    QTimer.singleShot(0, w.lock); yield dialog
    d = dialog(); d.pw.setText(PW); d.yesButton.click()
    yield lambda: not w.locked
    ok("unlocked", not w.locked)
    w.showMinimized()
    yield lambda: w.isMinimized()
    QTimer.singleShot(0, w._on_idle)  # what happens after 5 minutes without use
    yield lambda: w.locked
    QTest.qWait(1500)
    ok("idle lock while minimised: locked and data cleared", w.locked and w.vault.db is None)
    ok("…and the window STAYS minimised", w.isMinimized())
    ok("…with no unlock screen popping up", dialog() is None)
    w.showNormal()
    yield dialog
    ok("opening the window again shows the unlock screen", dialog() is not None and not w.isMinimized())
    d = dialog(); d.pw.setText(PW); d.yesButton.click()
    yield lambda: not w.locked
    ok("unlocks normally", not w.locked and w.vault.db is not None)
    QTimer.singleShot(0, w._on_idle)  # idle lock while the window is open: unlock screen straight away
    yield dialog
    ok("idle lock with the window open: unlock screen shown as before", dialog() is not None)


def run(gen):
    current, deadline = [None], [time.time() + 20]

    def tick():
        try:
            if current[0] is not None and not current[0]():
                if time.time() > deadline[0]:
                    ok("step finished in time", False); return finish()
                return QTimer.singleShot(50, tick)
            QTest.qWait(150)
            current[0] = next(gen); deadline[0] = time.time() + 20
            QTimer.singleShot(50, tick)
        except StopIteration:
            finish()
        except Exception as exc:
            import traceback; traceback.print_exc(); ok("no exceptions", False, exc); finish()
    QTimer.singleShot(200, tick)


def finish():
    print(f"--- {'ALL PASSED' if not fails else str(len(fails)) + ' FAILED'}", flush=True)
    os._exit(1 if fails else 0)


run(steps())
QTimer.singleShot(120_000, lambda: (ok("whole test in time", False), finish()))
app.exec()
