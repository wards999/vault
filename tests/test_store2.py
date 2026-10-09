"""Tests the new store operations (undo, folders, duplicate, icons, 2FA) and KeePassXC compatibility."""
import shutil, subprocess, sys, time
from pathlib import Path
import helpers  # repo path; temporary folder, settings and test databases
import pyotp
import store, totp, health
from store import Database, Op, apply_op, inverse_op, duplicate_op, save_database, open_kp

CLI = helpers.need_cli()
s = helpers.WORK
PW = "test-pw-123"
path = s / "ops41.kdbx"
shutil.copy(s / "rt41.kdbx", path)
ok = lambda c: "OK  " if c else "FAIL"


def cli(*args, stdin=f"{PW}\n"):
    r = subprocess.run([CLI, *args], input=stdin, capture_output=True, text=True, encoding="utf-8", timeout=30)
    return " | ".join(l for l in (r.stdout + r.stderr).splitlines() if l and "Enter password" not in l)


db = Database(path, PW, "")
undo = []


def do(op):
    inv = inverse_op(db.kp, op)
    assert apply_op(db.kp, op) is None, op
    undo.append(inv)
    db.build_snapshot()


def save():
    db.digest = save_database(db.kp, path, db.digest)


def entry(title):
    return next((e for e in db.entries if e["title"] == title), None)


def folder(name):
    return next((f for f in db.folders if f["name"] == name), None)


# Folders: create, rename, nested, move entry, trash folder
import uuid
fid = uuid.uuid4().hex
do(Op("folder_create", fid, fields={"name": "Banking"}, folder=None, title="Banking"))
do(Op("folder_rename", fid, fields={"name": "Finance"}, title="Finance"))
sub = uuid.uuid4().hex
do(Op("folder_create", sub, fields={"name": "Cards"}, folder=fid, title="Cards"))
gh = entry("GitHub")
do(Op("move", gh["uuid"], folder=sub, title="GitHub"))
save()
print(ok("Finance/Cards/GitHub" in cli("ls", "-R", "-f", str(path))), "KeePassXC sees folders + moved entry:", cli("ls", "-R", "-f", str(path)))

# Duplicate (keeps icon/fields), 2FA set
dup = duplicate_op(db.kp, entry("GitHub")["uuid"])
do(dup)
secret = pyotp.random_base32()
do(Op("update", entry("GitHub")["uuid"], fields={"otp": secret}, base_mtime=entry("GitHub")["base_mtime"], title="GitHub"))
save()
print(ok("GitHub - Copy" in cli("ls", "-R", "-f", str(path))), "duplicate created")
kxc_totp = cli("show", "-t", str(path), "Finance/Cards/GitHub")
mine = totp.code(entry("GitHub")["totp"])[0]
print(ok(kxc_totp.strip() == mine), f"2FA: KeePassXC code {kxc_totp} == Vault code {mine}")
fields = store.string_fields(store._find_entry(db.kp, entry("GitHub")["uuid"])._element)
print(ok(fields.get("TimeOtp-Secret-Base32") == secret), "KeePass 2 TimeOtp-Secret-Base32 written too")

# KeePass 2-only 2FA is read
kp2 = store._find_entry(db.kp, entry("Netflix")["uuid"])
kp2._set_string_field("TimeOtp-Secret-Base32", secret, True)
db.build_snapshot()
print(ok(entry("Netflix")["totp"] and totp.code(entry("Netflix")["totp"])[0] == mine), "reads KeePass 2 format 2FA")

# Icons: set, dedupe, KeePassXC keeps it
png = (s / "vault_icon_test.png")
from PySide6.QtGui import QGuiApplication
app = QGuiApplication([])
import favicon
data = favicon._to_png((helpers.REPO / "icons" / "vault.png").read_bytes())
do(Op("set_icon", entry("GitHub")["uuid"], icon=data, icon_name="github.com", title="GitHub"))
do(Op("set_icon", entry("Netflix")["uuid"], icon=data, icon_name="github.com", title="Netflix"))
save()
icons = db.kp.tree.getroot().findall("Meta/CustomIcons/Icon")
print(ok(entry("GitHub")["icon"][1] and entry("GitHub")["icon"][1] == entry("Netflix")["icon"][1]),
      f"icon set on both entries, stored once ({len(icons)} custom icons)")
print(ok(icons[-1].findtext("Name") == "github.com"), "icon name stored (KDBX 4.1)")
cli("edit", "-u", "kxc-touch", str(path), "Finance/Cards/GitHub")  # KeePassXC rewrites the file
again = Database(path, PW, "")
print(ok(next(e for e in again.entries if e["title"] == "GitHub")["icon"][1] is not None), "icon survives a KeePassXC save")
db = again
undo = []

# Undo: trash, permanent delete, edit, folder trash
nf = entry("Netflix")
do(Op("trash", nf["uuid"], title="Netflix"))
print(ok(entry("Netflix")["in_bin"]), "trashed")
apply_op(db.kp, undo.pop()); db.build_snapshot()
print(ok(not entry("Netflix")["in_bin"] and entry("Netflix")["folder"] == "Work"), "undo trash -> back in Work")
do(Op("delete", nf["uuid"], title="Netflix"))
print(ok(entry("Netflix") is None), "deleted permanently")
apply_op(db.kp, undo.pop()); db.build_snapshot()
print(ok(entry("Netflix") is not None and entry("Netflix")["icon"][1]), "undo delete -> restored with icon")
gh = entry("GitHub")
do(Op("update", gh["uuid"], fields={"password": "new!", "url": "x.com"}, base_mtime=gh["base_mtime"], title="GitHub"))
apply_op(db.kp, undo.pop(), force=True); db.build_snapshot()
print(ok(entry("GitHub")["url"] == gh["url"] and entry("GitHub")["password"] == gh["password"]), "undo edit -> old values back")
fin = folder("Finance")
do(Op("folder_trash", fin["id"], title="Finance"))
print(ok(folder("Finance")["in_bin"]), "folder trashed with contents:", [e["title"] for e in db.entries if e["in_bin"]])
apply_op(db.kp, undo.pop()); db.build_snapshot()
print(ok(not folder("Finance")["in_bin"]), "undo folder trash")
do(Op("folder_move", fin["id"], folder=folder("Cards")["id"], title="Finance"))
print(ok(folder("Finance")["parent"] is None), "refuses to move a folder into its own subfolder")
save()
print(ok("Finance/Cards/GitHub" in cli("ls", "-R", "-f", str(path))), "final KeePassXC ls:", cli("ls", "-R", "-f", str(path)))
print(ok(Database(path, PW, "").version == "4.1"), "still KDBX 4.1")

# Health report
issues = health.report(db.entries)
print("health:", health.summary(issues), [(i["issue"], i["entry"]["title"], i["detail"]) for i in issues][:6])
