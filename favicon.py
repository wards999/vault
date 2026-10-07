"""Downloads a website's icon (favicon) as a small PNG, directly from the site.

Tries the icons the site's home page declares (<link rel="icon" ...>), then /favicon.ico, and
only if allowed, DuckDuckGo's icon service as a last resort. Safe to call from worker threads
(QImage, unlike QPixmap, may be used off the GUI thread).
"""
import re
import ssl
import urllib.request
from html.parser import HTMLParser
from urllib.parse import urljoin, urlparse

from PySide6.QtCore import QBuffer, QByteArray, QIODevice, Qt
from PySide6.QtGui import QImage

ICON_SIZE = 64
TIMEOUT = 6
MAX_BYTES = 1_000_000
USER_AGENT = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/128.0 Safari/537.36")


def site_host(url):
    """Host name for an entry's website field, or None (e.g. "github.com/login" -> "github.com")."""
    url = (url or "").strip()
    if not url or url.startswith(("{", "cmd://", "file:", "kdbx:")):
        return None
    if "://" not in url:
        url = "https://" + url
    host = urlparse(url).hostname
    if not host or "." not in host or host.replace(".", "").isdigit():
        return None
    return host.lower()


def _ssl_context():
    # A bundled Python on macOS can't see the system's certificates, so use certifi's list when available.
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        return ssl.create_default_context()


_SSL = None


def _get(url, accept="*/*"):
    global _SSL
    if _SSL is None:
        _SSL = _ssl_context()
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": accept})
    with urllib.request.urlopen(request, timeout=TIMEOUT, context=_SSL) as response:
        return response.read(MAX_BYTES), response.geturl()


class _IconLinks(HTMLParser):
    def __init__(self):
        super().__init__()
        self.links = []  # (score, href)

    def handle_starttag(self, tag, attrs):
        if tag != "link":
            return
        a = dict(attrs)
        rel = (a.get("rel") or "").lower()
        href = a.get("href")
        if not href or "icon" not in rel or "mask-icon" in rel:
            return
        size = 0
        match = re.search(r"(\d+)x\d+", a.get("sizes") or "")
        if match:
            size = int(match.group(1))
        elif "apple-touch-icon" in rel:
            size = 180
        elif href.lower().endswith(".svg") or "svg" in (a.get("type") or ""):
            size = 128
        # prefer icons near our size; tiny or huge ones score lower
        score = -abs(min(size, 256) - ICON_SIZE * 2) if size else -1000
        self.links.append((score, href))


def _to_png(data):
    image = QImage.fromData(QByteArray(data))
    if image.isNull() or image.width() < 8:
        return None
    if image.width() != ICON_SIZE or image.height() != ICON_SIZE:
        image = image.scaled(ICON_SIZE, ICON_SIZE, Qt.KeepAspectRatio, Qt.SmoothTransformation)
    out = QByteArray()
    buffer = QBuffer(out)
    buffer.open(QIODevice.WriteOnly)
    image.save(buffer, "PNG")
    return bytes(out)


def fetch(url, allow_duckduckgo=False):
    """PNG bytes of the site's icon, or None if none could be found."""
    host = site_host(url)
    if not host:
        return None
    hosts = [host]
    if host.count(".") > 1 and not host.startswith("www."):
        hosts.append(".".join(host.split(".")[-2:]))  # e.g. accounts.google.com -> google.com
    for h in hosts:
        candidates = []
        try:
            html, final_url = _get(f"https://{h}/", "text/html")
            parser = _IconLinks()
            parser.feed(html.decode("utf-8", "replace"))
            candidates = [urljoin(final_url, href) for _, href in sorted(parser.links, reverse=True)]
        except Exception:
            final_url = f"https://{h}/"
        candidates.append(urljoin(final_url, "/favicon.ico"))
        for candidate in candidates[:6]:
            try:
                png = _to_png(_get(candidate, "image/*")[0])
            except Exception:
                continue
            if png:
                return png
    if allow_duckduckgo:
        try:
            return _to_png(_get(f"https://icons.duckduckgo.com/ip3/{host}.ico", "image/*")[0])
        except Exception:
            return None
    return None
