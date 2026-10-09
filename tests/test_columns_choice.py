"""Choosing columns (right-click a heading) and the Created column. Temporary settings, test database."""
import os, shutil, sys
from pathlib import Path
import helpers  # repo path; temporary folder, settings and test databases
from PySide6.QtCore import QSettings, Qt
from PySide6.QtGui import QStandardItemModel
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QHeaderView, QTableView

s = helpers.WORK
fails = []


def ok(label, cond, extra=""):
    print(("OK   " if cond else "FAIL ") + label + ("" if cond else f"  [{extra}]"), flush=True)
    if not cond:
        fails.append(label)


app = QApplication(sys.argv)
import vault, store
from PySide6.QtCore import QProcess
QProcess.startDetached = staticmethod(lambda *a, **k: (_ for _ in ()).throw(RuntimeError("no processes from tests")))
E = vault.EntryModel
ini = s / "colchoice.ini"; ini.unlink(missing_ok=True)
vault.settings = QSettings(str(ini), QSettings.IniFormat)

# A layout saved by the previous version: 6 columns, Title widened to 333.
old_model = QStandardItemModel(0, 6)
old = QTableView(); old.setModel(old_model); old.horizontalHeader().resizeSection(0, 333)
vault.settings.setValue("table_header", old.horizontalHeader().saveState())

shutil.copy(s / "rt41.kdbx", s / "colchoice41.kdbx")
w = vault.MainWindow(); w.setMicaEffectEnabled(False); w.resize(1300, 720); w.show(); QTest.qWaitForWindowExposed(w)
db = store.Database(s / "colchoice41.kdbx", "test-pw-123", ""); w.vault.load(db); w.locked = False; QTest.qWait(300)
v = w.vault
h = v.table.horizontalHeader()
ok("old 6-column layout still applied (Title width kept)", h.sectionSize(E.TITLE) == 333, h.sectionSize(E.TITLE))
ok("Created column exists but starts hidden", E.COLUMNS[E.CREATED] == "Created" and h.isSectionHidden(E.CREATED))
ok("other columns shown", not any(h.isSectionHidden(c) for c in range(E.CREATED)))
row0 = v.model.entries[0]
ok("Created holds a real date", bool(row0["created"]) and row0["created_key"], row0.get("created"))

# The menu lists the columns (not Title), ticked when shown
menu_items = []
orig_exec = vault.RoundMenu.exec
vault.RoundMenu.exec = lambda self, *a, **k: menu_items.extend((act.text(), act.isChecked()) for act in self.actions())
v._columns_menu(h.rect().center())
vault.RoundMenu.exec = orig_exec
ok("heading menu: every column except Title, Created unticked",
   [n for n, _ in menu_items] == E.COLUMNS[1:] and dict(menu_items)["Created"] is False and dict(menu_items)["Folder"] is True, menu_items)

v.set_column_visible("Folder", False); v.set_column_visible("Created", True); QTest.qWait(100)
ok("hide Folder / show Created: applied at once", h.isSectionHidden(E.FOLDER) and not h.isSectionHidden(E.CREATED))
ok("…and remembered", sorted(v._hidden_columns()) == ["Folder"], v._hidden_columns())
v.table.sortByColumn(E.CREATED, Qt.DescendingOrder); QTest.qWait(100)
keys = [e["created_key"] for e in v.model.entries]
ok("sorting by Created works", keys == sorted(keys, reverse=True), keys)
v.set_column_visible("Folder", True); v.set_column_visible("Created", True)
ok("all shown: setting is empty (not the default)", v._hidden_columns() == [] and not any(h.isSectionHidden(c) for c in range(len(E.COLUMNS))))
w.grab().save(str(s / "columns_choice.png"))
print(f"--- {'ALL PASSED' if not fails else str(len(fails)) + ' FAILED'}", flush=True)
sys.stdout.flush(); os._exit(1 if fails else 0)
