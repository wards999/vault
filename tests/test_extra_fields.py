"""Extra fields and attachments (made in KeePass/KeePassXC): shown in the details panel, hidden values
masked until shown, copy buttons, attachments saved where chosen, found by search, kept by edits."""
import sys
import helpers  # repo path; temporary folder, settings and test databases
from helpers import ok, wait, finish
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QFileDialog, QLabel
from pykeepass import PyKeePass

path = helpers.copy_db("rt41.kdbx", "extra41.kdbx")
kp = PyKeePass(str(path), password=helpers.PW)
bank = kp.add_entry(kp.find_groups(name="Work", first=True), "Bank card", "me", "card-pw")
bank.set_custom_property("PIN", "4321", protect=True)
bank.set_custom_property("Branch", "High Street")
bank.set_custom_property("KPH: Allow", "example.com")  # browser-integration bookkeeping: not shown
bank.add_attachment(kp.add_binary(b"made-up statement", compressed=False), "statement.txt")
kp.save()

app = QApplication(sys.argv)
import vault, store

w = vault.MainWindow(); w.setMicaEffectEnabled(False); w.resize(1200, 760); w.show(); QTest.qWaitForWindowExposed(w)
db = store.Database(path, helpers.PW, "")
w.vault.load(db); w.saver.attach(db); w.locked = False
v, panel = w.vault, w.vault.notes
entry = lambda title: next(e for e in w.saver.db.entries if e["title"] == title)

e = entry("Bank card")
ok("snapshot: fields (not the browser one) and the attachment",
   e["fields"] == [("PIN", "4321", True), ("Branch", "High Street", False)] and e["attachments"] == [("statement.txt", 17)],
   (e["fields"], e["attachments"]))

v.refresh(select_uuid=e["uuid"]); QTest.qWait(200)
texts = lambda: [wd.text() for wd in panel.extra_box.findChildren(QLabel) if wd.isVisible()]
ok("panel shows the fields", panel.extra_box.isVisible() and "PIN" in texts() and "Branch" in texts() and "High Street" in texts(), texts())
ok("PIN is masked", "4321" not in texts() and "••••••••" in texts(), texts())
reveal = panel.extra_box.findChildren(vault.TransparentToggleToolButton)[0]
reveal.setChecked(True); QTest.qWait(50)
ok("…and shown on request", "4321" in texts(), texts())
saved_clipboard = QApplication.clipboard().text()
copies = [b for b in panel.extra_box.findChildren(vault.TransparentToolButton) if b.toolTip() == "Copy PIN"]
copies[0].click(); QTest.qWait(50)
ok("copy button copies the PIN", QApplication.clipboard().text() == "4321")
w._clear_clipboard(); QApplication.clipboard().setText(saved_clipboard)
buttons = [b for b in panel.extra_box.findChildren(vault.TransparentPushButton) if "statement.txt" in b.text()]
ok("attachment button with its size", buttons and "17 bytes" in buttons[0].text(), [b.text() for b in buttons])
target = helpers.WORK / "saved_statement.txt"
QFileDialog.getSaveFileName = staticmethod(lambda *a, **k: (str(target), ""))
buttons[0].click(); QTest.qWait(100)
ok("Save writes the attachment where chosen", target.read_bytes() == b"made-up statement")
w.grab().save(str(helpers.WORK / "extra_fields.png"))

v.refresh(select_uuid=entry("Netflix")["uuid"]); QTest.qWait(100)
ok("entries without extras: nothing shown", not panel.extra_box.isVisible())

v.search.setText("high street"); QTest.qWait(400)
ok("search finds a field's value", [x["title"] for x in v.model.entries] == ["Bank card"], [x["title"] for x in v.model.entries])
v.search.setText("4321"); QTest.qWait(400)
ok("…but not a hidden one", v.model.entries == [], [x["title"] for x in v.model.entries])
v.search.setText("statement"); QTest.qWait(400)
ok("…and attachment names", [x["title"] for x in v.model.entries] == ["Bank card"])
v.search.setText("")

# Editing the entry in Vault keeps the extras
e = entry("Bank card")
fields = dict(e["raw"], password="new-card-pw")
w.saver.submit(store.Op("update", e["uuid"], fields={"password": "new-card-pw"}, all_fields=fields, folder=e["folder_id"],
                        base_mtime=e["base_mtime"], title=e["title"]), "test")
ok("saved", wait(lambda: entry("Bank card")["password"] == "new-card-pw" and not w.saver.pending, 30))
again = PyKeePass(str(path), password=helpers.PW).find_entries(title="Bank card", first=True)
ok("edit kept the fields and attachment", again.custom_properties.get("PIN") == "4321" and
   again.custom_properties.get("KPH: Allow") == "example.com" and [a.filename for a in again.attachments] == ["statement.txt"],
   (again.custom_properties, again.attachments))
finish()
