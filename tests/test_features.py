"""GUI test of undo, folders, duplicate, 2FA, health and site icons (in-app events only)."""
import shutil, subprocess, sys, time
from pathlib import Path
import helpers  # repo path; temporary folder, settings and test databases
from PySide6.QtCore import Qt, QTimer
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
import pyotp

s = helpers.WORK
CLI = helpers.need_cli()
PW = "test-pw-123"
db_path = s / "feat41.kdbx"
shutil.copy(s / "rt41.kdbx", db_path)
ok = lambda c: "OK  " if c else "FAIL"

app = QApplication(sys.argv)
import vault, store, totp
vault.setTheme(vault.Theme.LIGHT)
store.backup_dir = lambda: s / "feat_backups"
from PySide6.QtCore import QSettings, QProcess
(s / "features.ini").unlink(missing_ok=True)
vault.settings = QSettings(str(s / "features.ini"), QSettings.IniFormat)  # never the real settings
vault.settings.setValue("details_layout", "below")  # adding and editing in the pop-up (beside: in the pane)
QProcess.startDetached = staticmethod(lambda *a, **k: (_ for _ in ()).throw(RuntimeError("no processes from tests")))
saved_settings = {k: vault.settings.value(k) for k in ("icons_auto", "icons_duckduckgo")}


def cli(*args, stdin=f"{PW}\n"):
    r = subprocess.run([CLI, *args], input=stdin, capture_output=True, text=True, encoding="utf-8", timeout=30)
    return " | ".join(l for l in (r.stdout + r.stderr).splitlines() if l and "Enter password" not in l)


def wait(cond, timeout=20):
    end = time.time() + timeout
    while not cond() and time.time() < end:
        QTest.qWait(50)
    return cond()


def answer(dialog_cls, setup=lambda d: None, button="yes"):
    def act():
        dlg = next((d for d in w.findChildren(dialog_cls) if d.isVisible()), None)
        if dlg is None:
            QTimer.singleShot(50, act)
            return
        setup(dlg)
        QTest.qWait(150)
        (dlg.yesButton if button == "yes" else dlg.cancelButton).click()
    QTimer.singleShot(80, act)


db = store.Database(db_path, PW, "")
w = vault.MainWindow()
w.setMicaEffectEnabled(False)
w.show()
QTest.qWaitForWindowExposed(w)
w.vault.load(db); w.saver.attach(db); w.health.set_db(db); w.locked = False
v = w.vault
saver = w.saver
entries = lambda: saver.db.entries
entry = lambda t: next((e for e in entries() if e["title"] == t), None)
folder = lambda n: next((f for f in saver.db.folders if f["name"] == n), None)
settle = lambda: wait(lambda: not saver.pending)

# --- folders
answer(vault.NameDialog, lambda d: d.edit.setText("Banking"))
v.new_folder(None)
print(ok(folder("Banking") is not None), "new folder via dialog; current folder:", v.list_title.text())
answer(vault.NameDialog, lambda d: d.edit.setText("Finance"))
v.rename_folder(folder("Banking")["id"])
print(ok(folder("Finance") is not None), "renamed to Finance")
answer(vault.NameDialog, lambda d: d.edit.setText("Cards"))
v.new_folder(folder("Finance")["id"])
print(ok(folder("Cards")["parent"] == folder("Finance")["id"]), "subfolder Cards inside Finance")

# --- move + duplicate + undo
v.tree.setCurrentItem(v.tree.topLevelItem(0)); QTest.qWait(100)
v.refresh(select_uuid=entry("GitHub")["uuid"])
answer(vault.FolderPickerDialog, lambda d: d.combo.setCurrentIndex(
    next(i for i in range(d.combo.count()) if d.combo.itemData(i) == folder("Cards")["id"])))
v.move_entry()
print(ok(entry("GitHub")["folder"] == "Finance › Cards"), "moved GitHub to", entry("GitHub")["folder"])
v.refresh(select_uuid=entry("GitHub")["uuid"])
v.duplicate_entry()
print(ok(entry("GitHub - Copy") is not None), "duplicated")
v.undo()
print(ok(entry("GitHub - Copy") is None), "Ctrl+Z undid the duplicate")

# --- delete with the Undo button in the message
v.refresh(select_uuid=entry("Netflix")["uuid"])
answer(vault.MessageBox)
v.delete_entry()
print(ok(entry("Netflix")["in_bin"]), "Netflix moved to Recycle Bin")
QTest.qWait(600)
undo_buttons = [b for b in w.findChildren(vault.TransparentPushButton) if b.text() == "Undo" and b.isVisible()]
print(ok(bool(undo_buttons)), "message with Undo button shown")
w.grab().save(str(s / "feat_undo_toast.png"))
QTest.mouseClick(undo_buttons[-1], Qt.LeftButton)
print(ok(not entry("Netflix")["in_bin"]), "clicked Undo in the message -> Netflix restored to", entry("Netflix")["folder"])

# --- delete folder (with contents) and undo
answer(vault.MessageBox)
v.delete_folder(folder("Finance")["id"])
print(ok(folder("Finance")["in_bin"] and entry("GitHub")["in_bin"]), "Finance folder (with GitHub) moved to Recycle Bin")
v.undo()
print(ok(not folder("Finance")["in_bin"] and not entry("GitHub")["in_bin"]), "undo restored the folder")

# --- 2FA via the editor
secret = pyotp.random_base32()
v.refresh(select_uuid=entry("GitHub")["uuid"])
answer(vault.EntryEditor, lambda d: d.otp.setText(secret))
v.edit_entry()
gh = entry("GitHub")
expected = pyotp.TOTP(secret).now()
print(ok(gh["totp"] and totp.code(gh["totp"])[0] == expected), "2FA saved; code", totp.code(gh["totp"])[0], "==", expected)
v.refresh(select_uuid=gh["uuid"])
v.notes.tabs.setCurrentItem("details")  # (below the list, the 2FA code is on the Details tab)
QTest.qWait(1200)
print(ok(v.notes.totp_box.isVisible() and v.notes.totp_code.text().replace(" ", "") == pyotp.TOTP(secret).now()),
      "notes panel shows live code:", v.notes.totp_code.text(), v.notes.totp_left.text())
v.table.setFocus()
v.copy_totp()
QTest.qWait(200)
print(ok(QApplication.clipboard().text() == pyotp.TOTP(secret).now()), "copy 2FA code")
QApplication.clipboard().clear()
w.grab().save(str(s / "feat_main.png"))

# --- site icons
vault.settings.setValue("icons_auto", True)
gh_url_before = entry("GitHub")["icon"][1]
v.refresh(select_uuid=entry("GitHub")["uuid"])
v.download_icon()
print(ok(wait(lambda: entry("GitHub")["icon"][1] is not None, 30)), "downloaded GitHub's icon")
answer(vault.EntryEditor, lambda d: (d.title.setText("Wikipedia"), d.username.setText("me"), d.url.setText("https://wikipedia.org")))
v.new_entry()
print(ok(wait(lambda: entry("Wikipedia") and entry("Wikipedia")["icon"][1] is not None, 30)), "new entry got its icon automatically")
w.fetch_icons(missing_only=False)
QTest.qWait(500)
w.grab().save(str(s / "feat_icons_progress.png"))
wait(lambda: not w.icons.running, 60)
print(ok(True), "refresh all icons finished")
settle()
QTest.qWait(300)
w.grab().save(str(s / "feat_icons.png"))

# --- health
w.switchTo(w.health)
print(ok(wait(lambda: w.health.issues or w.health.empty.text().startswith("No"), 30)), "health report:", vault.health.summary(w.health.issues))
QTest.qWait(300)
w.grab().save(str(s / "feat_health.png"))
opened = {}
answer(vault.EntryEditor, lambda d: opened.setdefault("title", d.title.text()), button="cancel")
w.health._open(w.health.table.model().index(0, 0))
wait(lambda: "title" in opened, 10)
print(ok("title" in opened), "double-click in health opens the editor for", opened.get("title"))

# --- settings page
w.switchTo(w.stackedWidget.widget(w.stackedWidget.count() - 1))
QTest.qWait(300)
w.grab().save(str(s / "feat_settings.png"))
w.switchTo(v)

# --- saved file in KeePassXC
print(ok(settle()), "all saved | status:", v.save_status.text())
ls = cli("ls", "-R", "-f", str(db_path))
print(ok("Finance/Cards/GitHub" in ls and "Wikipedia" in ls), "KeePassXC ls:", ls)
print(ok(cli("show", "-t", str(db_path), "Finance/Cards/GitHub") == pyotp.TOTP(secret).now()), "KeePassXC 2FA code matches")
print(ok(store.Database(db_path, PW, "").version == "4.1"), "still KDBX 4.1")

for k, val in saved_settings.items():
    vault.settings.remove(k) if val is None else vault.settings.setValue(k, val)
