"""Secure notes: the sidebar's Notes row lists entries tagged "Note"; there, New note opens a form with just
the title, folder and notes (no generated password), and the note is saved with KeePass's Note tag and
notepad icon, so KeePassXC shows it too. Notes aren't flagged "No password" by Password health, and
entries dropped on Notes aren't turned into notes."""
import sys
import helpers  # repo path; temporary folder, settings and test databases
from helpers import ok, wait, finish
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from pykeepass import PyKeePass

app = QApplication(sys.argv)
import vault, store, health

path = helpers.copy_db("dnd41.kdbx", "notes41.kdbx")
w = vault.MainWindow(); w.setMicaEffectEnabled(False); w.show(); QTest.qWaitForWindowExposed(w)
db = store.Database(path, helpers.PW, "")
w.vault.load(db); w.saver.attach(db); w.health.set_db(db); w.locked = False
v = w.vault
entry = lambda title: next(e for e in w.saver.db.entries if e["title"] == title)
notes_row = lambda: next(v.tree.topLevelItem(i) for i in range(v.tree.topLevelItemCount())
                         if v.tree.topLevelItem(i).data(0, Qt.UserRole) == vault.NOTES)

ok("sidebar: Notes row, with 0", vault.FolderRowDelegate.split(notes_row().text(0)) == ("Notes", "0"))
ok("…New entry button outside Notes", v.new_btn.text() == "New entry")
v.tree.setCurrentItem(notes_row())
ok("in Notes: the button says New note", v.new_btn.text() == "New note", v.new_btn.text())
ok("…titled Notes, listing nothing", v.list_title.text() == "Notes" and v.model.rowCount() == 0)

v.new_entry()
pane = v.editor
ok("New note: the note form", pane is not None and pane.note and pane.heading.text() == "New note")
ok("…login fields hidden", not pane.login_box.isVisibleTo(pane))
ok("…no password generated", pane.password.text() == "")
ok("…Add note button", pane.yesButton.text() == "Add note")
pane.title.setText("Wi-Fi")
pane.notes.setPlainText("Network: Home\nKey: hunter2")
pane.save()
ok("saved: a note", wait(lambda: any(e["title"] == "Wi-Fi" for e in w.saver.db.entries), 5)
   and entry("Wi-Fi")["note"])
note = entry("Wi-Fi")
ok("…with its text and no password", note["notes"] == "Network: Home\nKey: hunter2" and note["password"] == "")
ok("…the notepad icon", note["icon"][0] == store.NOTE_ICON, note["icon"])
ok("…listed under Notes", wait(lambda: [e["title"] for e in v.model.entries] == ["Wi-Fi"], 5))
ok("…Notes counts 1", vault.FolderRowDelegate.split(notes_row().text(0))[1] == "1")
ok("…and in All entries", vault.in_folder(note, None))

issues = health.report(w.saver.db.entries, strength=False)
ok("Password health: the note isn't flagged", not any(i["entry"]["uuid"] == note["uuid"] for i in issues))

v.edit_entry()
ok("editing it: the note form again", v.editor.note and v.editor.heading.text() == "Edit note"
   and not v.editor.login_box.isVisibleTo(v.editor))
v.editor.cancelled.emit()

login = next(e for e in w.saver.db.entries if not e["in_bin"] and not e["note"])
v._on_entries_dropped([login["uuid"]], vault.NOTES)  # not offered by the tree; harmless if it happens
ok("dropped on Notes: a login stays a login, in its folder",
   not entry(login["title"])["note"] and entry(login["title"])["folder_id"] == login["folder_id"])

v.tree.setCurrentItem(v.tree.topLevelItem(0))
ok("All entries: New entry again", v.new_btn.text() == "New entry")
v.new_entry()
ok("…and the full form, with a generated password",
   not v.editor.note and v.editor.login_box.isVisibleTo(v.editor) and v.editor.password.text())
v.editor.cancelled.emit()

ok("saved", wait(lambda: not w.saver.pending, 15))
reopened = PyKeePass(str(path), password=helpers.PW)
saved = reopened.find_entries(title="Wi-Fi", first=True)
ok("in the file: the Note tag and notepad icon (as KeePassXC reads them)",
   saved.tags == ["Note"] and int(saved.icon) == store.NOTE_ICON, (saved.tags, saved.icon))
finish()
