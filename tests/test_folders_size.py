"""Folder icons from the database, compact indentation, and the Text size setting.
Run with SCALE=1.25 in the environment to take the screenshot at that size (as Vault does on start)."""
import os, shutil, sys
from pathlib import Path
import helpers  # repo path; temporary folder, settings and test databases
scale = os.environ.get("SCALE")
if scale:
    os.environ["QT_SCALE_FACTOR"] = scale
from PySide6.QtCore import QSettings, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from pykeepass import PyKeePass

s = helpers.WORK
fails = []


def ok(label, cond, extra=""):
    print(("OK   " if cond else "FAIL ") + label + ("" if cond else f"  [{extra}]"), flush=True)
    if not cond:
        fails.append(label)


db_path = s / "foldericons41.kdbx"
shutil.copy(s / "rt41.kdbx", db_path)
kp = PyKeePass(str(db_path), password="test-pw-123")
bank = kp.add_group(kp.root_group, "Banking", icon="37")     # KeePass "Homebanking"
mail = kp.add_group(kp.root_group, "Email", icon="19")       # "EMail"
plain = kp.add_group(kp.root_group, "Plain folder")          # default folder (48)
keys = kp.add_group(bank, "Cards", icon="0")                 # the key icon
kp.save()

app = QApplication(sys.argv)
import vault, store
ini = s / "foldersize.ini"; ini.unlink(missing_ok=True)
vault.settings = QSettings(str(ini), QSettings.IniFormat)
store.backup_dir = lambda: s / "foldersize_backups"
restarts = []
# Replace restart on the CLASS, before the window exists: Settings keeps a reference to the method it
# was given, so patching the instance afterwards (as before) let a real restart through.
vault.MainWindow.restart = lambda self: restarts.append(1)
from PySide6.QtCore import QProcess  # belt and braces: a test may never start another process
QProcess.startDetached = staticmethod(lambda *a, **k: (_ for _ in ()).throw(RuntimeError("test tried to start a process")))
w = vault.MainWindow()
w.setMicaEffectEnabled(False); w.resize(1250, 720); w.show(); QTest.qWaitForWindowExposed(w)
db = store.Database(db_path, "test-pw-123", "")
w.vault.load(db); w.saver.attach(db); w.locked = False
QTest.qWait(400)

items = {}
it = vault.QTreeWidgetItemIterator(w.vault.tree)
while it.value():
    items[it.value().text(0).split("  ")[0]] = it.value(); it += 1
key = lambda name: items[name].icon(0).cacheKey()
icons = w.vault.model.icons
ok("folder snapshot carries KeePass icon numbers", {f["name"]: f["icon"][0] for f in db.folders}.get("Banking") == 37)
ok("Banking shows KeePass's online-banking icon", key("Banking") == icons.folder((37, None)).cacheKey())
ok("Email shows the e-mail icon", key("Email") == icons.folder((19, None)).cacheKey())
ok("a folder with the key icon shows the key", icons.folder((0, None)) is not None and key("Cards") == icons.folder((0, None)).cacheKey())
ok("plain folders keep the theme's folder icon", icons.folder((48, None)) is None and key("Plain folder") != key("Banking"))
ok("the Recycle Bin keeps its bin icon", "Recycle Bin" in items and key("Recycle Bin") not in (key("Banking"), key("Plain folder")))
ok("indentation is 10 px per level", w.vault.tree.indentation() == 10)

w.switchTo(w.vault); QTest.qWait(300)
w.grab().save(str(s / f"foldersize_{scale or '1.0'}.png"))
print(f"--- {'ALL PASSED' if not fails else str(len(fails)) + ' FAILED'}", flush=True)
sys.stdout.flush(); os._exit(1 if fails else 0)
