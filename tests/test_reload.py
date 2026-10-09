import shutil, subprocess, sys, time
import helpers  # repo path; temporary folder, settings and test databases
from pathlib import Path
from PySide6.QtCore import QSettings
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

s = helpers.WORK
CLI = helpers.need_cli()
PW = "test-pw-123"
path = s / "reload41.kdbx"
shutil.copy(s / "dnd41.kdbx", path)
app = QApplication(sys.argv)
import vault, store
vault.settings = QSettings(str(s / "reload_test.ini"), QSettings.IniFormat)
vault.settings.clear()
store.backup_dir = lambda: s / "reload_backups"
ok = lambda c: "OK  " if c else "FAIL"


def cli(*args):
    r = subprocess.run([CLI, *args], input=PW + "\n", capture_output=True, text=True, encoding="utf-8", timeout=30)
    return (r.stdout + r.stderr).strip()


def wait(cond, timeout=15):
    end = time.time() + timeout
    while not cond() and time.time() < end:
        QTest.qWait(50)
    return cond()


def messages():
    return [(b.titleLabel.text(), b.contentLabel.text()) for b in w.findChildren(vault.InfoBar) if b.isVisible()]


db = store.Database(path, PW, "")
w = vault.MainWindow()
w.show(); QTest.qWaitForWindowExposed(w)
w.vault.load(db); w.saver.attach(db); w.locked = False
saver, v = w.saver, w.vault
entry = lambda t: next((e for e in saver.db.entries if e["title"] == t), None)
saver.poll_timer.stop()  # test the button first, without the automatic check

v.check_for_changes()
print(ok(wait(lambda: any(t == "Up to date" for t, _ in messages()))), "no outside change -> 'Up to date':", messages())

cli("edit", "-u", "changed-by-keepassxc", str(path), "Work/Netflix")
v.check_for_changes()
print(ok(wait(lambda: entry("Netflix")["username"] == "changed-by-keepassxc")), "button picked up KeePassXC's edit")
print(ok(v.save_status.text().startswith("·  Updated from elsewhere at")), "status:", v.save_status.text())

# automatic check (every 4 s)
saver.poll_timer.start()
cli("edit", "-u", "second-change", str(path), "Work/Netflix")
t = time.time()
print(ok(wait(lambda: entry("Netflix")["username"] == "second-change", 15)), f"automatic check picked it up in {time.time() - t:.1f}s")

# pending edit + outside change -> button saves and merges
saver.poll_timer.stop()
saver.save_timer.setInterval(60000)
wiki = entry("Wikipedia")
saver.submit(store.Op("update", wiki["uuid"], fields={"notes": "mine"}, base_mtime=wiki["base_mtime"], title="Wikipedia"))
cli("edit", "-u", "third-change", str(path), "Work/Netflix")
v.check_for_changes()
print(ok(wait(lambda: not saver.pending and entry("Netflix")["username"] == "third-change"
               and entry("Wikipedia")["notes"] == "mine", 20)), "with an unsaved edit: saved and merged both changes")
print(ok("mine" in cli("show", "-a", "Notes", str(path), "Work/Wikipedia")), "KeePassXC sees our edit too")

# file temporarily missing (e.g. Drive not running)
hidden = path.with_suffix(".hidden")
path.rename(hidden)
v.check_for_changes()
print(ok(wait(lambda: any(t == "Can't read the file" for t, _ in messages()))), "file missing -> warning shown")
hidden.rename(path)
