import sys
import helpers  # repo path; temporary folder, settings and test databases
from pathlib import Path
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

s = helpers.WORK
app = QApplication(sys.argv)
import vault, store
from PySide6.QtCore import QSettings
vault.settings = QSettings(str(s / 'gen_btn_test.ini'), QSettings.IniFormat)
vault.settings.clear()
vault.setTheme(vault.Theme.LIGHT)
ok = lambda c: "OK  " if c else "FAIL"

db = store.Database(s / "feat41.kdbx", "test-pw-123", "")
w = vault.MainWindow()
w.setMicaEffectEnabled(False)
w.show()
QTest.qWaitForWindowExposed(w)
w.vault.load(db)

# New entry: options shown, Generate keeps them shown and makes a new password every click
ed = vault.EntryEditor(w, db)
ed.show()
QTest.qWait(300)
print(ok(ed.generator.isVisible()), "new entry: generator options visible on open")
seen = {ed.password.text()}
for i in range(3):
    QTest.mouseClick(ed.gen_btn, Qt.LeftButton)
    QTest.qWait(100)
    seen.add(ed.password.text())
    print(ok(ed.generator.isVisible()), f"after Generate click {i + 1}: options visible={ed.generator.isVisible()}, password={ed.password.text()}")
print(ok(len(seen) == 4), "each click produced a new password")
QTest.mouseClick(ed.generator.mode.items["passphrase"], Qt.LeftButton)
QTest.qWait(100)
QTest.mouseClick(ed.gen_btn, Qt.LeftButton)
QTest.qWait(150)
print(ok(ed.generator.phrase_opts.isVisible() and "-" in ed.password.text()), "passphrase mode survives Generate:", ed.password.text())
w.grab().save(str(s / "gen_fixed.png"))
close = [b for b in ed.generator.findChildren(vault.TransparentToolButton) if b.toolTip() == "Hide generator options"][0]
QTest.mouseClick(close, Qt.LeftButton)
QTest.qWait(100)
print(ok(not ed.generator.isVisible()), "✕ hides the options")
QTest.mouseClick(ed.gen_btn, Qt.LeftButton)
QTest.qWait(100)
print(ok(ed.generator.isVisible()), "Generate shows them again")
ed.close()

# Existing entry: options hidden until Generate is clicked
e = db.entries[0]
ed2 = vault.EntryEditor(w, db, entry=e)
ed2.show()
QTest.qWait(200)
print(ok(not ed2.generator.isVisible() and ed2.password.text() == e["raw"]["password"]), "edit: password unchanged, options hidden")
QTest.mouseClick(ed2.gen_btn, Qt.LeftButton)
QTest.qWait(100)
print(ok(ed2.generator.isVisible() and ed2.password.text() != e["raw"]["password"]), "edit: Generate shows options + new password")
ed2.close()

for key in ("mode", "length", "words", "separator", "avoid", "capitalize", "number", "upper", "lower", "digits", "symbols"):
    vault.settings.remove(f"gen/{key}")
