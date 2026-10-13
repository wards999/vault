"""Vault's own edits are never "Changed in two places": starring an entry while editing it, notes saved from
the details pane after the editor opened, and several edits to one entry re-applied on top of a file that
changed on disk (e.g. Google Drive rewriting it). Nothing is lost in any of them. An entry really changed
elsewhere still asks."""
import sys
import helpers  # repo path; temporary folder, settings and test databases
from helpers import ok, wait, finish
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from pykeepass import PyKeePass

app = QApplication(sys.argv)
import vault, store

w = vault.MainWindow(); w.setMicaEffectEnabled(False); w.show(); QTest.qWaitForWindowExposed(w)
asked = []
w.saver._resolve = lambda conflict: (asked.append(conflict.op.title), [conflict.op])[1]  # "keep mine", noted
v = w.vault


def open_copy(name):
    path = helpers.copy_db("dnd41.kdbx", name)
    db = store.Database(path, helpers.PW, "")
    v.clear(); v.load(db); w.saver.attach(db); w.locked = False
    asked.clear()
    return path


def entry():
    return next(e for e in w.saver.db.entries if e["title"] == "GitHub")


def edit(e, **fields):
    return store.Op("update", e["uuid"], fields=fields, all_fields={**e["raw"], **fields},
                    base_mtime=e["base_mtime"], base_version=store.base_version(e), title=e["title"])


# Starred (the card's star) while being edited
open_copy("own1.kdbx")
v.refresh(select_uuid=entry()["uuid"]); v.edit_entry()
v.toggle_favourite(entry()); wait(lambda: entry()["favourite"], 5)
v.editor.username.setText("starred-while-editing"); v.editor.save(); QTest.qWait(300)
ok("starred while editing: no question", not asked, asked)
ok("…the edit and the star both kept", entry()["username"] == "starred-while-editing" and entry()["favourite"])
ok("…saved", wait(lambda: not w.saver.pending, 10))

# Notes typed in the details pane, then Edit before they were saved
open_copy("own2.kdbx")
v.refresh(select_uuid=entry()["uuid"]); QTest.qWait(200)
v.notes.notes.setPlainText("typed in the details pane"); v.edit_entry(); QTest.qWait(1200)
v.editor.username.setText("edited-after-notes"); v.editor.save(); QTest.qWait(300)
ok("notes saved after the editor opened: no question", not asked, asked)
ok("…the notes and the edit both kept",
   entry()["notes"] == "typed in the details pane" and entry()["username"] == "edited-after-notes")
ok("…saved", wait(lambda: not w.saver.pending, 10))

# Several edits to one entry, then the file changes on disk before Vault saves: re-applied on top
path = open_copy("own3.kdbx")
w.saver.save_timer.setInterval(60_000)
for name in ("first-edit", "second-edit", "third-edit"):
    w.saver.submit(edit(entry(), username=name))
other = PyKeePass(str(path), password=helpers.PW)
other.add_entry(other.root_group, "From phone", "p", "x")
other.save()
w.saver.save_now(); ok("merged and saved", wait(lambda: not w.saver.pending, 10))
ok("three edits of one entry, merged: no question", not asked, asked)
ok("…the last edit kept, and the other device's entry too",
   entry()["username"] == "third-edit" and any(e["title"] == "From phone" for e in w.saver.db.entries))

# The same entry really changed on the other device: still asks
path = open_copy("own4.kdbx")
w.saver.save_timer.setInterval(60_000)
w.saver.submit(edit(entry(), username="mine"))
w.saver.submit(edit(entry(), username="mine again"))
other = PyKeePass(str(path), password=helpers.PW)
theirs = other.find_entries(title="GitHub", first=True)
theirs.username = "theirs"; theirs.touch(modify=True)
other.save()
w.saver.save_now(); wait(lambda: not w.saver.pending, 10)
ok("changed on another device too: asked, once", asked == ["GitHub"], asked)
ok("…keeping mine: my last edit", entry()["username"] == "mine again", entry()["username"])
finish()
