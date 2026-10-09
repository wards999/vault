"""Username suggestions shown inside the dialog: Cancel works with one click; picking works."""
import sys
import helpers  # repo path; temporary folder, settings and test databases
from pathlib import Path
from PySide6.QtCore import QSettings, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

s = helpers.WORK
app = QApplication(sys.argv)
import vault, store
vault.settings = QSettings(str(s / "cancel_test.ini"), QSettings.IniFormat)
vault.settings.clear()
vault.setTheme(vault.Theme.LIGHT)
db = store.Database(s / "complete.kdbx", "pw", "")  # me@gmail.com x5, work@company.com x3, oldname x1
w = vault.MainWindow()
w.setMicaEffectEnabled(False)
w.show(); QTest.qWaitForWindowExposed(w)
w.vault.load(db)
w.raise_(); w.activateWindow(); QTest.qWaitForWindowActive(w, 3000)
win = w.windowHandle()
ok = lambda c: "OK  " if c else "FAIL"


def click(widget, pos=None):
    """Click through the window-system path, which handles pop-ups like a real mouse."""
    w.activateWindow(); QTest.qWaitForWindowActive(w, 2000)
    pos = widget.mapTo(w, pos if pos is not None else widget.rect().center())
    QTest.mouseClick(win, Qt.LeftButton, Qt.NoModifier, pos)
    QTest.qWait(200)


def shown(ed):
    return [ed.suggestions.item(i).text() for i in range(ed.suggestions.count())] if ed.suggestions.isVisible() else []


def editor():
    ed = vault.EntryEditor(w, db)
    ed.show()
    QTest.qWait(250)
    return ed


# 1. Cancel with suggestions showing: one click
for typed in ("", "w"):
    ed = editor()
    click(ed.username)
    if typed:
        QTest.keyClicks(ed.username, typed)
        QTest.qWait(150)
    visible = shown(ed)
    click(ed.cancelButton)
    print(ok(visible and not ed.isVisible()), f"suggestions {visible} showing -> ONE click on Cancel closes the editor")
    if ed.isVisible():
        ed.reject(); QTest.qWait(150)

# 2. behaviour
ed = editor()
before = (ed.widget.geometry(), ed.scroll.height())
click(ed.username)
after = (ed.widget.geometry(), ed.scroll.height())
print(ok(shown(ed) and before == after), 'dialog size unchanged when suggestions appear:', before[0].getRect(), '->', after[0].getRect())
over = ed.suggestions.geometry().bottom() > ed.password.mapTo(ed.widget, ed.password.rect().topLeft()).y()
print(ok(over), 'list floats over the fields below')
print(ok(shown(ed) == ["me@gmail.com", "work@company.com", "oldname"]), "focus on empty field shows all, most used first:", shown(ed))
w.grab().save(str(s / "suggest_inline.png"))
vault.setTheme(vault.Theme.DARK); QTest.qWait(200); w.grab().save(str(s / "suggest_dark.png")); vault.setTheme(vault.Theme.LIGHT); QTest.qWait(200)
click(ed.username)
QTest.keyClicks(ed.username, "COMP")
QTest.qWait(150)
print(ok(shown(ed) == ["work@company.com"]), "typing 'COMP' filters (any part, any case):", shown(ed))
item = ed.suggestions.item(0)
click(ed.suggestions.viewport(), ed.suggestions.visualItemRect(item).center())
print(ok(ed.username.text() == "work@company.com" and not shown(ed)), "click a suggestion -> filled, list hidden:", ed.username.text())

click(ed.username)
ed.username.clear()
QTest.keyClicks(ed.username, "m")
QTest.qWait(150)
QTest.keyClick(ed.username, Qt.Key_Down)
QTest.keyClick(ed.username, Qt.Key_Return)
QTest.qWait(150)
print(ok(ed.username.text() == "me@gmail.com" and ed.isVisible()), "Down + Enter picks the first suggestion (dialog stays open):", ed.username.text())

click(ed.username)
ed.username.clear()
QTest.keyClicks(ed.username, "o")
QTest.qWait(150)
had = bool(shown(ed))
QTest.keyClick(ed.username, Qt.Key_Escape)
QTest.qWait(150)
print(ok(had and not shown(ed) and ed.isVisible()), "Esc hides only the list, not the dialog")

click(ed.username)
QTest.keyClicks(ed.username, "l")
QTest.qWait(150)
had = bool(shown(ed))
QTest.keyClick(ed.username, Qt.Key_Tab)
QTest.qWait(400)
print(ok(had and not shown(ed)), "Tab to the next field hides the list")

ed.title.setText("Test")
click(ed.yesButton)
print(ok(not ed.isVisible() and ed.op is not None), "Save still works with one click")
