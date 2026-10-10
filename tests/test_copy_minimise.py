"""Double-clicking a username or password copies it and minimises Vault, unless Settings →
"Minimise after double-click copy" is off: then Vault stays open."""
import sys
import helpers  # repo path; temporary folder, settings and test databases
from helpers import ok, wait, finish
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
password = v.model.index(row, vault.EntryModel.PASSWORD)
cell = v.model.index(row, vault.EntryModel.USERNAME)

ok("on by default; the tooltip says it minimises", "minimise" in v.model.data(cell, vault.R_TOOLTIP))
v._on_double_click(password)
ok("on: the password is copied", QApplication.clipboard().text() == entry["password"])
ok("on: Vault minimises", wait(lambda: w.isMinimized(), 5))
w.showNormal(); QTest.qWaitForWindowExposed(w); QTest.qWait(300)

vault.settings.setValue("minimise_on_copy", False)
QApplication.clipboard().clear()
ok("off: the tooltip just says copy", v.model.data(cell, vault.R_TOOLTIP) == "Double-click to copy")
v._on_double_click(password)
QTest.qWait(500)
ok("off: the password is copied", QApplication.clipboard().text() == entry["password"])
ok("off: Vault stays open", not w.isMinimized())
finish()
