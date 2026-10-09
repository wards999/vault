"""Folder panel fits its widest folder name: short names, a long nested name, bigger text, the 40%
limit, collapsing. Every folder name must be fully visible (not cut off) and the panel not much wider."""
import os, shutil, sys
from pathlib import Path
import helpers  # repo path; temporary folder, settings and test databases
from PySide6.QtCore import QSettings
from PySide6.QtGui import QFontMetrics
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from pykeepass import PyKeePass

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
vault.settings = QSettings(str(s / "fit.ini"), QSettings.IniFormat)
w = vault.MainWindow(); w.setMicaEffectEnabled(False); w.resize(1300, 760); w.show(); QTest.qWaitForWindowExposed(w)
v = w.vault


def open_db(extra):
    path = s / "fit41.kdbx"
    shutil.copy(s / "foldericons41.kdbx", path)
    kp = PyKeePass(str(path), password="test-pw-123")
    parent = kp.root_group
    for name in extra:
        parent = kp.add_group(parent, name)
    kp.save()
    db = store.Database(path, "test-pw-123", "")
    v.load(db); w.locked = False
    QTest.qWait(400)


def all_names_fit():
    """Every visible folder row's text ends inside the tree's viewport."""
    worst = 0
    it = vault.QTreeWidgetItemIterator(v.tree)
    while it.value():
        item = it.value()
        rect = v.tree.visualItemRect(item)
        if rect.isValid():
            font = item.data(0, vault.Qt.FontRole) or v.tree.font()
            text_end = rect.left() + 16 + v.tree.iconSize().width() + 6 + QFontMetrics(font).horizontalAdvance(item.text(0))
            worst = max(worst, text_end - v.tree.viewport().width())
        it += 1
    return worst  # > 0: something cut off by that many px


panel = lambda: v.tree_splitter.sizes()[0]
open_db([])
short = panel()
ok("short names: panel fits, nothing cut off", all_names_fit() <= 0, all_names_fit())
ok("…and it's narrow (no big empty space)", short <= 260, short)
open_db(["Household and utilities", "Energy suppliers archive"])
longer = panel()
ok("long nested name: panel grows to fit it", longer > short and all_names_fit() <= 0, (short, longer, all_names_fit()))
ok("…but only just (less than 40 px spare)", all_names_fit() > -40, all_names_fit())
v.set_list_text_size(125); QTest.qWait(300)
ok("bigger list text: panel grows, still fits", panel() > longer and all_names_fit() <= 0, (longer, panel(), all_names_fit()))
v.set_list_text_size(100); QTest.qWait(300)
open_db(["A really very extremely long folder name that goes on", "and on and on and on forever more"])
total = sum(v.tree_splitter.sizes())
ok("very long name: capped at 40% of the page", panel() <= total * 0.4 + 1, (panel(), total))
open_db(["Household and utilities", "Energy suppliers archive"])
deep = panel()
item = v.tree.topLevelItem(0)
v.tree.collapseItem(item); QTest.qWait(300)
ok("collapsing everything: panel shrinks back to the heading's width", panel() < deep, (deep, panel()))
w.grab().save(str(s / "fit_panel.png"))
print(f"--- {'ALL PASSED' if not fails else str(len(fails)) + ' FAILED'}", flush=True)
sys.stdout.flush(); os._exit(1 if fails else 0)
