import shutil, subprocess, sys, time
from pathlib import Path
import helpers  # repo path; temporary folder, settings and test databases
from PySide6.QtCore import QTimer
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

s = helpers.WORK
CLI = helpers.need_cli()
PW = "test-pw-123"
db_path = s / "gui41.kdbx"
shutil.copy(s / "rt41.kdbx", db_path)
ok = lambda c: "OK  " if c else "FAIL"

app = QApplication(sys.argv)
import vault, store
from PySide6.QtCore import QSettings
vault.settings = QSettings(str(s / 'edit_test.ini'), QSettings.IniFormat)
vault.settings.clear()
vault.settings.setValue("details_layout", "below")  # adding and editing in the pop-up (beside: in the pane)
vault.setTheme(vault.Theme.LIGHT)
store.backup_dir = lambda: s / "gui_backups"  # keep test backups out of the project
shutil.rmtree(s / "gui_backups", ignore_errors=True)


def cli(*args, stdin=f"{PW}\n"):
    r = subprocess.run([CLI, *args], input=stdin, capture_output=True, text=True, encoding="utf-8", timeout=30)
    return " | ".join(l for l in (r.stdout + r.stderr).splitlines() if l and "Enter password" not in l)


def wait(cond, timeout=20):
    end = time.time() + timeout
    while not cond() and time.time() < end:
        QTest.qWait(50)
    return cond()


def run_dialog(dialog_cls, setup, shot=None):
    """Opens the next dialog of dialog_cls, lets `setup` fill it, then clicks its yes button."""
    def act():
        dlg = next((w for w in QApplication.topLevelWidgets() + w_main.findChildren(dialog_cls)
                    if isinstance(w, dialog_cls) and w.isVisible()), None)
        if dlg is None:
            QTimer.singleShot(50, act)
            return
        setup(dlg)
        QTest.qWait(300)
        if shot:
            w_main.grab().save(str(s / shot))
        dlg.yesButton.click()
    QTimer.singleShot(100, act)


db = store.Database(db_path, PW, "")
w_main = vault.MainWindow()
w_main.setMicaEffectEnabled(False)
w_main.show()
QTest.qWaitForWindowExposed(w_main)
w_main.vault.load(db)
w_main.saver.attach(db)
w_main.locked = False
v = w_main.vault
print(ok(v.new_btn.isVisible()), "writable 4.1 db; New entry button visible; status:", v.save_status.text())

# 1. New entry with generated password
run_dialog(vault.EntryEditor, lambda d: (d.title.setText("Dropbox"), d.username.setText("me@x.com"),
                                         d.url.setText("https://dropbox.com")), shot="editor_new.png")
v.new_entry()
new_pw = next(e for e in db.entries if e["title"] == "Dropbox")["password"]
print(ok(len(new_pw) == 20), "new entry has generated password:", new_pw, "| status:", v.save_status.text())
print(ok(wait(lambda: not w_main.saver.pending)), "auto-saved | status:", v.save_status.text())
print(ok(new_pw in cli("show", "-s", "-a", "Password", str(db_path), "Dropbox")), "KeePassXC sees Dropbox:",
      cli("show", "-s", "-a", "UserName", "-a", "URL", str(db_path), "Dropbox"))
print(ok(len(list((s / "gui_backups").glob("*"))) == 1), "one backup made:", [p.name for p in (s / "gui_backups").glob("*")])

# 2. Edit GitHub: passphrase mode screenshot, then a typed password
gh_row = next(i for i, e in enumerate(v.model.entries) if e["title"] == "GitHub")
v.table.selectRow(gh_row)
def edit_github(d):
    d.gen_btn.setChecked(True)
    d.generator.mode.setCurrentItem("passphrase")
    d.generator._set_mode("passphrase")
    QTest.qWait(200)
    w_main.grab().save(str(s / "editor_passphrase.png"))
    d.password.setText("Typed-Pa55word!")
    d.notes.setPlainText("edited via Vault GUI")
run_dialog(vault.EntryEditor, edit_github, shot="editor_edit.png")
v.edit_entry()
print(ok(wait(lambda: not w_main.saver.pending)), "edit saved | status:", v.save_status.text())
print(ok("Typed-Pa55word!" in cli("show", "-s", "-a", "Password", str(db_path), "Work/GitHub")),
      "KeePassXC GitHub:", cli("show", "-s", "-a", "Password", "-a", "Notes", str(db_path), "Work/GitHub"))
print(ok(v.current_entry() and v.current_entry()["title"] == "GitHub"), "selection kept on GitHub after save")

# 3. Change made elsewhere is picked up automatically
cli("edit", "-u", "changed-in-kxc", str(db_path), "Dropbox")
print(ok(wait(lambda: next(e for e in w_main.saver.db.entries if e["title"] == "Dropbox")["username"] == "changed-in-kxc", 15)),
      "external KeePassXC edit auto-loaded")

# 4. Conflict: KeePassXC edits GitHub while we have an unsaved edit of GitHub -> Keep mine
w_main.saver.SAVE_DELAY_MS = 60000
w_main.saver.save_timer.setInterval(60000)
w_main.saver.poll_timer.stop()
gh = next(e for e in w_main.saver.db.entries if e["title"] == "GitHub")
w_main.saver.submit(store.Op("update", gh["uuid"], fields={"username": "mine-wins"}, all_fields={**gh["raw"], "username": "mine-wins"},
                             folder=gh["folder_id"], base_mtime=gh["base_mtime"], title="GitHub"))
cli("edit", "-u", "theirs-loses", "--url", "https://kxc.example", str(db_path), "Work/GitHub")
run_dialog(vault.ConflictDialog, lambda d: None, shot="conflict.png")
w_main.saver.save_now()
print(ok(wait(lambda: not w_main.saver.pending)), "conflict resolved + saved | status:", v.save_status.text())
print(ok("mine-wins" in cli("show", "-a", "UserName", str(db_path), "Work/GitHub")), "KeePassXC GitHub username:",
      cli("show", "-a", "UserName", "-a", "URL", str(db_path), "Work/GitHub"))
w_main.saver.save_timer.setInterval(1500)
w_main.saver.poll_timer.start()

# 5. Delete -> Recycle Bin
dbx_row = next(i for i, e in enumerate(v.model.entries) if e["title"] == "Dropbox")
v.table.selectRow(dbx_row)
run_dialog(vault.MessageBox, lambda d: None)
v.delete_entry()
print(ok(wait(lambda: not w_main.saver.pending)), "delete saved")
print(ok("Recycle Bin/Dropbox" in cli("ls", "-R", "-f", str(db_path))), "KeePassXC ls:", cli("ls", "-R", "-f", str(db_path)))

# 6. Lock waits for pending edits
nf = next(e for e in w_main.saver.db.entries if e["title"] == "Netflix")
w_main._show_unlock = lambda: None  # don't block on the unlock dialog in the test
w_main.saver.submit(store.Op("update", nf["uuid"], fields={"notes": "saved before lock"}, all_fields={**nf["raw"], "notes": "saved before lock"},
                             folder=nf["folder_id"], base_mtime=nf["base_mtime"], title="Netflix"))
w_main.lock()
print(ok(wait(lambda: w_main.locked and w_main.saver.db is None)), "locked after saving")
print(ok("saved before lock" in cli("show", "-a", "Notes", str(db_path), "Work/Netflix")), "edit made just before lock is on disk")

print(ok(store.Database(db_path, PW, "").version == "4.1"), "file is still KDBX 4.1")
print(ok(not list(s.glob(".*vault-tmp"))), "no temp files left")
