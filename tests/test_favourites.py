"""Favourites: the star in the details pane (or dropping entries on Favourites in the sidebar) adds
KeePass's tag "Favourite", keeping the entry's other tags; the Favourites row lists starred entries;
Undo unstars; the tag is saved to the file, so KeePassXC shows it too."""
import sys
import helpers  # repo path; temporary folder, settings and test databases
from helpers import ok, wait, finish
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from pykeepass import PyKeePass

app = QApplication(sys.argv)
import vault, store

path = helpers.copy_db("dnd41.kdbx", "fav41.kdbx")
kp = PyKeePass(str(path), password=helpers.PW)
github = kp.find_entries(title="GitHub", first=True)
github.tags = ["work"]  # an existing tag, which starring must keep
kp.save()

w = vault.MainWindow(); w.setMicaEffectEnabled(False); w.show(); QTest.qWaitForWindowExposed(w)
db = store.Database(path, helpers.PW, "")
w.vault.load(db); w.saver.attach(db); w.health.set_db(db); w.locked = False
v = w.vault
entry = lambda title: next(e for e in w.saver.db.entries if e["title"] == title)
fav_row = lambda: next(v.tree.topLevelItem(i) for i in range(v.tree.topLevelItemCount())
                       if v.tree.topLevelItem(i).data(0, Qt.UserRole) == vault.FAVOURITES)

ok("store: tags read, not a favourite yet", entry("GitHub")["tags"] == ["work"] and not entry("GitHub")["favourite"])
ok("sidebar: Favourites row, with 0", vault.FolderRowDelegate.split(fav_row().text(0)) == ("Favourites", "0"))

v.refresh(select_uuid=entry("GitHub")["uuid"])
ok("details: an empty star", v.notes.fav_btn.toolTip() == "Add to Favourites")
v.notes.fav_btn.click()
ok("star clicked: a favourite", wait(lambda: entry("GitHub")["favourite"], 5))
ok("…its other tag kept", entry("GitHub")["tags"] == ["work", "Favourite"], entry("GitHub")["tags"])
ok("…the star filled", v.notes.fav_btn.toolTip() == "Remove from Favourites")
ok("…Favourites counts 1", vault.FolderRowDelegate.split(fav_row().text(0))[1] == "1")

v.tree.setCurrentItem(fav_row())
ok("Favourites row: only starred entries listed", [e["title"] for e in v.model.entries] == ["GitHub"])
ok("…titled Favourites", v.list_title.text() == "Favourites")

v.undo()
ok("Undo: not a favourite again, other tag kept",
   wait(lambda: not entry("GitHub")["favourite"], 5) and entry("GitHub")["tags"] == ["work"], entry("GitHub")["tags"])
ok("…gone from the Favourites list", wait(lambda: v.model.rowCount() == 0, 5))

others = [e for e in w.saver.db.entries if not e["in_bin"]][:2]
v._on_entries_dropped([e["uuid"] for e in others], vault.FAVOURITES)
ok("dropped on Favourites: both starred", wait(lambda: all(entry(e["title"])["favourite"] for e in others), 5))
ok("…and still in their folders", all(entry(e["title"])["folder_id"] == e["folder_id"] for e in others))

ok("saved", wait(lambda: not w.saver.pending, 15))
reopened = PyKeePass(str(path), password=helpers.PW)
ok("in the file: the Favourite tag (as KeePassXC reads it)",
   all("Favourite" in (reopened.find_entries(title=e["title"], first=True).tags or []) for e in others))
finish()
