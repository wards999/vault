"""Time-based 2FA codes (TOTP) for entries, in the formats KeePassXC and KeePass 2 use.

KeePassXC stores an `otpauth://totp/...` link in the entry's `otp` field. KeePass 2 (2.47+)
uses `TimeOtp-Secret-Base32` (or -Hex, -Base64, plain), plus optional `TimeOtp-Length`,
`TimeOtp-Period` and `TimeOtp-Algorithm` fields. Vault reads both and writes both.
"""
import base64
import binascii
import hashlib
import time
from urllib.parse import parse_qs, quote, urlparse

import pyotp

KEEPASS2_KEYS = ("TimeOtp-Secret", "TimeOtp-Secret-Hex", "TimeOtp-Secret-Base32", "TimeOtp-Secret-Base64",
                 "TimeOtp-Length", "TimeOtp-Period", "TimeOtp-Algorithm")
ALGORITHMS = {"SHA1": hashlib.sha1, "SHA256": hashlib.sha256, "SHA512": hashlib.sha512}
KEEPASS2_ALGORITHMS = {"HMAC-SHA-1": "SHA1", "HMAC-SHA-256": "SHA256", "HMAC-SHA-512": "SHA512"}


def _clean_base32(secret):
    secret = secret.replace(" ", "").replace("-", "").upper().rstrip("=")
    base64.b32decode(secret + "=" * (-len(secret) % 8))  # raises if invalid
    return secret


def keepass2_secret(fields):
    """KeePass 2's TimeOtp secret as Base32, or None."""
    try:
        if fields.get("TimeOtp-Secret-Base32"):
            return _clean_base32(fields["TimeOtp-Secret-Base32"])
        if fields.get("TimeOtp-Secret-Hex"):
            raw = binascii.unhexlify(fields["TimeOtp-Secret-Hex"].replace(" ", ""))
        elif fields.get("TimeOtp-Secret-Base64"):
            raw = base64.b64decode(fields["TimeOtp-Secret-Base64"])
        elif fields.get("TimeOtp-Secret"):
            raw = fields["TimeOtp-Secret"].encode("utf-8")
        else:
            return None
        return base64.b32encode(raw).decode().rstrip("=")
    except (ValueError, binascii.Error):
        return None


def params(otp_text, fields=None):
    """{secret, digits, period, algorithm} for an entry, or None if it has no (valid) 2FA."""
    fields = fields or {}
    otp_text = (otp_text or "").strip()
    try:
        if otp_text.startswith("otpauth://"):
            url = urlparse(otp_text)
            if url.netloc.lower() != "totp":
                return None
            q = {k: v[0] for k, v in parse_qs(url.query).items()}
            return dict(secret=_clean_base32(q["secret"]), digits=int(q.get("digits", 6)),
                        period=int(q.get("period", 30)), algorithm=q.get("algorithm", "SHA1").upper())
        if otp_text:  # a bare secret in the otp field
            return dict(secret=_clean_base32(otp_text), digits=6, period=30, algorithm="SHA1")
        secret = keepass2_secret(fields)
        if secret:
            return dict(secret=secret, digits=int(fields.get("TimeOtp-Length") or 6),
                        period=int(fields.get("TimeOtp-Period") or 30),
                        algorithm=KEEPASS2_ALGORITHMS.get(fields.get("TimeOtp-Algorithm", ""), "SHA1"))
    except (KeyError, ValueError, binascii.Error):
        return None
    return None


def code(p, now=None):
    """(current code, seconds until it changes)."""
    now = time.time() if now is None else now
    generator = pyotp.TOTP(p["secret"], digits=p["digits"], interval=p["period"],
                           digest=ALGORITHMS.get(p["algorithm"], hashlib.sha1))
    return generator.at(now), p["period"] - int(now) % p["period"]


def validate(value):
    """Error message for a 2FA secret / otpauth link typed by the user, or None if it's fine."""
    value = (value or "").strip()
    if not value:
        return None
    if value.startswith("otpauth://") and urlparse(value).netloc.lower() == "hotp":
        return "Counter-based (HOTP) codes aren't supported, only time-based (TOTP)."
    return None if params(value) else "That doesn't look like a valid 2FA secret or otpauth:// link."


def to_uri(value, issuer="", account=""):
    """Normalises a secret or otpauth:// link to an otpauth://totp link (KeePassXC's format)."""
    value = value.strip()
    if value.startswith("otpauth://"):
        return value
    p = params(value)
    label = quote(f"{issuer}:{account}" if account else issuer or "Vault")
    return f"otpauth://totp/{label}?secret={p['secret']}&period=30&digits=6&issuer={quote(issuer)}"


def keepass2_fields(uri):
    """KeePass 2's TimeOtp-* fields for an otpauth link (non-default settings only)."""
    p = params(uri)
    if not p:
        return {}
    out = {"TimeOtp-Secret-Base32": p["secret"]}
    if p["digits"] != 6:
        out["TimeOtp-Length"] = str(p["digits"])
    if p["period"] != 30:
        out["TimeOtp-Period"] = str(p["period"])
    if p["algorithm"] != "SHA1":
        out["TimeOtp-Algorithm"] = {v: k for k, v in KEEPASS2_ALGORITHMS.items()}[p["algorithm"]]
    return out
