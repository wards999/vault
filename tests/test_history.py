"""Entry history: earlier versions listed newest first, old password copied, a version restored (and undone)."""
import sys
import helpers  # repo path; temporary folder, settings and test databases
from helpers import ok, wait, finish
from PySide6.QtCore import QTimer, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

app = QApplication(sys.argv)
import vault, store

path = helpers.copy_db("rt41.kdbx", "history41.kdbx")
w = vault.MainWindow(); w.setMicaEffectEnabled(False); w.resize(1200, 720); w.show(); QTest.qWaitForWindowExposed(w)
db = store.Database(path, helpers.PW, "")
w.vault.load(db); w.saver.attach(db); w.locked = False
v = w.vault
entry = lambda title: next(e for e in w.saver.db.entries if e["title"] == title)

versions = db.history(entry("GitHub")["uuid"])
ok("GitHub has 4 earlier versions, newest first",
   [x["password"] for x in versions] == ["edited-by-pykeepass!", "edited-by-pykeepass!", "orig-pw", "orig-pw"],
   [x["password"] for x in versions])
ok("each has a time", all(x["modified"] for x in versions))


def in_dialog(action):
    def step():
        d = next((d for d in w.findChildren(vault.HistoryDialog) if d.isVisible()), None)
        if d is None:
            QTimer.singleShot(50, step); return
        QTest.qWait(150)
        action(d)
    QTimer.singleShot(80, step)


seen = {}
def look(d):
    seen["rows"] = d.table.rowCount()
    seen["masked"] = d.table.item(0, d.PASSWORD).text()
    d.reveal.setChecked(True); QTest.qWait(50)
    seen["shown"] = d.table.item(2, d.PASSWORD).text()
    seen["changed"] = d.table.item(0, d.CHANGED).text()
    d.table.selectRow(2); QTest.qWait(50)
    d.copy.click(); QTest.qWait(50)
    seen["clipboard"] = QApplication.clipboard().text()
    w.grab().save(str(helpers.WORK / "history.png"))
    d.cancelButton.click()

v.refresh(select_uuid=entry("GitHub")["uuid"])
saved_clipboard = QApplication.clipboard().text()
in_dialog(look)
v.show_history()
ok("dialog lists 4 versions", seen.get("rows") == 4, seen)
ok("passwords hidden until Show passwords", seen.get("masked", "").startswith("•") and seen.get("shown") == "orig-pw", seen)
ok("'Changed' says what differs from the newer version", seen.get("changed") == "Password", seen.get("changed"))
ok("Copy password copies the old one", seen.get("clipboard") == "orig-pw", seen.get("clipboard"))
w._clear_clipboard(); QApplication.clipboard().setText(saved_clipboard)

# Restore the oldest version
def restore(d):
    d.table.selectRow(3); QTest.qWait(50)
    d.yesButton.click()
in_dialog(restore)
v.show_history()
ok("restored: password is the old one", wait(lambda: entry("GitHub")["password"] == "orig-pw"), entry("GitHub")["password"])
ok("…and saved", wait(lambda: not w.saver.pending, 30))
after = store.Database(path, helpers.PW, "").history(entry("GitHub")["uuid"])
ok("the replaced version is now in history", after and after[0]["password"] == "edited-in-4.1-by-pykeepass", after and after[0]["password"])
v.undo()
ok("undo brings the newer password back", wait(lambda: entry("GitHub")["password"] == "edited-in-4.1-by-pykeepass"))

# An entry with no history (Wikipedia-like: create one)
nohist = {}
def look_empty(d):
    nohist["table"] = d.table.isVisible(); nohist["restore"] = d.yesButton.isVisible(); d.cancelButton.click()
import uuid as uuidlib
fresh = dict(title="Brand new", username="me", password="pw-1", url="", notes="", otp="")
w.saver.submit(store.Op("create", uuidlib.uuid4().hex, fields=fresh, all_fields=fresh, folder=None, title="Brand new"), "test")
wait(lambda: any(e["title"] == "Brand new" for e in w.saver.db.entries))
v.refresh(select_uuid=entry("Brand new")["uuid"])
ok("new entry selected", v.current_entry()["title"] == "Brand new")
in_dialog(look_empty)
v.show_history()
ok("no history: a message, no table, no Restore", nohist == {"table": False, "restore": False}, nohist)
finish()
