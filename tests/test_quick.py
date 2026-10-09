"""GUI test of Quick Unlock in Vault, with a stand-in for Windows Hello (no real prompt).
Uses temporary settings and a test database. The steps run from timers (a generator), because the
unlock dialog runs its own event loop."""
import os, shutil, sys, time
from pathlib import Path
import helpers  # repo path; temporary folder, settings and test databases
from PySide6.QtCore import QSettings, QTimer
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

s = helpers.WORK
PW = "test-pw-123"
db_path = s / "quick41.kdbx"
shutil.copy(s / "rt41.kdbx", db_path)
ini = s / "quick_settings.ini"
ini.unlink(missing_ok=True)
fails = []


def ok(label, cond, extra=""):
    print(("OK   " if cond else "FAIL ") + label + ("" if cond else f"  [{extra}]"), flush=True)
    if not cond:
        fails.append(label)


app = QApplication(sys.argv)
import vault, store, quickunlock
vault.settings = QSettings(str(ini), QSettings.IniFormat)
vault.settings.setValue("last_file", str(db_path))
vault.settings.setValue("last_keyfile", "")
store.backup_dir = lambda: s / "quick_backups"


class FakeHello:
    name = "Windows Hello"

    def __init__(self):
        self.answer, self.calls = True, []

    def available(self):
        return True

    def verify(self, hwnd, reason):
        self.calls.append((hwnd, reason))
        p = quickunlock._Pending()
        QTimer.singleShot(300, lambda: p.finish(self.answer, ""))
        return p


fake = FakeHello()
quickunlock._verifier = fake

w = vault.MainWindow()
w.setMicaEffectEnabled(False)
w.show()
QTest.qWaitForWindowExposed(w)


def visible_dialog():
    return next((d for d in w.findChildren(vault.UnlockDialog) if d.isVisible()), None)


def steps():
    labels = [l.text() for l in w.findChildren(vault.BodyLabel)]
    ok("Settings has 'Unlock with Windows Hello'", "Unlock with Windows Hello" in labels)

    def lock():
        QTimer.singleShot(0, w.lock)

    # 1. first unlock: password only
    lock(); yield visible_dialog
    d = visible_dialog()
    ok("first unlock: plain 'Unlock' (nothing remembered yet)", d.yesButton.text() == "Unlock", d.yesButton.text())
    d.pw.setText(PW); d.yesButton.click()
    yield lambda: not w.locked
    ok("unlocked with password", not w.locked)
    ok("password kept for Quick Unlock, encrypted", isinstance(w.quick, quickunlock.Sealed) and PW.encode() not in w.quick._data)
    ok("dialog doesn't keep the password", d.password is None)

    # 2. lock -> Windows Hello button; cancel
    lock(); yield visible_dialog
    d = visible_dialog()
    ok("after lock: 'Unlock with Windows Hello'", d.yesButton.text() == "Unlock with Windows Hello", d.yesButton.text())
    d.pw.setText("x")
    ok("typing switches to 'Unlock'", d.yesButton.text() == "Unlock", d.yesButton.text())
    d.pw.clear()
    fake.answer = False
    d.yesButton.click()
    ok("while asking: 'Waiting for Windows Hello…'", d.yesButton.text() == "Waiting for Windows Hello…", d.yesButton.text())
    yield lambda: d.yesButton.isEnabled()
    ok("cancelled: still locked, button back", w.locked and d.yesButton.text() == "Unlock with Windows Hello", d.yesButton.text())
    ok("Hello prompt attached to Vault's window", fake.calls and fake.calls[-1][0] == int(w.winId()), fake.calls)

    # 3. approve
    fake.answer = True
    d.pw.returnPressed.emit()  # Enter in the empty password field
    yield lambda: not w.locked
    ok("Enter + approved Hello: unlocked", not w.locked)
    ok("entries loaded", w.vault.db is not None and len(w.vault.db.entries) > 0)

    # 4. master password changed elsewhere
    w.quick = quickunlock.Sealed(str(db_path), "", "old-password")
    lock(); yield visible_dialog
    d = visible_dialog()
    d.yesButton.click()
    yield lambda: d.error.isVisible()
    ok("changed master password: explained", "has changed" in d.error.text(), d.error.text())
    ok("…and falls back to 'Unlock'", d.yesButton.text() == "Unlock", d.yesButton.text())
    d.pw.setText(PW); d.yesButton.click()
    yield lambda: not w.locked
    ok("unlock with new password", not w.locked)
    ok("Quick Unlock re-armed with the new password", w.quick is not None and w.quick.password() == PW)

    # 5. setting off
    vault.settings.setValue("quick_unlock", False); w._set_quick_unlock(False)
    ok("turning it off forgets the password", w.quick is None)
    lock(); yield visible_dialog
    d = visible_dialog()
    ok("off: plain 'Unlock'", d.yesButton.text() == "Unlock", d.yesButton.text())
    d.pw.setText(PW); d.yesButton.click()
    yield lambda: not w.locked
    ok("off: nothing kept after unlocking", w.quick is None)

    # 6. another database file: no Hello button
    vault.settings.setValue("quick_unlock", True)
    lock(); yield visible_dialog
    d = visible_dialog()
    d.pw.setText(PW); d.yesButton.click()
    yield lambda: not w.locked
    lock(); yield visible_dialog
    d = visible_dialog()
    d._set_path(str(s / "rt41.kdbx"))
    ok("different database file: plain 'Unlock'", d.yesButton.text() == "Unlock", d.yesButton.text())
    d._set_path(str(db_path))
    ok("same file again: Hello again", d.yesButton.text() == "Unlock with Windows Hello", d.yesButton.text())


def run(gen, deadline=[None]):
    def tick():
        try:
            cond = current[0]
            if cond is not None and not cond():
                if time.time() > deadline[0]:
                    ok("step finished in time", False, getattr(cond, "__name__", "condition"))
                    return finish()
                return QTimer.singleShot(50, tick)
            QTest.qWait(150)  # let the UI settle before the next step
            current[0] = next(gen)
            deadline[0] = time.time() + 20
            QTimer.singleShot(50, tick)
        except StopIteration:
            finish()
        except Exception as exc:
            import traceback; traceback.print_exc()
            ok("no exceptions", False, exc)
            finish()

    current = [None]
    deadline[0] = time.time() + 20
    QTimer.singleShot(200, tick)


def finish():
    print(f"--- {'ALL PASSED' if not fails else str(len(fails)) + ' FAILED'}", flush=True)
    os._exit(1 if fails else 0)


run(steps())
QTimer.singleShot(180_000, lambda: (ok("whole test in time", False), finish()))
app.exec()
