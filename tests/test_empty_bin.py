"""Empty Recycle Bin: asks, deletes entries and folders in the bin (incl. nested), saved to the file,
leaves everything else, Undo restores, Cancel does nothing. Steps run from timers."""
import os, shutil, sys, time
from pathlib import Path
import helpers  # repo path; temporary folder, settings and test databases
from PySide6.QtCore import QSettings, QTimer
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from pykeepass import PyKeePass

s = helpers.WORK
fails = []


def ok(label, cond, extra=""):
    print(("OK   " if cond else "FAIL ") + label + ("" if cond else f"  [{extra}]"), flush=True)
    if not cond:
        fails.append(label)


db_path = s / "emptybin41.kdbx"
shutil.copy(s / "rt41.kdbx", db_path)
kp = PyKeePass(str(db_path), password="test-pw-123")
bin_group = kp.recyclebin_group
old = kp.add_group(bin_group, "Old stuff")
kp.add_entry(old, "Nested old entry", "u", "p")
kp.add_entry(kp.root_group, "Keep me", "u", "p")
kp.save()
in_bin_before = len([e for e in PyKeePass(str(db_path), password="test-pw-123").entries if e.group.uuid != kp.root_group.uuid and ("Recycle" in (e.group.name or "") or e.group.name == "Old stuff")])

app = QApplication(sys.argv)
import vault, store
from PySide6.QtCore import QProcess
QProcess.startDetached = staticmethod(lambda *a, **k: (_ for _ in ()).throw(RuntimeError("no processes from tests")))
ini = s / "emptybin.ini"; ini.unlink(missing_ok=True)
vault.settings = QSettings(str(ini), QSettings.IniFormat)
store.backup_dir = lambda: s / "emptybin_backups"
w = vault.MainWindow(); w.setMicaEffectEnabled(False); w.resize(1250, 760); w.show(); QTest.qWaitForWindowExposed(w)
db = store.Database(db_path, "test-pw-123", "")
w.vault.load(db); w.saver.attach(db); w.locked = False
v = w.vault
box = lambda: next((b for b in w.findChildren(vault.MessageBox) if b.isVisible()), None)
in_bin = lambda: [e for e in w.saver.db.entries if e["in_bin"]]
bin_folders = lambda: [f for f in w.saver.db.folders if f["in_bin"] and f["id"] != w.saver.db.bin_id]
outside = lambda: sorted(e["title"] for e in w.saver.db.entries if not e["in_bin"])
settle = lambda: not w.saver.pending


def steps():
    before_bin, before_outside = len(in_bin()), outside()
    ok("starting state: entries and a folder in the bin", before_bin >= 3 and len(bin_folders()) == 1, (before_bin, bin_folders()))
    QTimer.singleShot(0, v.empty_recycle_bin); yield box
    b = box()
    ok("asks first, saying how much", "entries" in b.contentLabel.text() and "folder" in b.contentLabel.text(), b.contentLabel.text())
    b.cancelButton.click(); yield lambda: box() is None
    QTest.qWait(300)
    ok("Cancel: nothing deleted", len(in_bin()) == before_bin)
    QTimer.singleShot(0, v.empty_recycle_bin); yield box
    box().yesButton.click(); yield lambda: box() is None
    yield settle
    QTest.qWait(500)
    ok("emptied: no entries or folders left in the bin", not in_bin() and not bin_folders(), (in_bin(), bin_folders()))
    ok("everything outside the bin untouched", outside() == before_outside, outside())
    kp2 = PyKeePass(str(db_path), password="test-pw-123")
    ok("saved: the file's Recycle Bin is empty", not kp2.recyclebin_group.entries and not kp2.recyclebin_group.subgroups)
    v.undo(); yield settle
    QTest.qWait(500)
    ok("Undo brings it all back (incl. the nested folder and its entry)",
       len(in_bin()) == before_bin and len(bin_folders()) == 1, (len(in_bin()), bin_folders()))


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
    sys.stdout.flush(); os._exit(1 if fails else 0)


run(steps())
QTimer.singleShot(120_000, lambda: (ok("whole test in time", False), finish()))
app.exec()
