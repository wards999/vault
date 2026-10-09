import sys
import helpers  # repo path; temporary folder, settings and test databases
from pathlib import Path
from pykeepass import create_database
from PySide6.QtCore import QSettings, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

s = helpers.WORK
app = QApplication(sys.argv)
import vault, store
vault.settings = QSettings(str(s / "wildcard_test.ini"), QSettings.IniFormat)
vault.settings.clear()
vault.setTheme(vault.Theme.LIGHT)
ok = lambda c: "OK  " if c else "FAIL"

names = ["simon.ward@gmail.com", "simon@work.co.uk", "john.simon@outlook.com", "ward999", "s.ward@icloud.com",
         "admin", "me@gmail.com", "billing@shop.com", "support@site.com", "dev@company.com", "test.user",
         "family@gmail.com", "simonw", "w.simon@yahoo.com", "guest"]
path = s / "wildcard.kdbx"
kp = create_database(str(path), password="pw")
for i, user in enumerate(names):
    for _ in range(len(names) - i):  # earlier names used more often
        kp.add_entry(kp.root_group, f"Site {i}-{_}", user, "x", force_creation=True)
kp.save()
db = store.Database(path, "pw", "")

w = vault.MainWindow()
w.setMicaEffectEnabled(False)
w.show(); QTest.qWaitForWindowExposed(w)
w.vault.load(db)
w.raise_(); w.activateWindow(); QTest.qWaitForWindowActive(w, 3000)
win = w.windowHandle()

ed = vault.EntryEditor(w, db)
ed.show(); QTest.qWait(250)
before = ed.widget.geometry()
QTest.mouseClick(win, Qt.LeftButton, Qt.NoModifier, ed.username.mapTo(w, ed.username.rect().center()))
QTest.qWait(250)
lst = ed.suggestions
shown = lambda: [lst.item(i).text() for i in range(lst.count())] if lst.isVisible() else []
print(ok(shown() == names), f"empty field: all {len(shown())} usernames, most used first")
print(ok(lst.height() == 6 * 30 + 14 and lst.verticalScrollBar().maximum() > 0), f"shows 6 rows ({lst.height()} px) and scrolls")
print(ok(ed.widget.geometry() == before), "editor size unchanged")
w.grab().save(str(s / "wildcard_all.png"))


def type_(text):
    ed.username.clear()
    QTest.keyClicks(ed.username, text)
    QTest.qWait(150)


type_("simon")
print(ok(shown() == ["simon.ward@gmail.com", "simon@work.co.uk", "john.simon@outlook.com", "simonw", "w.simon@yahoo.com"]),
      "'simon' anywhere in the name:", shown())
print(ok(lst.height() == 5 * 30 + 14), "list shrinks to fit 5 matches")
type_("sim*mail")
print(ok(shown() == ["simon.ward@gmail.com"]), "'sim*mail' wildcard:", shown())
type_("gmail simon")
print(ok(shown() == ["simon.ward@gmail.com"]), "'gmail simon' (any order):", shown())
type_("WARD")
print(ok(shown() == ["simon.ward@gmail.com", "ward999", "s.ward@icloud.com"]), "'WARD' (any case):", shown())

type_("x")
QTest.keyClick(ed.username, Qt.Key_Backspace)  # delete with the keyboard -> full list again
QTest.qWait(150)
print('   debug: field has focus:', ed.username.hasFocus(), '| window active:', QApplication.activeWindow() is w, '| text:', repr(ed.username.text()))
print(ok(len(shown()) == 15), 'deleting the text with Backspace brings back the full list:', len(shown()))
for _ in range(10):
    QTest.keyClick(ed.username, Qt.Key_Down)
cur = lst.currentItem()
visible = lst.viewport().rect().contains(lst.visualItemRect(cur))
print(ok(cur.text() == names[9] and visible), f"Down x10 selects '{cur.text()}' and scrolls it into view")
QTest.keyClick(ed.username, Qt.Key_Return)
QTest.qWait(150)
print(ok(ed.username.text() == names[9]), "Enter picks it:", ed.username.text())
