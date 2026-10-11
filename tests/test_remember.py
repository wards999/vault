import sys, time
import helpers  # repo path; temporary folder, settings and test databases
from pathlib import Path
from PySide6.QtCore import Qt, QSettings, QRect
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

s = helpers.WORK
ini = s / "remember_test.ini"
ini.unlink(missing_ok=True)
app = QApplication(sys.argv)
import vault, store
vault.settings = QSettings(str(ini), QSettings.IniFormat)  # never touch the user's real settings
ok = lambda c: "OK  " if c else "FAIL"
db = store.Database(s / "test.kdbx", "test123", "")


def window():
    w = vault.MainWindow()
    w.setMicaEffectEnabled(False)
    w.show()
    QTest.qWaitForWindowExposed(w)
    w.vault.load(db)
    w._closing = True
    QTest.qWait(150)
    return w


# 1. size + position
w = window()
w.setGeometry(QRect(220, 140, 1100, 700))
QTest.qWait(200)
before = w.geometry()
w.close()
w = window()
print(ok(w.geometry() == before), "window size/position restored:", before.getRect(), "->", w.geometry().getRect())
w.showMaximized()
QTest.qWait(300)
w.close()
w = window()
QTest.qWait(300)
print(ok(w.isMaximized()), "maximised window comes back maximised")
w.showNormal()
QTest.qWait(200)

# 2. the list's order (Sort menu)
w.vault.sort_by(vault.EntryModel.MODIFIED, Qt.DescendingOrder)  # "Recently changed"
w.close()
w = window()
m = w.vault.model
print(ok((m.sort_column, m.sort_order) == (vault.EntryModel.MODIFIED, Qt.DescendingOrder)),
      "sort order restored (Recently changed)")
keys = [e["modified_key"] for e in m.entries]
print(ok(keys == sorted(keys, reverse=True)), "rows are actually sorted newest first")

# 3. clipboard timing
settings_view = w.stackedWidget.widget(w.stackedWidget.count() - 1)
combos = settings_view.findChildren(vault.ComboBox)
clip = next(c for c in combos if c.findText("10 seconds") >= 0)
clip.setCurrentText("10 seconds")
print(ok(vault.clipboard_seconds() == 10), "setting saved: 10 seconds")
w.copy_secret("secret-xyz", "Password")
QTest.qWait(500)
note = [b.contentLabel.text() for b in w.findChildren(vault.InfoBar) if b.isVisible()]
print(ok(any("10 seconds" in n for n in note)), "copy message says:", note)
print(ok(QApplication.clipboard().text() == "secret-xyz"), "copied")
QTest.qWait(10200)
print(ok(QApplication.clipboard().text() == ""), "cleared after 10 seconds")
clip.setCurrentText("Never")
w.copy_secret("keep-me", "Password")
QTest.qWait(500)
print(ok(vault.clipboard_seconds() == 0 and QApplication.clipboard().text() == "keep-me"), "Never: not scheduled to clear")
QApplication.clipboard().clear()

# 4. carry-over from the old on/off switch
vault.settings.remove("clipboard_seconds")
vault.settings.setValue("clear_clipboard", False)
print(ok(vault.clipboard_seconds() == 0), "old 'off' -> Never")
vault.settings.setValue("clear_clipboard", True)
print(ok(vault.clipboard_seconds() == 30), "old 'on' -> 30 seconds")
w.close()
