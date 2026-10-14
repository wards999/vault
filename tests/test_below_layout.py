"""The details below the list: the button by Sort switches layouts (remembered, each with its own divider
position); below, the list shows columns that sort from their headings and give way when narrow, the
username and password copy with a double-click, the details are on tabs, and editing uses the pop-up."""
import sys
import helpers  # repo path; temporary folder, settings and test databases
from helpers import ok, wait, finish
from PySide6.QtCore import Qt, QTimer
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

app = QApplication(sys.argv)
import vault, store

M = vault.EntryModel
path = helpers.copy_db("dnd41.kdbx", "below41.kdbx")
vault.settings.setValue("icons_auto", False)


def open_window():
    w = vault.MainWindow(); w.setMicaEffectEnabled(False); w.resize(1500, 800); w.show(); QTest.qWaitForWindowExposed(w)
    db = store.Database(path, helpers.PW, "")
    w.vault.load(db); w.saver.attach(db); w.locked = False
    QTest.qWait(200)
    return w


w = open_window()
v = w.vault
header = v.table.horizontalHeader()
shown = lambda: [c for c in range(len(M.COLUMNS)) if not header.isSectionHidden(c)]

# Beside the list, as before: one column, no headings, the name and fields at the top of the details
ok("starts beside the list", not v.below and v.splitter.orientation() == Qt.Horizontal)
ok("beside: no headings, only the card's column", not header.isVisible() and shown() == [M.TITLE], shown())
ok("beside: the details' heading shows", v.notes.head_box.isVisible() and not v.notes.strip_bar.isVisible())
before = v.splitter.sizes()

# Below
v.layout_btn.click()
QTest.qWait(200)
ok("the button puts the details below", v.below and v.splitter.orientation() == Qt.Vertical)
ok("remembered", vault.settings.value("details_layout") == "below")
ok("below: headings show", header.isVisible())
ok("below: all the columns fit a wide window (All entries: the folder too)",
   shown() == [M.TITLE, M.USERNAME, M.PASSWORD, M.WEBSITE, M.FOLDER, M.MODIFIED, M.CREATED, M.ACTIONS], shown())
work = next(f["id"] for f in v.db.folders if f["name"] == "Work")
v.tree.setCurrentItem(next(v.tree.topLevelItem(i) for i in range(v.tree.topLevelItemCount())
                           if v.tree.topLevelItem(i).data(0, Qt.UserRole) == work))
QTest.qWait(200)
ok("in a folder: no folder column", v.folder == work and M.FOLDER not in shown() and M.CREATED in shown(), shown())
ok("below: tabs instead of the heading", v.notes.strip_bar.isVisible() and not v.notes.head_box.isVisible()
   and not v.notes.details_splitter.isVisible())
ok("below: the Notes tab shows first", v.notes.pages.currentWidget() is v.notes.notes_box)
ok("below: History and Edit sit by the tabs", v.notes.edit_btn.parent() is v.notes.strip_bar)

# All entries mixes folders: the folder column too, if there's room (it gives way first)
v.tree.setCurrentItem(v.tree.topLevelItem(0))
w.resize(1900, 800)
QTest.qWait(300)
ok("All entries: a folder column", M.FOLDER in shown(), shown())
ok("the folder column shows the entry's folder", v.model.data(v.model.index(0, M.FOLDER)) == v.model.entries[0]["folder"])

# Narrow: columns give way, created and the folder first
w.resize(900, 800)
QTest.qWait(300)
ok("narrow: fewer columns, the username stays",
   M.USERNAME in shown() and M.FOLDER not in shown() and M.CREATED not in shown(), shown())
w.resize(1500, 800)
QTest.qWait(300)

# Right-click a heading: choose columns
v._choose_column(M.WEBSITE, False)
ok("a column can be left out", M.WEBSITE not in shown() and vault.settings.value("list_columns"), shown())
v._choose_column(M.WEBSITE, True)
ok("and put back", M.WEBSITE in shown(), shown())

# Sorting from the headings
v._heading_clicked(M.USERNAME)
names = [e["username"].lower() for e in v.model.entries]
ok("username heading sorts by username", v.model.sort_column == M.USERNAME and names == sorted(names), names)
ok("…and is remembered, like the Sort menu", vault.settings.value("list_sort") == f"{M.USERNAME},0")
v._heading_clicked(M.USERNAME)
ok("clicked again: the other way round", v.model.sort_order == Qt.DescendingOrder)
v._heading_clicked(M.PASSWORD)
ok("the password heading doesn't sort", v.model.sort_column == M.USERNAME)
v._heading_clicked(M.MODIFIED)
ok("dates start newest first", v.model.sort_column == M.MODIFIED and v.model.sort_order == Qt.DescendingOrder)
v._heading_clicked(M.TITLE)

# Double-clicking the username or password copies it (checked with a short wait: another program
# reading the clipboard, e.g. Windows' clipboard history, can hold it for a moment)
row = next(i for i, e in enumerate(v.model.entries) if e["username"] and e["password"])
e = v.model.entries[row]
vault.settings.setValue("minimise_on_copy", False)
QApplication.clipboard().clear()
v._on_double_click(v.model.index(row, M.USERNAME))
ok("double-click a username: copied", wait(lambda: QApplication.clipboard().text() == e["username"], 3))
ok("…with a tick in the cell", v.delegate.done == (e["uuid"], "username"))
v._on_double_click(v.model.index(row, M.PASSWORD))
ok("double-click a password: copied", wait(lambda: QApplication.clipboard().text() == e["password"], 3))
ok("minimise off: Vault stays open", not w.isMinimized())
vault.settings.setValue("minimise_on_copy", True)
QApplication.clipboard().clear()
v._on_double_click(v.model.index(row, M.USERNAME))
ok("minimise on: the username is copied", wait(lambda: QApplication.clipboard().text() == e["username"], 3))
ok("minimise on: Vault minimises", wait(lambda: w.isMinimized(), 5))
w.showNormal(); QTest.qWaitForWindowExposed(w); QTest.qWait(300)
v._on_double_click(v.model.index(row, M.TITLE))
ok("double-click the name: the password, as beside the list", wait(lambda: QApplication.clipboard().text() == e["password"], 3))
w.showNormal(); QTest.qWaitForWindowExposed(w); QTest.qWait(300)
vault.settings.setValue("minimise_on_copy", False)

# The password column: dots, unless shown
v.table.selectRow(row)
ok("password column: dots", v.model.data(v.model.index(row, M.PASSWORD)) == vault.MASK)
v.toggle_password()
ok("Show password: in the column too", v.model.data(v.model.index(row, M.PASSWORD)) == e["password"]
   and v.notes.revealed)
v.toggle_password()
ok("and hidden again", v.model.data(v.model.index(row, M.PASSWORD)) == vault.MASK and not v.notes.revealed)

# The copy buttons have the last column
rect = v.delegate.row_rect(v.table.visualRect(v.model.index(row, M.TITLE)))
actions = v.delegate.actions(e, rect)
last = v.table.visualRect(v.model.index(row, M.ACTIONS))
ok("the buttons sit in the last column", actions and all(last.contains(r) for *_x, r in actions),
   (last, [r for *_x, r in actions]))
hit = v._button_at(actions[0][3].center())
ok("…and are found there", hit is not None and hit[1] == actions[0][0], hit)

# Tabs
v.notes.tabs.setCurrentItem("details")
ok("Details tab: the fields", v.notes.pages.currentWidget() is v.notes.details_scroll
   and v.notes.card.isVisibleTo(v.notes))
ok("the tab is remembered", vault.settings.value("details_tab") == "details")
v.notes.tabs.setCurrentItem("activity")
ok("Activity tab", v.notes.pages.currentWidget() is v.notes.activity_box)
v.notes.tabs.setCurrentItem("notes")

# Editing: the pop-up
def add():
    dlg = next((d for d in w.findChildren(vault.EntryEditor) if d.isVisible()), None)
    if dlg is None:
        QTimer.singleShot(50, add); return
    dlg.title.setText("Added below")
    dlg.username.setText("below-user")
    QTest.qWait(50)
    dlg.yesButton.click()
QTimer.singleShot(80, add)
v.new_entry()
ok("New entry below: the pop-up adds it", wait(lambda: any(x["title"] == "Added below" for x in w.saver.db.entries)))
ok("…and no pane editor", v.editor is None)
ok("…and it's selected", wait(lambda: (v.current_entry() or {}).get("title") == "Added below"))

def edit():
    dlg = next((d for d in w.findChildren(vault.EntryEditor) if d.isVisible()), None)
    if dlg is None:
        QTimer.singleShot(50, edit); return
    ok("editing: the entry's values", dlg.username.text() == "below-user")
    dlg.username.setText("below-user-2")
    QTest.keyClick(dlg.username, Qt.Key_S, Qt.ControlModifier)  # Ctrl+S saves
QTimer.singleShot(80, edit)
v.edit_entry()
ok("Edit below: Ctrl+S saves the change",
   wait(lambda: any(x["username"] == "below-user-2" for x in w.saver.db.entries)))

def add_note():
    dlg = next((d for d in w.findChildren(vault.EntryEditor) if d.isVisible()), None)
    if dlg is None:
        QTimer.singleShot(50, add_note); return
    ok("New note: the pop-up says so", dlg.note and dlg.yesButton.text() == "Add note")
    dlg.cancelButton.click()
QTimer.singleShot(80, add_note)
v._open_editor(note=True)

# Pictures, to look at (both layouts)
QTest.qWait(300)
v.grab().save(str(helpers.WORK / "below-layout.png"))

# Each layout keeps its own divider position
v.splitter.setSizes([400, 340])
v.splitter.splitterMoved.emit(400, 1)
below_sizes = v.splitter.sizes()
v.layout_btn.click()
QTest.qWait(200)
ok("back beside the list", not v.below and v.splitter.orientation() == Qt.Horizontal
   and vault.settings.value("details_layout") == "right")
ok("beside: its own divider position again", abs(v.splitter.sizes()[0] - before[0]) <= 2, (before, v.splitter.sizes()))
ok("beside: one column, no headings", not header.isVisible() and shown() == [M.TITLE], shown())
ok("beside: the notes and activity back under the fields",
   v.notes.notes_box.parent() is v.notes.details_splitter and v.notes.head_box.isVisible()
   and v.notes.details_splitter.isVisible() and v.notes.notes_box.isVisible() and v.notes.activity_box.isVisible())
ok("beside: History and Edit back in the heading", v.notes.edit_btn.parent() is v.notes.head_box)
v.grab().save(str(helpers.WORK / "beside-layout.png"))
v.layout_btn.click()
QTest.qWait(200)
ok("below again: its divider position", abs(v.splitter.sizes()[0] - below_sizes[0]) <= 2,
   (below_sizes, v.splitter.sizes()))

# Editing beside the list, then switching: asks about unsaved changes first (here: no title, can't save)
v.layout_btn.click()
QTest.qWait(200)
v.new_entry()
ok("beside: New entry opens in the pane", v.editor is not None)
v.editor.username.setText("typed")
QTimer.singleShot(150, lambda: next(d for d in w.findChildren(vault.MessageBox) if d.isVisible()).yesButton.click())
ok("switching with an unsaveable edit: stays", v.set_details_below(True) is False and not v.below
   and v.editor is not None)
v.editor.cancelled.emit()
v.layout_btn.click()
QTest.qWait(200)

# Locking closes the pop-up editor, unsaved (as it does the pane), before asking for the password
vault.settings.setValue("last_file", str(path))
vault.settings.setValue("last_keyfile", "")
seen = {}

def lock_mid_edit():
    dlg = next((d for d in w.findChildren(vault.EntryEditor) if d.isVisible()), None)
    if dlg is None:
        QTimer.singleShot(50, lock_mid_edit); return
    dlg.title.setText("Typed then locked")
    QTimer.singleShot(0, w.lock)
    QTimer.singleShot(100, at_unlock)

def at_unlock():
    unlock = next((d for d in w.findChildren(vault.UnlockDialog) if d.isVisible()), None)
    if unlock is None:
        QTimer.singleShot(50, at_unlock); return
    seen["editor"] = any(d.isVisible() for d in w.findChildren(vault.EntryEditor))
    seen["locked"] = w.locked and w.vault.db is None
    unlock.pw.setText(helpers.PW)
    unlock.yesButton.click()
QTimer.singleShot(80, lock_mid_edit)
v.edit_entry()
ok("locked: the pop-up editor was gone before the password was asked for",
   seen.get("locked") and seen.get("editor") is False, seen)
ok("…without saving", wait(lambda: not w.locked) and not any(x["title"] == "Typed then locked"
                                                              for x in w.saver.db.entries))

# Remembered next time
w.close()
w = open_window()
ok("next time: below again", w.vault.below and w.vault.table.horizontalHeader().isVisible())
print(f"pictures: {helpers.WORK / 'below-layout.png'}, {helpers.WORK / 'beside-layout.png'}")
finish()
