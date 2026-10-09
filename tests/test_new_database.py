"""First run: no database yet. Create one from the unlock screen; it opens straight away, is KDBX 4.1,
never overwrites a file, and the next launch offers it."""
import sys
import helpers  # repo path; temporary folder, settings and test databases
from helpers import ok, wait, finish
from PySide6.QtCore import QTimer
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QFileDialog
from pykeepass import PyKeePass

app = QApplication(sys.argv)
import vault, store

folder = helpers.WORK / "new-db"
folder.mkdir(exist_ok=True)
QFileDialog.getExistingDirectory = staticmethod(lambda *a, **k: str(folder))
(folder / "Taken.kdbx").write_bytes(b"not mine")
w = vault.MainWindow(); w.setMicaEffectEnabled(False); w.resize(1100, 700); w.show(); QTest.qWaitForWindowExposed(w)
seen = {}


def in_dialog(cls, action):
    def step():
        d = next((d for d in w.findChildren(cls) if d.isVisible()), None)
        if d is None:
            QTimer.singleShot(50, step); return
        QTest.qWait(100)
        action(d)
    QTimer.singleShot(80, step)


def on_unlock(d):
    seen["label"] = d.file_label.text()
    in_dialog(vault.NewDatabaseDialog, on_new)
    d.new_btn.click()  # opens NewDatabaseDialog (nested), then unlocks


def on_new(d):
    seen["default_name"] = d.name.text()
    d._choose_folder()
    d.name.setText("Taken")
    d.new.setText("Family-Passw0rd-123"); d.repeat.setText("Family-Passw0rd-123")
    d.yesButton.click(); QTest.qWait(100)
    seen["exists_error"] = d.error.text() if d.error.isVisible() else None
    d.name.setText("Family")
    d.repeat.setText("typo"); d.yesButton.click(); QTest.qWait(50)
    seen["mismatch_error"] = d.error.text()
    d.repeat.setText("Family-Passw0rd-123")
    w.grab().save(str(helpers.WORK / "new_database.png"))
    d.yesButton.click()


in_dialog(vault.UnlockDialog, on_unlock)
w._show_unlock()
ok("first run: the unlock screen says there's no database yet", "make a new one" in seen.get("label", ""), seen)
ok("suggests a name", seen.get("default_name") == "Passwords")
ok("won't overwrite an existing file", "already exists" in (seen.get("exists_error") or ""), seen)
ok("…which is untouched", (folder / "Taken.kdbx").read_bytes() == b"not mine")
ok("passwords must match", "don't match" in seen.get("mismatch_error", ""), seen)
path = folder / "Family.kdbx"
ok("created and opened straight away", wait(lambda: not w.locked) and path.exists() and w.saver.db and w.saver.db.path == str(path))
kp = PyKeePass(str(path), password="Family-Passw0rd-123")
ok("KDBX 4.1, named", kp.version == (4, 1) and kp.root_group.name == "Family", (kp.version, kp.root_group.name))
ok("empty and editable", w.saver.db.entries == [] and w.saver.db.writable)
ok("remembered for next time", vault.settings.value("last_file") == str(path), vault.settings.value("last_file"))
ok("no stray temporary files", sorted(p.name for p in folder.iterdir()) == ["Family.kdbx", "Taken.kdbx"], list(folder.iterdir()))
finish()
