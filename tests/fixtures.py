"""Test databases, built from code with made-up data (no database files in the repo).

All are KDBX 4.1 with the password "test-pw-123", except where noted:
  rt41.kdbx           Work/GitHub (history, tags), Work/Netflix (weak), Recycle Bin/Slack and /Bank
  big41.kdbx          rt41 plus 300 entries in the root folder
  foldericons41.kdbx  rt41 plus Banking (icon 37)/Cards, Email (icon 19) and Plain folder
  dnd41.kdbx          Work/Wikipedia, Work/Netflix, Finance/Cards/GitHub (2FA), Recycle Bin
  test.kdbx           password "test123": nested folders, a {REF:...} entry and 2000 bulk entries
  complete.kdbx       password "pw": repeated usernames, for username suggestions
"""
import random
from pathlib import Path

from pykeepass import PyKeePass, create_database

PW = "test-pw-123"
OTP = "otpauth://totp/GitHub%3Aalice-final?secret=CNEYB6VXL3EV2DAHW22NI2ECECC5542B&period=30&digits=6&issuer=GitHub"
SITES = ["Netflix", "Microsoft", "Twitter", "eBay", "Google", "Adobe", "Amazon", "Apple", "Dropbox", "Spotify"]


def _new(path, password=PW):
    path = Path(path)
    path.unlink(missing_ok=True)
    kp = create_database(str(path), password=password)
    kp.kdbx.header.value.minor_version = 1  # KDBX 4.1, like files KeePassXC writes
    return kp


def _with_history(kp, entry, passwords):
    """Gives `entry` older versions with these passwords (oldest first), then its current one."""
    current = entry.password
    for old in passwords:
        entry.password = old
        entry.save_history()
    entry.password = current


def _base(kp, github_folder=None):
    """The rt41 contents: Work/GitHub, Work/Netflix and two entries in the Recycle Bin."""
    work = kp.add_group(kp.root_group, "Work")
    gh = kp.add_entry(github_folder(kp) if github_folder else work, "GitHub", "alice-final",
                      "edited-in-4.1-by-pykeepass", url="https://github.com", tags=["dev", "important"])
    _with_history(kp, gh, ["orig-pw", "orig-pw", "edited-by-pykeepass!", "edited-by-pykeepass!"])
    nf = kp.add_entry(work, "Netflix", "x", "nf-pw")
    _with_history(kp, nf, ["nf-pw"])
    for title, user, pw in (("Slack", "bob", "slack-pw"), ("Bank", "carol", "bank-pw")):
        kp.trash_entry(kp.add_entry(kp.root_group, title, user, pw))
    return kp, work, gh


def rt41(path):
    kp, _, _ = _base(_new(path))
    kp.save()


def big41(path):
    kp, _, _ = _base(_new(path))
    rng = random.Random(41)
    for i in range(300):
        site = SITES[i % len(SITES)]
        kp.add_entry(kp.root_group, f"{site} {i}", f"user{i}@example.com", f"Pw-{i}-{rng.random():.6f}",
                     url=f"https://{site.lower()}.com")
    kp.save()


def foldericons41(path):
    kp, _, _ = _base(_new(path))
    banking = kp.add_group(kp.root_group, "Banking", icon="37")
    kp.add_group(banking, "Cards", icon="0")
    kp.add_group(kp.root_group, "Email", icon="19")
    kp.add_group(kp.root_group, "Plain folder")
    kp.save()


def dnd41(path):
    kp = _new(path)
    finance = kp.add_group(kp.root_group, "Finance")
    cards = kp.add_group(finance, "Cards")
    kp, work, gh = _base(kp, github_folder=lambda _: cards)
    gh.otp = OTP
    kp.add_entry(work, "Wikipedia", "me", "szByC6K#;7_E]f/%FS]", url="https://wikipedia.org")
    kp.save()


def test_db(path):
    kp = _new(path, "test123")
    work = kp.add_group(kp.root_group, "Work")
    dev = kp.add_group(work, "Dev")
    email = kp.add_group(kp.root_group, "Email")
    dup = kp.add_group(email, "Dev")  # same name as Work/Dev on purpose
    gh = kp.add_entry(dev, "GitHub", "me", "gh-secret", url="github.com", notes="2FA on")
    kp.add_entry(dup, "Mail dev", "dev@x", "m-secret")
    kp.add_entry(kp.root_group, "Root entry", "root", "r-secret")
    kp.add_entry(work, "Ref entry", "ref", "{REF:P@I:%s}" % gh.uuid.hex.upper())
    for i in range(2000):
        kp.add_entry(email, f"Bulk {i:04}", f"user{i}", f"pw{i}")
    kp.trash_entry(kp.add_entry(work, "Old thing", "old", "old-pw"))
    kp.save()


def complete(path):
    kp = _new(path, "pw")
    for i in range(5):
        kp.add_entry(kp.root_group, f"Personal {i}", "me@gmail.com", f"p{i}")
    for i in range(3):
        kp.add_entry(kp.root_group, f"Work {i}", "work@company.com", f"w{i}")
    kp.add_entry(kp.root_group, "Old", "oldname", "o")
    kp.save()


BUILDERS = {"rt41.kdbx": rt41, "big41.kdbx": big41, "foldericons41.kdbx": foldericons41, "dnd41.kdbx": dnd41,
            "test.kdbx": test_db, "complete.kdbx": complete}


def build(folder):
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    for name, builder in BUILDERS.items():
        if not (folder / name).exists():
            builder(folder / name)


if __name__ == "__main__":
    import sys
    build(sys.argv[1])
    for name in BUILDERS:
        print(name, PyKeePass(str(Path(sys.argv[1]) / name),
                              password={"test.kdbx": "test123", "complete.kdbx": "pw"}.get(name, PW)).version)
