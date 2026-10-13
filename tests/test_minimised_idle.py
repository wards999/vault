"""Minimised, Vault does nothing: no 2FA countdown, no file checks, no animations, no timers at all.
Restored, it catches up straight away (2FA code running, changes from other devices picked up)."""
import collections
import sys
import helpers  # repo path; temporary folder, settings and test databases
from helpers import ok, wait, finish
from PySide6.QtCore import QEvent, QEventLoop, QObject, QTimer
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from pykeepass import PyKeePass

app = QApplication(sys.argv)
import vault, store


class Timers(QObject):
    def __init__(self):
        super().__init__()
        self.on, self.seen = False, collections.Counter()

    def eventFilter(self, obj, event):
        if self.on and event.type() == QEvent.Timer and obj is not quit_timer:
            self.seen[obj.metaObject().className() + (f" < {obj.parent().metaObject().className()}" if obj.parent() else "")] += 1
        return False


timers = Timers()
app.installEventFilter(timers)
path = helpers.copy_db("dnd41.kdbx", "idle41.kdbx")
w = vault.MainWindow(); w.setMicaEffectEnabled(False); w.show(); QTest.qWaitForWindowExposed(w)
db = store.Database(path, helpers.PW, "")
w.vault.load(db); w.saver.attach(db); w.locked = False
notes = w.vault.notes
gh = next(e for e in db.entries if e["title"] == "GitHub")
w.vault.refresh(select_uuid=gh["uuid"]); QTest.qWait(1500)
ok("open: the 2FA countdown runs", notes.totp_timer.isActive() and notes.totp_box.isVisible())
ok("open: checking for changes elsewhere", w.saver.poll_timer.isActive())
ok("the 2FA ring doesn't animate (it cost ~4% CPU)", not notes.totp_ring.isUseAni())

w.showMinimized(); QTest.qWait(2500)  # includes the memory trim at 1.5 s
ok("minimised: 2FA countdown stopped", not notes.totp_timer.isActive())
ok("minimised: file checks stopped", not w.saver.poll_timer.isActive())
quit_timer = QTimer(singleShot=True, interval=10_000)
loop = QEventLoop(); quit_timer.timeout.connect(loop.quit)
timers.on = True; quit_timer.start(); loop.exec(); timers.on = False
ok("minimised for 10 s: no timer fired at all", not timers.seen, dict(timers.seen))
WINDOWS = sys.platform == "win32"  # the later, light trims are Windows only
ok("…the later memory trims are still to come (Windows, once idle threads have exited)",
   w.late_trim.isActive() == WINDOWS)

# Something changes on another device while Vault is minimised
other = PyKeePass(str(path), password=helpers.PW)
other.add_entry(other.root_group, "From phone", "p", "phone-pw")
other.save()
w.vault.refresh(select_uuid=gh["uuid"])  # e.g. a reload while minimised must not restart the countdown
ok("still minimised: countdown not restarted by a refresh", not notes.totp_timer.isActive())
# (macOS says "minimised" before its minimise animation: a cover then would flash up in it)
ok("minimised, unlocked: no privacy cover", not w.privacy_cover.isVisible())
w.showNormal(); QApplication.processEvents()
ok("restored: no cover (no flash of it)", not w.privacy_cover.isVisible())
QTest.qWaitForWindowExposed(w)
ok("restored: changes made elsewhere are picked up at once",
   wait(lambda: any(e["title"] == "From phone" for e in w.saver.db.entries), 10))
ok("restored: file checks running again", w.saver.poll_timer.isActive())
w.vault.refresh(select_uuid=next(e for e in w.saver.db.entries if e["title"] == "GitHub")["uuid"]); QTest.qWait(300)
ok("restored: 2FA countdown running again", notes.totp_timer.isActive())
ok("restored: the later trims are cancelled", not w.late_trim.isActive())

# The trims, sped up: a full one 1.5 s after minimising, on Windows two light ones later, then nothing more
trims = []
real_trim = vault.trim_memory
vault.trim_memory = lambda light=False: trims.append("light" if light else "full") or real_trim(light)
w.LATE_TRIMS_MS = (2500, 4000)
w.showMinimized(); QTest.qWait(7000)
ok("minimised: memory trimmed in full once, then (Windows) lightly twice, then left alone",
   trims == (["full", "light", "light"] if WINDOWS else ["full"]), trims)
ok("…the trim timer is done", not w.late_trim.isActive())
w.showNormal(); QTest.qWaitForWindowExposed(w)
vault.trim_memory = real_trim
finish()
