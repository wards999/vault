import shutil, sys
import helpers  # repo path; temporary folder, settings and test databases
from pathlib import Path
from PySide6.QtCore import QSettings
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

s = helpers.WORK
app = QApplication(sys.argv)
import vault, store
vault.settings = QSettings(str(s / "folder_memory.ini"), QSettings.IniFormat)
vault.settings.clear()
ok = lambda c: "OK  " if c else "FAIL"
a, b = s / "fm_a.kdbx", s / "fm_b.kdbx"
shutil.copy(s / "dnd41.kdbx", a)
shutil.copy(s / "dnd41.kdbx", b)


def open_window(path):
    db = store.Database(path, "test-pw-123", "")
    w = vault.MainWindow()
    w.show(); QTest.qWaitForWindowExposed(w)
    w.vault.load(db); w.saver.attach(db); w.locked = False
    w._closing = True
    return w, db


def pick(w, name):
    f = next(f for f in w.vault.db.folders if f["name"] == name)
    w.vault.tree.setCurrentItem(w.vault.tree._item_for(f["id"]))
    QTest.qWait(100)


w, db = open_window(a)
print(ok(w.vault.list_title.text() == "All entries"), "first time: opens at the top level:", w.vault.list_title.text())
pick(w, "Cards")
w.close()
w, db = open_window(a)
print(ok(w.vault.list_title.text() == "Cards"), "reopened database A: back in", w.vault.list_title.text())
w.close()

w, db = open_window(b)
print(ok(w.vault.list_title.text() == "All entries"), "database B has its own memory (top level):", w.vault.list_title.text())
pick(w, "Work")
w.close()
w, _ = open_window(a)
print(ok(w.vault.list_title.text() == "Cards"), "A still remembers Cards")
w.close()
w, _ = open_window(b)
print(ok(w.vault.list_title.text() == "Work"), "B remembers Work")

# folder moved to the Recycle Bin since -> top level
cards = next(f for f in w.vault.db.folders if f["name"] == "Cards")
w.close()
w, db = open_window(a)
w.saver.submit(store.Op("folder_trash", cards["id"], title="Cards"))
for _ in range(200):
    if not w.saver.pending:
        break
    QTest.qWait(50)
print(ok(not w.saver.pending), "folder move saved")
w.close()
w, db = open_window(a)
print(ok(w.vault.list_title.text() == "All entries"), "remembered folder now in the Recycle Bin -> top level:", w.vault.list_title.text())

# remembered the Recycle Bin itself -> reopens it
pick(w, "Recycle Bin")
w.close()
w, _ = open_window(a)
print(ok(w.vault.list_title.text() == "Recycle Bin"), "remembered Recycle Bin reopens:", w.vault.list_title.text())
