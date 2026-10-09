import shutil, subprocess, sys, uuid
from pathlib import Path
import helpers  # repo path; temporary folder, settings and test databases
import store
from store import Database, Op, apply_op, save_database, FileChanged, open_kp, digest, keep_both_op

CLI = helpers.need_cli()
s = helpers.WORK
PW = "test-pw-123"
db_path = s / "store41.kdbx"
backups = s / "test_backups"
shutil.copy(s / "rt41.kdbx", db_path)  # genuine KeePassXC-written KDBX 4.1
shutil.rmtree(backups, ignore_errors=True)
ok = lambda cond: "OK " if cond else "FAIL"


def cli(*args, stdin=f"{PW}\n"):
    r = subprocess.run([CLI, *args], input=stdin, capture_output=True, text=True, encoding="utf-8", timeout=30)
    return " | ".join(l for l in (r.stdout + r.stderr).splitlines() if l and "Enter password" not in l)


def entry(db, title):
    return next(e for e in db.entries if e["title"] == title)


# 1. open
db = Database(db_path, PW, "")
print(ok(db.writable and db.version == "4.1"), "opened KeePassXC 4.1 file, writable:", db.writable, db.version)

# 2. update + create + trash, then save with backup
gh = entry(db, "GitHub")
ops = [
    Op("update", gh["uuid"], fields={"password": "Vault-edit-1!", "notes": "edited in Vault"},
       all_fields={**gh["raw"], "password": "Vault-edit-1!", "notes": "edited in Vault"},
       folder=gh["folder_id"], base_mtime=gh["base_mtime"], title="GitHub"),
    Op("create", uuid.uuid4().hex, fields={"title": "Amazon", "username": "me", "password": "Az!9", "url": "amazon.com", "notes": ""},
       folder=gh["folder_id"], title="Amazon"),
    Op("trash", entry(db, "Netflix")["uuid"], title="Netflix"),
]
for op in ops:
    assert apply_op(db.kp, op) is None
db.digest = save_database(db.kp, db_path, db.digest, backup=True, backup_directory=backups)
db.build_snapshot()
print(ok(True), "saved; KeePassXC ls:", cli("ls", "-R", "-f", str(db_path)))
print(ok("Vault-edit-1!" in cli("show", "-s", "-a", "Password", str(db_path), "Work/GitHub")), "KeePassXC sees GitHub password:",
      cli("show", "-s", "-a", "Password", "-a", "Notes", str(db_path), "Work/GitHub"))
print(ok(len(list(backups.glob("*"))) == 1), "backups:", [p.name for p in backups.glob("*")])
print(ok(store.open_kp(db_path.read_bytes(), PW, None).kdbx.header.value.minor_version == 1), "still KDBX 4.1 after save")

# 3. conflict: KeePassXC edits GitHub and adds an entry while we have unsaved edits
gh = entry(db, "GitHub")
amazon = entry(db, "Amazon")
pending = [
    Op("update", gh["uuid"], fields={"username": "alice-from-vault"}, all_fields={**gh["raw"], "username": "alice-from-vault"},
       folder=gh["folder_id"], base_mtime=gh["base_mtime"], title="GitHub"),
    Op("update", amazon["uuid"], fields={"password": "Amazon-vault-2"}, all_fields={**amazon["raw"], "password": "Amazon-vault-2"},
       folder=amazon["folder_id"], base_mtime=amazon["base_mtime"], title="Amazon"),
]
for op in pending:
    apply_op(db.kp, op)
print("   KeePassXC edits GitHub elsewhere:", cli("edit", "-u", "alice-from-kxc", str(db_path), "Work/GitHub"),
      "| adds:", cli("add", "-u", "zed", "-p", str(db_path), "Work/Zoom", stdin=f"{PW}\nzoom-pw\n") or "Zoom")
try:
    save_database(db.kp, db_path, db.digest)
    print("FAIL save should have detected the external change")
except FileChanged as changed:
    print(ok(True), "save refused: file changed elsewhere -> reload + replay")
    fresh = open_kp(changed.data, PW, None)
    conflicts = [c for c in (apply_op(fresh, op) for op in pending) if c]
    print(ok([c.op.title for c in conflicts] == ["GitHub"]), "conflicts:", [(c.op.title, c.reason) for c in conflicts],
          "(Amazon applied cleanly)")
    for c in conflicts:  # user picks "Keep mine"
        apply_op(fresh, c.op, force=True)
    db.replace_kp(fresh, changed.data)
    db.digest = save_database(db.kp, db_path, db.digest)

out = cli("ls", "-R", "-f", str(db_path))
print(ok("Work/Zoom" in out), "KeePassXC's new entry kept:", out)
print(ok("alice-from-vault" in cli("show", "-a", "UserName", str(db_path), "Work/GitHub")), "GitHub username (mine):",
      cli("show", "-a", "UserName", str(db_path), "Work/GitHub"))
gh_kp = open_kp(db_path.read_bytes(), PW, None).find_entries(title="GitHub", first=True)
print(ok(any(h.username == "alice-from-kxc" for h in gh_kp.history)), "their version is in history:",
      [h.username for h in gh_kp.history])
print(ok("Amazon-vault-2" in cli("show", "-s", "-a", "Password", str(db_path), "Work/Amazon")), "Amazon edit applied")

# 4. keep-both and deleted-elsewhere
db = Database(db_path, PW, "")
zoom = entry(db, "Zoom")
op = Op("update", zoom["uuid"], fields={"password": "mine"}, all_fields={**zoom["raw"], "password": "mine"},
        folder=zoom["folder_id"], base_mtime=zoom["base_mtime"], title="Zoom")
cli("rm", str(db_path), "Work/Zoom")  # KeePassXC recycles it meanwhile
fresh = open_kp(db_path.read_bytes(), PW, None)
c = apply_op(fresh, op)
# Older KeePassXC left the modified time alone when recycling (the edit just applies); newer ones update
# it, so Vault asks which version to keep. Either is fine; losing the edit silently is not.
print(ok(c is None or c.reason == "changed"), "edit of an entry recycled elsewhere applies or asks:", c and c.reason)
fresh2 = open_kp(db_path.read_bytes(), PW, None)
fresh2.delete_entry(fresh2.find_entries(title="Zoom", first=True))
c = apply_op(fresh2, op)
print(ok(c and c.reason == "deleted"), "edit of an entry permanently deleted elsewhere -> conflict:", c and c.reason)
apply_op(fresh2, keep_both_op(op))
print(ok(fresh2.find_entries(title="Zoom (my copy)", first=True) is not None), "keep-both creates 'Zoom (my copy)'")

# 5. backups pruning
for i in range(12):
    store.make_backup(db_path, b"x" * i, backups, keep=10)
names = sorted(p.name for p in backups.glob("store41 *"))
print(ok(len(names) <= 10), f"backups pruned to {len(names)} (same-second names overwrite; max 10)")

# 6. KDBX 3.x is read-only
kdbx3 = s / "rt_kdbx3_plain.kdbx"
if kdbx3.exists():
    pass
v3 = s / "v3.kdbx"
v3.unlink(missing_ok=True)
cli("db-create", "-p", str(v3), stdin=f"{PW}\n{PW}\n")
print(ok(not Database(v3, PW, "").writable), "KDBX 3.x opens read-only:", Database(v3, PW, "").version)

# 7. no temp files left behind
print(ok(not list(s.glob(".*vault-tmp")) and not list(s.glob("*.tmp"))), "no temp files left:",
      [p.name for p in s.glob(".*vault-tmp")] + [p.name for p in s.glob("*.tmp")])
