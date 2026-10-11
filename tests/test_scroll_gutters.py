"""The entry list's cards stop where its scrollbar starts (the UI library's scrollbars float over the
rows, so text showed around them), also after the list text size is changed. The cards fit the list's
width, so there's never a sideways scrollbar."""
import sys
import helpers  # repo path; temporary folder, settings and test databases
from helpers import ok, finish
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

app = QApplication(sys.argv)
import vault, store

path = helpers.copy_db("big41.kdbx", "gutters41.kdbx")  # 300 entries: the list scrolls
w = vault.MainWindow(); w.setMicaEffectEnabled(False); w.resize(1100, 700); w.show(); QTest.qWaitForWindowExposed(w)
db = store.Database(path, helpers.PW, "")
w.vault.load(db); w.saver.attach(db); w.locked = False
v = w.vault
t, bars = v.table, v.table.scrollDelagate


def check(when):
    QTest.qWait(300)
    rows = t.viewport().geometry()
    ok(f"{when}: the scrollbar shows, and no sideways one", bars.vScrollBar.isVisible() and not bars.hScrollBar.isVisible())
    ok(f"{when}: cards stop at the scrollbar", rows.right() < bars.vScrollBar.x(),
       (rows.getRect(), bars.vScrollBar.geometry().getRect()))


check("300 entries")
v.set_list_text_size(125)
check("text size changed")
v.set_list_text_size(100)
check("text size back")
finish()
