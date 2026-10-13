"""Hovering over an entry in the list shows buttons on its card to copy the username, the password and
(if it has one) the 2FA code, then a star. A click copies straight away, shows a tick, and doesn't select
the entry or start dragging it; the star stars or unstars that entry. In-app Qt events only (no OS input)."""
import sys
import helpers  # repo path; temporary folder, settings and test databases
from helpers import ok, wait, finish
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

app = QApplication(sys.argv)
import vault, store, totp

path = helpers.copy_db("dnd41.kdbx", "cardbuttons41.kdbx")
vault.settings.setValue("minimise_on_copy", False)  # Settings → Minimise after copying: off, so Vault stays
w = vault.MainWindow(); w.setMicaEffectEnabled(False); w.resize(1200, 700); w.show(); QTest.qWaitForWindowExposed(w)
db = store.Database(path, helpers.PW, "")
w.vault.load(db); w.saver.attach(db); w.locked = False
v = w.vault
viewport = v.table.viewport()
row = next(i for i, e in enumerate(v.model.entries) if e["totp"])  # GitHub: username, password and 2FA
other = 1 if row == 0 else 0
v.table.selectRow(other); QTest.qWait(200)
uuid = v.model.entries[row]["uuid"]
e = v.model.entries[row]
ok("set-up: another entry is selected", v.table.currentIndex().row() == other)


def buttons():
    return {field: rect for field, _i, _t, rect in v.delegate.actions(e, v.table.visualRect(v.model.index(row, 0)))}


ok("an entry with a username, password and 2FA code has three copy buttons, then the star",
   list(buttons()) == ["username", "password", "totp", "favourite"], list(buttons()))
QTest.mouseMove(viewport, buttons()["username"].center()); QTest.qWait(150)
ok("hovering: the card shows them", v.delegate.hoverRow == row, v.delegate.hoverRow)

QApplication.clipboard().clear()
QTest.mouseClick(viewport, Qt.LeftButton, Qt.NoModifier, buttons()["username"].center()); QTest.qWait(150)
ok("username button: username copied", QApplication.clipboard().text() == e["username"])
ok("…its button shows a tick", v.delegate.done == (e["uuid"], "username"))
ok("…and the selected entry didn't change", v.table.currentIndex().row() == other, v.table.currentIndex().row())
ok("…the tick goes after a moment", wait(lambda: v.delegate.done is None, 3))

QTest.mouseClick(viewport, Qt.LeftButton, Qt.NoModifier, buttons()["password"].center()); QTest.qWait(150)
ok("password button: password copied", QApplication.clipboard().text() == e["password"])
QTest.mouseClick(viewport, Qt.LeftButton, Qt.NoModifier, buttons()["totp"].center()); QTest.qWait(150)
ok("2FA button: the current code copied", QApplication.clipboard().text() == totp.code(e["totp"])[0])
ok("Vault stayed open (Minimise after copying is off)", not w.isMinimized())

entry = lambda: next(x for x in w.saver.db.entries if x["uuid"] == uuid)
ok("the star's tooltip: Add to Favourites", v._button_at(buttons()["favourite"].center())[2] == "Add to Favourites")
QTest.mouseClick(viewport, Qt.LeftButton, Qt.NoModifier, buttons()["favourite"].center())
ok("star clicked: a favourite", wait(lambda: entry()["favourite"], 5))
ok("…the selected entry didn't change", wait(lambda: v.table.currentIndex().row() == other, 3),
   v.table.currentIndex().row())
row = next(i for i, x in enumerate(v.model.entries) if x["uuid"] == uuid)  # (the list reloaded)
e = v.model.entries[row]
ok("…its tooltip now: Remove from Favourites",
   v._button_at(buttons()["favourite"].center())[2] == "Remove from Favourites")
QTest.mouseClick(viewport, Qt.LeftButton, Qt.NoModifier, buttons()["favourite"].center())
ok("clicked again: unstarred", wait(lambda: not entry()["favourite"], 5))
ok("…the list shows it", wait(lambda: any(x["uuid"] == uuid and not x["favourite"] for x in v.model.entries), 5))
ok("…saved", wait(lambda: not w.saver.pending, 15))
QTest.qWait(QApplication.styleHints().mouseDoubleClickInterval() + 100)  # the next click isn't a double-click
row = next(i for i, x in enumerate(v.model.entries) if x["uuid"] == uuid)
e = v.model.entries[row]

QTest.mouseClick(viewport, Qt.LeftButton, Qt.NoModifier, v.table.visualRect(v.model.index(row, 0)).center())
QTest.qWait(150)
ok("clicking the card itself still selects it", v.table.currentIndex().row() == row,
   (v.table.currentIndex().row(), row))
no_user = next((x for x in v.model.entries if not x["username"]), None)
if no_user:
    ok("no username: no username button", "username" not in [a[0] for a in v.delegate.actions(no_user, buttons()["username"])])
QApplication.clipboard().clear()
finish()
