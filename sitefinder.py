"""Guesses the website for an entry from its name (e.g. "British Gas login" -> britishgas.co.uk), for
entries that have no website address, so their site icon can be found. Every guess is shown to the
user to tick or correct before anything is changed (see FindIconsDialog in vault.py).

Only the guessed sites themselves are contacted (a name lookup, then their icon), as when fetching
icons for entries that do have a website.
"""
import re
import socket

import favicon

# Domain endings to try, most likely first, per country.
COUNTRIES = {
    "United Kingdom": ["co.uk", "com", "uk", "org.uk", "org", "net"],
    "Ireland": ["ie", "com", "co.uk", "org", "net"],
    "United States": ["com", "org", "net", "us", "io"],
    "Canada": ["ca", "com", "org", "net"],
    "Australia": ["com.au", "au", "com", "org.au", "net.au"],
    "New Zealand": ["co.nz", "nz", "com", "org.nz"],
    "Germany": ["de", "com", "org", "net"],
    "France": ["fr", "com", "org", "net"],
    "Netherlands": ["nl", "com", "org", "net"],
    "Spain": ["es", "com", "org", "net"],
    "Italy": ["it", "com", "org", "net"],
    "India": ["in", "co.in", "com", "org"],
    "Other / international": ["com", "org", "net", "io"],
}
DEFAULT_COUNTRY = "United Kingdom"

# Words that describe the login rather than name the site.
FILLER = {
    "login", "logon", "log", "signin", "sign", "in", "on", "account", "accounts", "acct", "online",
    "the", "my", "app", "apps", "website", "web", "site", "portal", "password", "pass", "pin", "user",
    "username", "old", "new", "main", "personal", "work", "home", "admin", "uk", "ltd", "limited",
    "plc", "inc", "co", "and", "of", "for", "www", "http", "https", "com",
}
MAX_NAMES = 4   # word combinations tried per entry
MAX_ENDINGS = 3  # domain endings tried per combination (the country's most likely ones)


def _words(title):
    title = re.sub(r"\(.*?\)|\[.*?\]", " ", title.lower())  # drop "(old)", "[work]" and the like
    title = title.replace("&", " and ")
    words = re.findall(r"[a-z0-9]+", title)
    kept = [w for w in words if w not in FILLER]
    return kept or words


def candidates(title, country=DEFAULT_COUNTRY):
    """Likely domains for an entry name, most likely first."""
    out = []
    host = favicon.site_host(title.strip()) if "." in title and " " not in title.strip() else None
    if host:  # the name already is a website ("amazon.co.uk")
        out.append(host[4:] if host.startswith("www.") else host)
    words = _words(title)
    if not words:
        return out
    names = ["".join(words)]
    if "&" in title:  # "Marks & Spencer" -> marksandspencer as well as marksspencer
        names.insert(0, "".join(w for w in re.findall(r"[a-z0-9]+", title.lower().replace("&", " and "))
                                if w == "and" or w not in FILLER))
    if len(words) > 1:
        names += ["-".join(words), "".join(words[:2]), words[0]]
    names = [n for n in dict.fromkeys(names) if len(n) >= 2][:MAX_NAMES]
    endings = COUNTRIES.get(country, COUNTRIES[DEFAULT_COUNTRY])[:MAX_ENDINGS]
    out += [f"{name}.{ending}" for name in names for ending in endings]
    return list(dict.fromkeys(out))


def _exists(domain):
    """The domain (or its www. name) has an address: worth asking for an icon."""
    for host in (domain, "www." + domain):
        try:
            socket.getaddrinfo(host, 443, proto=socket.IPPROTO_TCP)
            return True
        except (socket.gaierror, UnicodeError, OSError):
            continue
    return False


def find(title, country=DEFAULT_COUNTRY, allow_duckduckgo=False):
    """(domain, PNG bytes) for the first likely site that exists and has an icon, else (None, None)."""
    for domain in candidates(title, country):
        if not _exists(domain):
            continue
        png = favicon.fetch(domain, allow_duckduckgo)
        if png:
            return domain, png
    return None, None


def icon_for(domain, allow_duckduckgo=False):
    """Icon for a website the user typed (any form: "bbc.co.uk", "https://www.bbc.co.uk/news")."""
    host = favicon.site_host(domain)
    return (host, favicon.fetch(host, allow_duckduckgo)) if host else (None, None)
