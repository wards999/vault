"""Old copies in a "Backup" folder (KeePass 1 style) are greyed and italic in the list, so they aren't
mistaken for the live entry; browsing the Backup folder itself shows them normally."""
import sys
import helpers  # repo path; temporary folder, settings and test databases
from helpers import ok, finish
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QStyleOptionViewItem
from pykeepass import create_database

app = QApplication(sys.argv)
import vault, store

path = helpers.WORK / "backup41.kdbx"
path.unlink(missing_ok=True)
kp = create_database(str(path), password=helpers.PW)
kp.add_entry(kp.root_group, "GitHub", "me", "live-pw")
backup = kp.add_group(kp.root_group, "Backup")
kp.add_entry(backup, "GitHub", "me", "old-pw")
nested = kp.add_group(kp.add_group(kp.root_group, "Work"), "backup")
kp.add_entry(nested, "Intranet", "me", "old-intranet")
kp.save()

db = store.Database(path, helpers.PW, "")
by_password = {e["password"]: e for e in db.entries}
ok("entry in Backup is marked", by_password["old-pw"]["backup"])
ok("…and in a nested folder called 'backup'", by_password["old-intranet"]["backup"])
ok("the live entry isn't", not by_password["live-pw"]["backup"])
ok("Backup folders are marked too", {f["name"] for f in db.folders if f["backup"]} == {"Backup", "backup"})

w = vault.MainWindow(); w.setMicaEffectEnabled(False); w.show(); QTest.qWaitForWindowExposed(w)
w.vault.load(db); w.saver.attach(db); w.locked = False
v = w.vault
model, delegate = v.model, v.delegate


def looks(password):
    row = next(i for i, e in enumerate(model.entries) if e["password"] == password)
    index = model.index(row, 0)
    option = QStyleOptionViewItem()
    delegate.initStyleOption(option, index)
    return option.font.italic(), model.data(index, vault.R_FOREGROUND) == vault.EXPIRED_COLOR


v.folder = None; v.refresh()
ok("All entries: the backup copy is italic and grey", looks("old-pw") == (True, True))
ok("All entries: the live entry is normal", looks("live-pw") == (False, False))
v.search.setText("github"); v.refresh()
ok("search: both copies found", {e["password"] for e in model.entries} == {"live-pw", "old-pw"})
ok("search: the backup copy is italic and grey, the live one normal",
   looks("old-pw") == (True, True) and looks("live-pw") == (False, False))
ok("search: tooltip says it's an old copy", "old copy" in (model.data(model.index(
    next(i for i, e in enumerate(model.entries) if e["password"] == "old-pw"), 0), vault.R_TOOLTIP) or ""))
v.search.setText(""); v.folder = next(f["id"] for f in db.folders if f["name"] == "Backup"); v.refresh()
ok("inside the Backup folder: shown normally", looks("old-pw") == (False, False))

import health
same = dict(by_password["old-pw"], password="live-pw")  # a backup copy with the live entry's password
issues = health.report(db.entries + [same])
ok("Password health skips backup copies", not any(i["entry"]["backup"] for i in issues))
ok("…so the live entry isn't flagged as reused with its old copy",
   not any(i["issue"] == "reused" and i["entry"]["password"] == "live-pw" for i in issues),
   [(i["issue"], i["entry"]["title"]) for i in issues])
finish()
