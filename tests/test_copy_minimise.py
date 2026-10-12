"""Double-clicking an entry copies its password and minimises Vault, unless Settings →
"Minimise after double-click copy" is off: then Vault stays open."""
import sys
import helpers  # repo path; temporary folder, settings and test databases
from helpers import ok, wait, finish
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

app = QApplication(sys.argv)
import vault, store

path = helpers.copy_db("dnd41.kdbx", "copymin41.kdbx")
w = vault.MainWindow(); w.setMicaEffectEnabled(False); w.show(); QTest.qWaitForWindowExposed(w)
db = store.Database(path, helpers.PW, "")
w.vault.load(db); w.saver.attach(db); w.locked = False
v = w.vault
row = next(i for i, e in enumerate(v.model.entries) if e["password"])
entry = v.model.entries[row]
password = cell = v.model.index(row, vault.EntryModel.TITLE)  # the card

v._on_double_click(password)
ok("on: the password is copied", QApplication.clipboard().text() == entry["password"])
ok("on: Vault minimises", wait(lambda: w.isMinimized(), 5))
w.showNormal(); QTest.qWaitForWindowExposed(w); QTest.qWait(300)

# The double-click fires on the second press: minimising before the release left the list thinking the
# button was still down (macOS), so moving the mouse dragged the row's picture around the screen.
spot = v.table.visualRect(password).center()
QTest.mousePress(v.table.viewport(), Qt.LeftButton, Qt.NoModifier, spot)
v._on_double_click(password)
QTest.qWait(300)
ok("button still down: not minimised yet", not w.isMinimized(), QApplication.mouseButtons())
QTest.mouseRelease(v.table.viewport(), Qt.LeftButton, Qt.NoModifier, spot)
ok("button up: Vault minimises", wait(lambda: w.isMinimized(), 5))
w.showNormal(); QTest.qWaitForWindowExposed(w); QTest.qWait(300)

vault.settings.setValue("minimise_on_copy", False)
QApplication.clipboard().clear()
v._on_double_click(password)
QTest.qWait(500)
ok("off: the password is copied", QApplication.clipboard().text() == entry["password"])
ok("off: Vault stays open", not w.isMinimized())
finish()
