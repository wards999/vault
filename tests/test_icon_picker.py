"""Change icon… for folders and entries: standard icon, default, image file; saved in the file
(checked by re-reading it with pykeepass), shown in Vault, and undoable. Steps run from timers."""
import os, shutil, sys, time
from pathlib import Path
import helpers  # repo path; temporary folder, settings and test databases
from PySide6.QtCore import QSettings, Qt, QTimer
from PySide6.QtGui import QColor, QImage
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QFileDialog
from pykeepass import PyKeePass

s = helpers.WORK
fails = []


def ok(label, cond, extra=""):
    print(("OK   " if cond else "FAIL ") + label + ("" if cond else f"  [{extra}]"), flush=True)
    if not cond:
        fails.append(label)


db_path = s / "iconpick41.kdbx"
shutil.copy(s / "foldericons41.kdbx", db_path)
image_path = s / "logo_test.png"
img = QImage(48, 48, QImage.Format_ARGB32); img.fill(QColor("#c03030")); img.save(str(image_path))

app = QApplication(sys.argv)
import vault, store
from PySide6.QtCore import QProcess
QProcess.startDetached = staticmethod(lambda *a, **k: (_ for _ in ()).throw(RuntimeError("no processes from tests")))
QFileDialog.getOpenFileName = staticmethod(lambda *a, **k: (str(image_path), ""))  # the "chosen" image
ini = s / "iconpick.ini"; ini.unlink(missing_ok=True)
vault.settings = QSettings(str(ini), QSettings.IniFormat)
store.backup_dir = lambda: s / "iconpick_backups"
w = vault.MainWindow(); w.setMicaEffectEnabled(False); w.resize(1300, 800); w.show(); QTest.qWaitForWindowExposed(w)
db = store.Database(db_path, "test-pw-123", "")
w.vault.load(db); w.saver.attach(db); w.locked = False
v = w.vault
picker = lambda: next((d for d in w.findChildren(vault.IconPickerDialog) if d.isVisible()), None)
folder_id = lambda name: next(f["id"] for f in w.saver.db.folders if f["name"] == name)
folder = lambda name: next(f for f in w.saver.db.folders if f["name"] == name)
entry = lambda title: next(e for e in w.saver.db.entries if e["title"] == title)
saved = lambda: PyKeePass(str(db_path), password="test-pw-123")
settle = lambda: not w.saver.pending


def steps():
    # Folder: a standard icon
    QTimer.singleShot(0, lambda: v.change_folder_icon(folder_id("Work"))); yield picker
    d = picker()
    ok("picker shows KeePass's standard icons", len(d.buttons.buttons()) >= 68, len(d.buttons.buttons()))
    ok("Apply is off until something is chosen", not d.yesButton.isEnabled())
    d.buttons.button(37).click(); d.yesButton.click()
    yield settle
    QTest.qWait(400)
    ok("folder 'Work' now has icon 37 in Vault", folder("Work")["icon"] == (37, None), folder("Work")["icon"])
    ok("…and in the saved file (KeePass will show it)", saved().find_groups(name="Work", first=True).icon == "37")
    # Folder: image file
    QTimer.singleShot(0, lambda: v.change_folder_icon(folder_id("Work"))); yield picker
    d = picker(); d._image_chosen(); d.yesButton.click()
    yield settle
    QTest.qWait(400)
    ok("folder with an image file: custom icon stored", folder("Work")["icon"][1] is not None, folder("Work")["icon"])
    # Folder: back to plain
    QTimer.singleShot(0, lambda: v.change_folder_icon(folder_id("Work"))); yield picker
    d = picker(); d._default_chosen(); d.yesButton.click()
    yield settle
    QTest.qWait(400)
    ok("Plain folder: back to the standard folder, no custom image", folder("Work")["icon"] == (48, None), folder("Work")["icon"])
    v.undo(); yield settle
    QTest.qWait(400)
    ok("Undo brings back the previous (image) icon", folder("Work")["icon"][1] is not None, folder("Work")["icon"])
    # Entry: standard icon, then default
    row = next(r for r in range(v.model.rowCount()) if v.model.entries[r]["title"] == "Netflix")
    v.table.selectRow(row); QTest.qWait(150)
    QTimer.singleShot(0, v.change_entry_icon); yield picker
    d = picker(); d.buttons.button(60).click(); d.yesButton.click()
    yield settle
    QTest.qWait(400)
    ok("entry Netflix: standard icon 60", entry("Netflix")["icon"] == (60, None), entry("Netflix")["icon"])
    ok("…saved in the file", saved().find_entries(title="Netflix", first=True).icon == "60")
    row = next(r for r in range(v.model.rowCount()) if v.model.entries[r]["title"] == "Netflix")
    v.table.selectRow(row); QTest.qWait(150)
    QTimer.singleShot(0, v.change_entry_icon); yield picker
    d = picker(); d._default_chosen(); d.yesButton.click()
    yield settle
    QTest.qWait(400)
    ok("entry back to Default (letter)", entry("Netflix")["icon"] == (0, None), entry("Netflix")["icon"])
    QTimer.singleShot(0, lambda: v.change_folder_icon(folder_id("Work"))); yield picker
    d = picker()
    w.grab().save(str(s / "icon_picker.png"))
    d.cancelButton.click()
    yield lambda: picker() is None
    ok("Cancel changes nothing", folder("Work")["icon"][1] is not None)


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
