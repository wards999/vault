"""Password health report: weak, reused, old, expired and empty passwords.

Works on the plain-data entry snapshot (store.entry_snapshot), so it can run on a worker thread.
"""
from collections import defaultdict
from datetime import datetime, timezone

import generator

WEAK_BITS = 50  # below this (zxcvbn estimate) a password counts as weak
OLD_DAYS = 365

ISSUES = {  # issue -> (label, order)
    "weak": ("Weak password", 0),
    "reused": ("Reused password", 1),
    "empty": ("No password", 2),
    "expired": ("Expired", 3),
    "old": ("Not changed in over a year", 4),
}


def _age_text(days):
    if days >= 730:
        return f"{days // 365} years ago"
    if days >= 365:
        return "over a year ago"
    return f"{days} days ago"


def report(entries, now=None, strength_cache=None, strength=True):
    """List of issue dicts: {issue, entry, detail, sort} for entries outside the Recycle Bin and
    Backup folders (old copies there would just show up as "reused" alongside the live entry).
    strength_cache: {password: bits} kept between checks, so unchanged passwords aren't measured again.
    strength=False skips the "weak" check: the rest are quick comparisons, while measuring strength
    loads zxcvbn's word lists (about 20 MB)."""
    now = now or datetime.now(timezone.utc)
    live = [e for e in entries if not e["in_bin"] and not e["backup"]]
    by_password = defaultdict(list)
    for e in live:
        if e["password"]:
            by_password[e["password"]].append(e)

    issues = []
    strength_cache = {} if strength_cache is None else strength_cache
    for e in live:
        password = e["password"]
        if not password:
            if not e.get("note"):  # a secure note has no password to begin with
                issues.append(dict(issue="empty", entry=e, detail="", sort=0))
            continue
        if strength and password not in strength_cache:
            strength_cache[password] = generator.estimate_bits(password)
        bits = strength_cache.get(password, WEAK_BITS) if strength else WEAK_BITS
        if bits < WEAK_BITS:
            label = generator.strength_label(bits)[0]
            issues.append(dict(issue="weak", entry=e, detail=f"{label} · ~{int(bits)} bits", sort=bits))
        others = by_password[password]
        if len(others) > 1:
            names = ", ".join(o["title"] for o in others if o is not e)[:120]
            issues.append(dict(issue="reused", entry=e, detail=f"Same as {names}", sort=-len(others)))
        if e["expired"]:
            issues.append(dict(issue="expired", entry=e, detail=f"Expired {e['expires']:%b %d, %Y}"
                               if e.get("expires") else "", sort=0))
        changed = e.get("password_changed")
        if changed is not None:
            days = (now - changed).days
            if days > OLD_DAYS:
                issues.append(dict(issue="old", entry=e, detail=f"Last changed {_age_text(days)}", sort=-days))
    issues.sort(key=lambda i: (ISSUES[i["issue"]][1], i["sort"], i["entry"]["title"].lower()))
    return issues


def summary(issues):
    counts = {k: 0 for k in ISSUES}
    for i in issues:
        counts[i["issue"]] += 1
    return counts
