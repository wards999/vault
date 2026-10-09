"""Changing the master password: checks, the new password opens the file, a backup still opens with the
old one, KeePassXC agrees, and a clash with another device leaves the old password in place."""
import subprocess
import sys
import helpers  # repo path; temporary folder, settings and test databases
from helpers import ok, wait, finish
from PySide6.QtCore import QTimer
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from pykeepass import PyKeePass

app = QApplication(sys.argv)
import vault, store

path = helpers.copy_db("rt41.kdbx", "master41.kdbx")
w = vault.MainWindow(); w.setMicaEffectEnabled(False); w.resize(1100, 700); w.show(); QTest.qWaitForWindowExposed(w)
db = store.Database(path, helpers.PW, "")
w.vault.load(db); w.saver.attach(db); w.health.set_db(db); w.locked = False
w.saver.poll_timer.stop()  # this test changes the file "elsewhere" on purpose


def opens(password, file=path):
    try:
        PyKeePass(str(file), password=password)
        return True
    except Exception:
        return False


def dialog_step(fill, expect_error=None, cancel_after=False):
    seen = {}
    def step():
        d = next((d for d in w.findChildren(vault.ChangeMasterDialog) if d.isVisible()), None)
        if d is None:
            QTimer.singleShot(50, step); return
        fill(d); QTest.qWait(50)
        d.yesButton.click(); QTest.qWait(100)
        seen["error"] = d.error.text() if d.error.isVisible() else None
        seen["strength"] = d.strength_label.text()
        if d.isVisible():
            d.cancelButton.click()
    QTimer.singleShot(80, step)
    return seen


def fill(current, new, repeat):
    return lambda d: (d.current.setText(current), d.new.setText(new), d.repeat.setText(repeat))


seen = dialog_step(fill("wrong", "Brand-new-Passw0rd!", "Brand-new-Passw0rd!"))
w.change_master_password()
ok("wrong current password is refused", seen.get("error") == "That isn't the current master password.", seen)
seen = dialog_step(fill(helpers.PW, "Brand-new-Passw0rd!", "Brand-new-Passw0rd?"))
w.change_master_password()
ok("mismatched new passwords are refused", seen.get("error") == "The two new passwords don't match.", seen)
ok("strength is shown", "bits" in seen.get("strength", ""), seen)
ok("nothing changed yet", opens(helpers.PW))

# A pending edit first: it must be saved (with the old password) before the change
e = next(x for x in w.saver.db.entries if x["title"] == "Netflix")
w.saver.submit(store.Op("update", e["uuid"], fields={"username": "edited"}, all_fields=dict(e["raw"], username="edited"),
                        folder=e["folder_id"], base_mtime=e["base_mtime"], title="Netflix"), "test")
backups = helpers.WORK / "backups"
before = set(backups.glob("master41*")) if backups.exists() else set()
NEW = "Brand-new-Passw0rd!"
seen = dialog_step(fill(helpers.PW, NEW, NEW))
w.change_master_password()
ok("accepted", seen.get("error") is None, seen)
ok("saved", wait(lambda: not w.saver.pending and opens(NEW), 30))
ok("the file opens with the new password", opens(NEW))
ok("…and no longer with the old one", not opens(helpers.PW))
kp = PyKeePass(str(path), password=NEW)
ok("the pending edit was kept", kp.find_entries(title="Netflix", first=True).username == "edited")
new_backups = set(backups.glob("master41*")) - before
ok("a backup was made", bool(new_backups), list(backups.glob("*")) if backups.exists() else "no backups folder")
ok("…and it opens with the OLD password", any(opens(helpers.PW, b) for b in new_backups))
import shutil
from pathlib import Path
cli = shutil.which("keepassxc-cli") or r"C:\Program Files\KeePassXC\keepassxc-cli.exe"
if Path(cli).exists():  # optional cross-check with KeePassXC
    r = subprocess.run([cli, "ls", str(path)], input=NEW + "\n", capture_output=True, text=True, timeout=60)
    ok("KeePassXC opens it with the new password", "Work/" in r.stdout, r.stdout + r.stderr)

# Editing after the change saves with the new password
e = next(x for x in w.saver.db.entries if x["title"] == "Netflix")
w.saver.submit(store.Op("update", e["uuid"], fields={"username": "again"}, all_fields=dict(e["raw"], username="again"),
                        folder=e["folder_id"], base_mtime=e["base_mtime"], title="Netflix"), "test")
ok("later edits save with the new password",
   wait(lambda: not w.saver.pending and PyKeePass(str(path), password=NEW).find_entries(title="Netflix", first=True).username == "again", 30))

# Clash: another device changes the file just before the change is saved -> nothing changes
other = PyKeePass(str(path), password=NEW)
other.add_entry(other.root_group, "From phone", "p", "phone-pw")
other.save()
seen = dialog_step(fill(NEW, "Third-Passw0rd!!", "Third-Passw0rd!!"))
w.change_master_password()
ok("clash: still opens with the current password", wait(lambda: not w.saver.pending, 30) and opens(NEW) and not opens("Third-Passw0rd!!"))
ok("clash: Vault still uses the current password", w.saver.db.kp.password == NEW)
finish()
