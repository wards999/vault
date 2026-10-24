"""Makes the README's screenshots (docs/*.png, light and dark) from a made-up demo database.

Usage (from the repo folder):  python tools/screenshots.py

Settings, backups and the demo database go to a temporary folder, never the real ones.
"""
import os
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
WORK = Path(tempfile.mkdtemp(prefix="vault-shots-"))
os.environ["VAULT_SETTINGS"] = str(WORK / "settings.ini")
os.environ["VAULT_BACKUPS"] = str(WORK / "backups")

from pykeepass import create_database  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

PW = "demo-pw"
OUT = REPO / "docs"
OTP = "otpauth://totp/Example%3Aalex?secret=JBSWY3DPEHPK3PXP&period=30&digits=6&issuer=Example"

ENTRIES = {  # folder: (title, username, password, website, notes)
    "Personal": [
        ("Email", "alex.morgan@example.com", "tidal-Lantern-42-orbit", "https://mail.example.com", ""),
        ("Bank", "alexmorgan", "R7#qv!2LmZp9@wXe", "https://bank.example.com", "Card PIN in the safe."),
        ("Home Wi-Fi", "", "maple-Harbor-17-violet", "", "Router in the hall cupboard."),
        ("Photos", "alex.morgan@example.com", "c0ral-Sketch-88-frost", "https://photos.example.com", ""),
    ],
    "Work": [
        ("Code hosting", "alex-morgan", "Gq8$Tn2!vK5#rY7p", "https://code.example.com", "2FA on."),
        ("Team chat", "alex@company.example", "quiet-Meadow-63-ember", "https://chat.example.com", ""),
        ("Timesheets", "amorgan", "hT4%mW9@bX2&kL6s", "https://hr.example.com", ""),
    ],
    "Shopping": [
        ("Online shop", "alex.morgan@example.com", "Bx5!pR8#nQ3$wT1z", "https://shop.example.com", ""),
        ("Groceries", "alex.morgan@example.com", "amber-Pocket-29-river", "https://groceries.example.com", ""),
    ],
}


def demo_db(path):
    kp = create_database(str(path), password=PW)
    kp.kdbx.header.value.minor_version = 1
    for folder, entries in ENTRIES.items():
        group = kp.add_group(kp.root_group, folder)
        for title, user, pw, url, notes in entries:
            tags = ["Favourite"] if title in ("Email", "Bank", "Code hosting") else None
            e = kp.add_entry(group, title, user, pw, url=url or None, notes=notes or None, tags=tags)
            if title == "Code hosting":
                e.otp = OTP
    kp.save()


THEMES = {"Light": "", "Dark": "-dark"}  # theme: file name suffix


def main():
    if len(sys.argv) < 2:  # each theme in a fresh copy of this script (one ends with the editor open)
        for theme in THEMES:
            subprocess.run([sys.executable, __file__, theme], check=True)
        return
    theme = sys.argv[1]
    OUT.mkdir(exist_ok=True)
    db_path = WORK / "Demo.kdbx"
    demo_db(db_path)

    app = QApplication(sys.argv)
    import vault
    import store

    vault.apply_theme(theme)  # before the window, so it's drawn in the theme from the start
    w = vault.MainWindow()
    w.setMicaEffectEnabled(False)  # (apply_theme(theme, w) would turn Mica on: a see-through grab)
    w.setCustomBackgroundColor(*vault.DEFAULT_BACKGROUNDS)
    w.resize(1200, 720)
    w.show()
    QTest.qWaitForWindowExposed(w)
    db = store.Database(db_path, PW, "")
    w.vault.load(db)
    w.saver.attach(db)
    w.locked = False
    v = w.vault
    QTest.qWait(1500)

    def shot(name):
        QTest.qWait(400)
        path = OUT / name.replace(".png", THEMES[theme] + ".png")
        w.grab().save(str(path))
        print("saved", path, flush=True)  # (os._exit below skips flushing)

    # 1. The list, with an entry's details beside it
    row = next(r for r in range(v.model.rowCount()) if v.model.index(r, 0).data() == "Code hosting")
    v.table.selectRow(row)
    shot("main.png")

    # 2. The details below the list, which then shows columns
    w.resize(1200, 800)
    v.set_details_below(True, save=False)
    v.notes.tabs.setCurrentItem("details")  # (the demo's notes are hidden dots)
    v.table.selectRow(row)
    shot("below.png")
    v.set_details_below(False, save=False)
    w.resize(1200, 720)

    # 3. Adding an entry, with the password generator
    v.new_entry()
    QTest.qWait(300)
    ed = v.editor
    ed.title.setText("Streaming")
    ed.username.setText("alex.morgan@example.com")
    ed.url.setText("https://tv.example.com")
    ed._generate()
    shot("new-entry.png")

    os._exit(0)


main()
