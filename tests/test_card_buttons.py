"""Hovering over an entry in the list shows buttons on its card to copy the username, the password and
(if it has one) the 2FA code. A click copies straight away, shows a tick, and doesn't select the entry
or start dragging it. In-app Qt events only (no OS input)."""
import sys
import helpers  # repo path; temporary folder, settings and test databases
from helpers import ok, wait, finish
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

app = QApplication(sys.argv)
import vault, store, totp

path = helpers.copy_db("dnd41.kdbx", "cardbuttons41.kdbx")
w = vault.MainWindow(); w.setMicaEffectEnabled(False); w.resize(1200, 700); w.show(); QTest.qWaitForWindowExposed(w)
db = store.Database(path, helpers.PW, "")
w.vault.load(db); w.saver.attach(db); w.locked = False
v = w.vault
viewport = v.table.viewport()
v.table.selectRow(0); QTest.qWait(200)
row = next(i for i, e in enumerate(v.model.entries) if e["totp"])  # GitHub: username, password and 2FA
e = v.model.entries[row]
ok("set-up: another entry is selected", row != 0)


def buttons():
    return {field: rect for field, _i, _t, rect in v.delegate.actions(e, v.table.visualRect(v.model.index(row, 0)))}


ok("an entry with a username, password and 2FA code has three buttons",
   list(buttons()) == ["username", "password", "totp"], list(buttons()))
QTest.mouseMove(viewport, buttons()["username"].center()); QTest.qWait(150)
ok("hovering: the card shows them", v.delegate.hoverRow == row, v.delegate.hoverRow)

QApplication.clipboard().clear()
QTest.mouseClick(viewport, Qt.LeftButton, Qt.NoModifier, buttons()["username"].center()); QTest.qWait(150)
ok("username button: username copied", QApplication.clipboard().text() == e["username"])
ok("…its button shows a tick", v.delegate.done == (e["uuid"], "username"))
ok("…and the selected entry didn't change", v.table.currentIndex().row() == 0, v.table.currentIndex().row())
ok("…the tick goes after a moment", wait(lambda: v.delegate.done is None, 3))

QTest.mouseClick(viewport, Qt.LeftButton, Qt.NoModifier, buttons()["password"].center()); QTest.qWait(150)
ok("password button: password copied", QApplication.clipboard().text() == e["password"])
QTest.mouseClick(viewport, Qt.LeftButton, Qt.NoModifier, buttons()["totp"].center()); QTest.qWait(150)
ok("2FA button: the current code copied", QApplication.clipboard().text() == totp.code(e["totp"])[0])
ok("Vault stayed open (only double-click minimises)", not w.isMinimized())

QTest.mouseClick(viewport, Qt.LeftButton, Qt.NoModifier, v.table.visualRect(v.model.index(row, 0)).center())
QTest.qWait(150)
ok("clicking the card itself still selects it", v.table.currentIndex().row() == row)
no_user = next((x for x in v.model.entries if not x["username"]), None)
if no_user:
    ok("no username: no username button", "username" not in [a[0] for a in v.delegate.actions(no_user, buttons()["username"])])
QApplication.clipboard().clear()
finish()
