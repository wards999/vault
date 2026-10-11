"""The entry list's rows stop where its scrollbars start (the UI library's scrollbars float over the
rows, so text showed around them), and keep doing so after the list text size is changed."""
import sys
import helpers  # repo path; temporary folder, settings and test databases
from helpers import ok, finish
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

app = QApplication(sys.argv)
import vault, store

path = helpers.copy_db("dnd41.kdbx", "gutters41.kdbx")
w = vault.MainWindow(); w.setMicaEffectEnabled(False); w.resize(700, 300); w.show(); QTest.qWaitForWindowExposed(w)
db = store.Database(path, helpers.PW, "")
w.vault.load(db); w.saver.attach(db); w.locked = False
v = w.vault
t, bars = v.table, v.table.scrollDelagate


def check(when):
    QTest.qWait(300)
    rows = t.viewport().geometry()
    ok(f"{when}: both scrollbars showing", bars.vScrollBar.isVisible() and bars.hScrollBar.isVisible())
    ok(f"{when}: rows stop at the side scrollbar", rows.right() < bars.vScrollBar.x(),
       (rows.getRect(), bars.vScrollBar.geometry().getRect()))
    ok(f"{when}: rows stop at the bottom scrollbar", rows.bottom() < bars.hScrollBar.y(),
       (rows.getRect(), bars.hScrollBar.geometry().getRect()))


check("small window")
v.set_list_text_size(125)
check("text size changed")
v.set_list_text_size(100)
check("text size back")
finish()
