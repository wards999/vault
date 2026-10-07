"""Password and passphrase generation (using `secrets`) and strength estimates."""
import math
import secrets
import string
import sys
from pathlib import Path

UPPER = string.ascii_uppercase
LOWER = string.ascii_lowercase
DIGITS = string.digits
SYMBOLS = "!@#$%^&*()-_=+[]{};:,.<>/?~"
LOOK_ALIKES = set("Il1|O0o`'\"")

_RESOURCES = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
_words = None


def words():
    """The EFF large wordlist (7,776 words)."""
    global _words
    if _words is None:
        text = (_RESOURCES / "wordlists" / "eff_large_wordlist.txt").read_text(encoding="utf-8")
        _words = [line.split("\t")[1].strip() for line in text.splitlines() if "\t" in line]
    return _words


def char_pools(upper=True, lower=True, digits=True, symbols=True, avoid_look_alikes=False):
    pools = [p for p, on in ((UPPER, upper), (LOWER, lower), (DIGITS, digits), (SYMBOLS, symbols)) if on]
    if avoid_look_alikes:
        pools = ["".join(c for c in p if c not in LOOK_ALIKES) for p in pools]
    return [p for p in pools if p]


def generate_password(length=20, **options):
    """Random password using every selected character type at least once.

    Returns (password, entropy_bits)."""
    pools = char_pools(**options) or [LOWER]
    length = max(length, len(pools))
    alphabet = "".join(pools)
    while True:
        password = "".join(secrets.choice(alphabet) for _ in range(length))
        if all(any(c in pool for c in password) for pool in pools):
            return password, length * math.log2(len(alphabet))


def generate_passphrase(word_count=5, separator="-", capitalize=True, add_number=False):
    """Diceware-style passphrase. Returns (passphrase, entropy_bits)."""
    wordlist = words()
    chosen = [secrets.choice(wordlist) for _ in range(word_count)]
    if capitalize:
        chosen = [w.capitalize() for w in chosen]
    bits = word_count * math.log2(len(wordlist))
    if add_number:
        i = secrets.randbelow(len(chosen))
        chosen[i] += str(secrets.randbelow(10))
        bits += math.log2(10) + math.log2(word_count)
    return separator.join(chosen), bits


def estimate_bits(password):
    """Strength of a typed password in bits, using zxcvbn (as KeePassXC does), which spots
    dictionary words, l33t substitutions, keyboard patterns, dates and so on.
    Generated passwords use their exact entropy instead."""
    if not password:
        return 0.0
    try:
        from zxcvbn import zxcvbn
        return zxcvbn(password[:100])["guesses_log10"] * math.log2(10)
    except ImportError:
        return _naive_bits(password)


def _naive_bits(password):
    """Fallback: length x log2(size of the character types used), penalising repeats."""
    pool = 0
    pool += 26 if any(c in LOWER for c in password) else 0
    pool += 26 if any(c in UPPER for c in password) else 0
    pool += 10 if any(c in DIGITS for c in password) else 0
    pool += 33 if any(not c.isalnum() for c in password) else 0
    pool += 100 if any(ord(c) > 127 for c in password) else 0
    unique_ratio = len(set(password)) / len(password)
    return len(password) * math.log2(max(pool, 2)) * (0.5 + 0.5 * unique_ratio)


def strength_label(bits):
    """(label, 0-100 score, level 0-3) for an entropy estimate."""
    if bits < 40:
        label, level = "Weak", 0
    elif bits < 64:
        label, level = "Fair", 1
    elif bits < 90:
        label, level = "Good", 2
    else:
        label, level = "Excellent", 3
    return label, min(100, int(bits / 128 * 100)), level
