"""Desktop lock settings: idle-time choices (incl. migrating the old on/off switch) and locking with
the computer (Windows+L / sleep), simulated with the window messages Windows sends - not input."""
import ctypes, os, shutil, sys, time
from pathlib import Path
import helpers  # repo path; temporary folder, settings and test databases
from PySide6.QtCore import QSettings, QTimer
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

s = helpers.WORK
PW = "test-pw-123"
db_path = s / "locks41.kdbx"
shutil.copy(s / "rt41.kdbx", db_path)
ini = s / "locks_settings.ini"
ini.unlink(missing_ok=True)
fails = []


def ok(label, cond, extra=""):
    print(("OK   " if cond else "FAIL ") + label + ("" if cond else f"  [{extra}]"), flush=True)
    if not cond:
        fails.append(label)


app = QApplication(sys.argv)
import vault, store, systemlock
vault.settings = QSettings(str(ini), QSettings.IniFormat)
vault.settings.setValue("last_file", str(db_path))
vault.settings.setValue("last_keyfile", "")
store.backup_dir = lambda: s / "locks_backups"

# Migration of the old switch, before any window exists
vault.settings.setValue("lock_idle", False)
ok("old 'Lock when idle: off' becomes Never", vault.idle_lock_minutes() == 0)
vault.settings.remove("lock_idle")
ok("default is 5 minutes", vault.idle_lock_minutes() == 5)

w = vault.MainWindow()
w.setMicaEffectEnabled(False)
w.show()
QTest.qWaitForWindowExposed(w)
hwnd = int(w.winId())
send = ctypes.windll.user32.SendMessageW
send.argtypes = [ctypes.c_void_p, ctypes.c_uint, ctypes.c_size_t, ctypes.c_void_p]
dialog = lambda: next((d for d in w.findChildren(vault.UnlockDialog) if d.isVisible()), None)
ok("registered for Windows lock notifications", systemlock.register_windows(hwnd))
combo = next(c for c in w.findChildren(vault.ComboBox) if c.findText("After 5 hours") >= 0)
ok("Settings offers Never … 5 hours, showing 'After 5 minutes'",
   [combo.itemText(i) for i in range(combo.count())] == list(vault.IDLE_LOCK_CHOICES) and combo.currentText() == "After 5 minutes")


def unlock():
    d = dialog(); d.pw.setText(PW); d.yesButton.click()


def steps():
    QTimer.singleShot(0, w.lock); yield dialog
    unlock(); yield lambda: not w.locked
    combo.setCurrentText("After 1 minute")
    ok("choosing 1 minute: saved and the timer uses it", vault.settings.value("lock_idle_minutes") in (1, "1")
       and w.idle.timer.interval() == 60_000 and w.idle.timer.isActive())
    combo.setCurrentText("After 5 hours")
    ok("choosing 5 hours: timer set to 5 hours", w.idle.timer.interval() == 5 * 3_600_000 and w.idle.timer.isActive(), w.idle.timer.interval())
    combo.setCurrentText("Never")
    ok("choosing Never stops the idle timer", not w.idle.timer.isActive())
    w._on_idle()
    ok("…and an idle tick doesn't lock", not w.locked)
    combo.setCurrentText("After 5 minutes")
    # Windows+L
    send(hwnd, systemlock.WM_WTSSESSION_CHANGE, systemlock.WTS_SESSION_LOCK, None)
    yield dialog
    ok("Windows+L (session lock) locks Vault", w.locked and w.vault.db is None)
    unlock(); yield lambda: not w.locked
    # Sleep
    send(hwnd, systemlock.WM_POWERBROADCAST, systemlock.PBT_APMSUSPEND, None)
    yield dialog
    ok("going to sleep locks Vault", w.locked)
    unlock(); yield lambda: not w.locked
    # Other session events must not lock (e.g. unlock = 8)
    send(hwnd, systemlock.WM_WTSSESSION_CHANGE, 8, None); QTest.qWait(300)
    ok("other session events (e.g. unlocking Windows) don't lock", not w.locked)
    # While minimised: lock but stay minimised
    w.showMinimized(); yield lambda: w.isMinimized()
    send(hwnd, systemlock.WM_WTSSESSION_CHANGE, systemlock.WTS_SESSION_LOCK, None)
    yield lambda: w.locked
    QTest.qWait(500)
    ok("Windows+L while minimised: locked, stays minimised", w.locked and w.isMinimized() and dialog() is None)
    w.showNormal(); yield dialog
    unlock(); yield lambda: not w.locked
    # Switch off
    vault.settings.setValue("lock_with_system", False)
    send(hwnd, systemlock.WM_WTSSESSION_CHANGE, systemlock.WTS_SESSION_LOCK, None); QTest.qWait(400)
    ok("with 'Lock with the computer' off, Windows+L doesn't lock", not w.locked)


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
