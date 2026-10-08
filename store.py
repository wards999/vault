"""Opening, editing and safely saving KeePass databases (no Qt here, so it is easy to test).

Edits are recorded as operations (Op) and applied to the open PyKeePass object. Saving:

1. re-reads the file and checks it is unchanged since we last loaded or saved it; if another
   device or app changed it, the caller reloads it and re-applies the unsaved operations,
   asking the user about entries that were changed in both places (see apply_op);
2. backs up the current file (at most every BACKUP_INTERVAL, keeping MAX_BACKUPS per database);
3. encrypts to memory, re-opens that copy to verify it, then writes it next to the database
   and atomically replaces the original, so a crash can never leave a half-written file.

inverse_op() gives the operation that undoes another, for the app's undo.
"""
import base64
import copy
import hashlib
import io
import os
import time
import uuid as uuidlib
from dataclasses import dataclass, field as dc_field
from datetime import datetime, timezone
from pathlib import Path

from lxml import etree

import totp

# pykeepass (with its crypto and Argon2 libraries) takes a noticeable time to import, so it's
# imported on first use; the app preloads it in the background while the unlock screen shows.

FIELDS = ("title", "username", "password", "url", "notes", "otp")
MAX_BACKUPS = 10
BACKUP_INTERVAL = 10 * 60  # seconds
RECYCLE_BIN_ICON = "43"  # KeePass's trash-can icon
FOLDER_ICON = 48  # KeePass's standard folder icon (the default for groups)


def digest(data):
    return hashlib.sha256(data).hexdigest()


def b64_uuid(hex_uuid):
    return base64.b64encode(uuidlib.UUID(hex=hex_uuid).bytes).decode()


def icon_ref(element, default_id):
    """(standard icon number, custom icon UUID or None) for an entry or group.

    Custom icons are usually site favicons, e.g. downloaded by KeePassXC or Vault.
    """
    try:
        icon_id = int(element.icon or default_id)
    except (TypeError, ValueError):
        icon_id = default_id
    custom = element._element.findtext("CustomIconUUID")  # pykeepass has no API for custom icons
    return icon_id, (custom or None)


def open_kp(data, password, keyfile):
    from pykeepass import PyKeePass
    return PyKeePass(io.BytesIO(data), password=password or None, keyfile=keyfile or None)


# ---------------------------------------------------------------- reading fields

def string_fields(element):
    """All <String> fields of an entry element as {key: value}."""
    out = {}
    for s in element.findall("String"):
        out[s.findtext("Key") or ""] = s.findtext("Value") or ""
    return out


def get_otp(e):
    """The entry's 2FA setting as text: KeePassXC's `otp` field, else KeePass 2's TimeOtp secret."""
    fields = string_fields(e._element)
    if fields.get("otp"):
        return fields["otp"]
    return totp.keepass2_secret(fields) or ""


def password_changed(e):
    """When the current password was set: the oldest version in the latest run of history
    entries that have the same password."""
    password = e.password or ""
    changed = e.mtime
    history = e.history
    for older in reversed(history):
        if (older.password or "") != password:
            break
        changed = older.mtime
    else:
        changed = e.ctime or changed
    return changed


class Database:
    """An open KeePass file: the PyKeePass object plus a plain-data snapshot for the UI.

    The snapshot holds only plain data (icon images as PNG bytes), so it can be built on a
    background thread; Qt pixmaps are made later on the GUI thread.
    """

    def __init__(self, path, password, keyfile, data=None):
        self.path = str(path)
        data = Path(path).read_bytes() if data is None else data
        self.kp = open_kp(data, password, keyfile)
        self.digest = digest(data)  # what is on disk, as far as we know
        header = self.kp.kdbx.header.value
        self.version = f"{header.major_version}.{header.minor_version}"
        # pykeepass corrupts KDBX 3.x files when saving them (KeePass rejects the header hash),
        # so only KDBX 4.x databases may be edited.
        self.writable = header.major_version >= 4
        self.build_snapshot()

    def replace_kp(self, kp, data):
        self.kp = kp
        self.digest = digest(data)
        self.build_snapshot()

    def build_snapshot(self):
        kp = self.kp
        bin_group = kp.recyclebin_group
        self.bin_id = bin_group.uuid.hex if bin_group is not None else None
        self.name = kp.root_group.name or Path(self.path).stem
        self.folders = []  # dicts: id, name, parent (None = root), in_bin, path
        self.entries = []
        self.custom_icons = {}  # CustomIconUUID (base64 text) -> image bytes
        for ico in kp.tree.getroot().iterfind("Meta/CustomIcons/Icon"):
            icon_uuid, data = ico.findtext("UUID"), ico.findtext("Data")
            if icon_uuid and data:
                try:
                    self.custom_icons[icon_uuid] = base64.b64decode(data)
                except ValueError:
                    pass

        def walk(group, ids, names, in_bin):
            for e in group.entries:
                self.entries.append(entry_snapshot(e, ids, names, in_bin))
            for sub in group.subgroups:
                sub_id = sub.uuid.hex
                sub_bin = in_bin or sub_id == self.bin_id
                name = sub.name or "(unnamed)"
                self.folders.append(dict(id=sub_id, name=name, parent=ids[-1] if ids else None,
                                         in_bin=sub_bin, path=names + (name,),
                                         icon=icon_ref(sub, FOLDER_ICON)))
                walk(sub, ids + (sub_id,), names + (name,), sub_bin)

        walk(kp.root_group, (), (), False)
        self.entries.sort(key=lambda e: e["title"].lower())

    @property
    def recycle_bin_enabled(self):
        return self.kp.tree.getroot().findtext("Meta/RecycleBinEnabled") != "False"


_XML_KEYS = {"title": "Title", "username": "UserName", "password": "Password", "url": "URL", "notes": "Notes"}


def entry_snapshot(e, ids, names, in_bin):
    """Plain-data view of an entry. Reads the entry's XML directly: pykeepass's properties run an
    XPath search per field, which made unlocking large databases noticeably slower."""
    el = e._element
    kp = e._kp
    fields = string_fields(el)
    raw = {name: fields.get(key) or "" for name, key in _XML_KEYS.items()}
    otp = fields.get("otp") or totp.keepass2_secret(fields) or ""
    raw["otp"] = otp

    def resolved(name):
        value = raw[name]
        if "{REF:" in value:  # field references are rare; let pykeepass resolve them
            try:
                value = e.deref(name)
            except Exception:
                pass
        return value if isinstance(value, str) else ""

    times = el.find("Times")

    def when(tag, element_times=times):
        node = element_times.find(tag) if element_times is not None else None
        return kp._decode_time(node.text) if node is not None and node.text else None

    mtime_utc = when("LastModificationTime")
    mtime = mtime_utc.astimezone() if mtime_utc else None
    expires = times is not None and times.findtext("Expires") == "True"
    expiry = when("ExpiryTime") if expires else None

    # When the current password was set: the oldest version in the latest run of history
    # entries with the same password (no history: when the entry was created).
    changed = mtime_utc
    history = el.find("History")
    for old in reversed(history.findall("Entry") if history is not None else []):
        if (string_fields(old).get("Password") or "") != raw["password"]:
            break
        changed = when("LastModificationTime", old.find("Times"))
    else:
        changed = when("CreationTime") or changed

    try:
        icon_id = int(el.findtext("IconID") or 0)
    except ValueError:
        icon_id = 0
    entry = dict(
        uuid=uuidlib.UUID(bytes=base64.b64decode(el.findtext("UUID"))).hex,
        title=resolved("title") or "(untitled)", username=resolved("username"),
        password=resolved("password"), url=resolved("url"), notes=resolved("notes"),
        raw=raw,  # unresolved values, for editing
        totp=totp.params(otp, fields),
        base_mtime=mtime_utc,  # to detect edits made elsewhere while we edit
        password_changed=changed,
        modified=mtime.strftime("%b %d, %Y %H:%M") if mtime else "",
        modified_key=mtime.isoformat() if mtime else "",
        expires=expiry,
        expired=bool(expires and expiry and datetime.now(timezone.utc) > expiry),
        folder_ids=ids, path=names, in_bin=in_bin, folder_id=ids[-1] if ids else None,
        icon=(icon_id, el.findtext("CustomIconUUID") or None), folder=" › ".join(names) or "Root",
    )
    entry["search"] = "\n".join(entry[k] for k in ("title", "username", "url", "notes")).lower()
    return entry


# ---------------------------------------------------------------- operations

@dataclass
class Op:
    """One change to the database.

    Entries:  "create", "update", "trash" (to the Recycle Bin), "delete" (permanent),
              "move" (to `folder`), "insert" (restore/duplicate from `element`), "set_icon".
    Folders:  "folder_create", "folder_rename", "folder_trash", "folder_delete",
              "folder_move" (to parent `folder`), "folder_insert".
    """
    kind: str
    uuid: str
    fields: dict = dc_field(default_factory=dict)  # changed fields (entries) or {"name": ...} (folders)
    all_fields: dict = dc_field(default_factory=dict)  # every field after the edit (to re-create it)
    folder: object = False  # destination / parent folder id (None = root); False = don't move
    base_mtime: object = None  # entry's modified time when the user started the edit
    title: str = ""  # for messages
    element: bytes = None  # serialized XML for "insert" / "folder_insert"
    icon: object = None  # "set_icon": PNG bytes (new image), str (existing icon UUID) or "" (none)
    icon_name: str = ""  # e.g. the site's domain, stored with new icons in KDBX 4.1


@dataclass
class Conflict:
    op: Op
    reason: str  # "changed" or "deleted"


def _find_entry(kp, entry_uuid):
    return kp.find_entries(uuid=uuidlib.UUID(hex=entry_uuid), first=True)


def _find_group(kp, group_id):
    if group_id is None:
        return kp.root_group
    return kp.find_groups(uuid=uuidlib.UUID(hex=group_id), first=True)


def _group_or_root(kp, group_id):
    return _find_group(kp, group_id) or kp.root_group


def _folder_id(kp, group):
    return None if group is None or group.uuid == kp.root_group.uuid else group.uuid.hex


def _recycle_bin(kp):
    return kp._create_or_get_recyclebin_group(icon=RECYCLE_BIN_ICON)


def _history_limit(kp):
    try:
        return int(kp.tree.getroot().findtext("Meta/HistoryMaxItems") or 10)
    except ValueError:
        return 10


def _prune_history(kp, entry):
    limit = _history_limit(kp)
    if limit < 0:
        return
    history = entry.history  # oldest first
    for old in history[:max(0, len(history) - limit)]:
        entry.delete_history(old)


def _remove_string(element, key):
    for s in element.findall("String"):
        if s.findtext("Key") == key:
            element.remove(s)


def _set_otp(entry, value):
    """Stores a 2FA secret or otpauth:// link in both KeePassXC's and KeePass 2's formats."""
    element = entry._element
    for key in ("otp", *totp.KEEPASS2_KEYS):
        _remove_string(element, key)
    value = (value or "").strip()
    if not value:
        return
    uri = totp.to_uri(value, issuer=entry.title or "", account=entry.username or "")
    entry._set_string_field("otp", uri, True)
    for key, field_value in totp.keepass2_fields(uri).items():
        entry._set_string_field(key, field_value, key == "TimeOtp-Secret-Base32")


def _ensure_custom_icons(kp):
    meta = kp.tree.getroot().find("Meta")
    icons = meta.find("CustomIcons")
    if icons is None:
        icons = etree.SubElement(meta, "CustomIcons")
    return icons


def _icon_uuid_for(kp, data, name):
    """UUID (base64) of a custom icon with these image bytes, adding the icon if needed."""
    encoded = base64.b64encode(data).decode()
    icons = _ensure_custom_icons(kp)
    for ico in icons.findall("Icon"):
        if ico.findtext("Data") == encoded:
            return ico.findtext("UUID")
    new = etree.SubElement(icons, "Icon")
    etree.SubElement(new, "UUID").text = base64.b64encode(uuidlib.uuid4().bytes).decode()
    etree.SubElement(new, "Data").text = encoded
    if name and kp.kdbx.header.value.minor_version >= 1:  # icon names are a KDBX 4.1 feature
        etree.SubElement(new, "Name").text = name
    return new.findtext("UUID")


def _set_custom_icon(entry_element, icon_uuid):
    current = entry_element.find("CustomIconUUID")
    if not icon_uuid:
        if current is not None:
            entry_element.remove(current)
        return
    if current is None:
        current = etree.Element("CustomIconUUID")
        icon_id = entry_element.find("IconID")  # keep KeePass's element order: after IconID
        if icon_id is not None:
            icon_id.addnext(current)
        else:
            entry_element.append(current)
    current.text = icon_uuid


def apply_op(kp, op, force=False):
    """Applies `op` to `kp`. Returns a Conflict instead if the entry was changed or deleted
    elsewhere since the user started editing it (unless `force`)."""
    kind = op.kind
    if kind.startswith("folder_"):
        _apply_folder_op(kp, op)
        return None

    entry = None if kind in ("create", "insert") else _find_entry(kp, op.uuid)

    if kind == "create" or (entry is None and force and kind == "update"):
        source = op.all_fields or op.fields
        values = {f: source.get(f, "") for f in FIELDS}
        folder = None if op.folder is False else op.folder
        new = kp.add_entry(_group_or_root(kp, folder), values["title"], values["username"], values["password"],
                           url=values["url"] or None, notes=values["notes"] or None, force_creation=True)
        new.uuid = uuidlib.UUID(hex=op.uuid)
        if values["otp"]:
            _set_otp(new, values["otp"])
        return None

    if kind == "insert":
        if _find_entry(kp, op.uuid) is None:
            _group_or_root(kp, None if op.folder is False else op.folder)._element.append(
                etree.fromstring(op.element))
        return None

    if entry is None:
        return None if kind in ("trash", "delete", "move", "set_icon") else Conflict(op, "deleted")

    if kind == "update":
        if not force and op.base_mtime is not None and entry.mtime != op.base_mtime:
            return Conflict(op, "changed")
        entry.save_history()  # keep the previous version, as KeePass does
        for name, value in op.fields.items():
            if name == "otp":
                _set_otp(entry, value)
            else:
                setattr(entry, name, value)
        if op.folder is not False:
            target = _group_or_root(kp, op.folder)
            if entry.group.uuid != target.uuid:
                kp.move_entry(entry, target)
        entry.touch(modify=True)
        _prune_history(kp, entry)
    elif kind == "trash":
        kp.move_entry(entry, _recycle_bin(kp))
    elif kind == "delete":
        kp.delete_entry(entry)
    elif kind == "move":
        target = _group_or_root(kp, None if op.folder is False else op.folder)
        if entry.group.uuid != target.uuid:
            kp.move_entry(entry, target)
    elif kind == "set_icon":
        if isinstance(op.icon, (bytes, bytearray)):
            icon_uuid = _icon_uuid_for(kp, bytes(op.icon), op.icon_name)
        else:
            icon_uuid = op.icon or ""
        _set_custom_icon(entry._element, icon_uuid)
    return None


def _apply_folder_op(kp, op):
    kind = op.kind
    if kind == "folder_create":
        if _find_group(kp, op.uuid) is None:
            parent = _group_or_root(kp, None if op.folder is False else op.folder)
            group = kp.add_group(parent, op.fields.get("name") or "New folder")
            group.uuid = uuidlib.UUID(hex=op.uuid)
        return
    if kind == "folder_insert":
        if _find_group(kp, op.uuid) is None:
            _group_or_root(kp, None if op.folder is False else op.folder)._element.append(
                etree.fromstring(op.element))
        return
    group = _find_group(kp, op.uuid)
    if group is None or group.uuid == kp.root_group.uuid:
        return
    if kind == "folder_rename":
        group.name = op.fields.get("name") or group.name
        group.touch(modify=True)
    elif kind == "folder_trash":
        kp.move_group(group, _recycle_bin(kp))
    elif kind == "folder_delete":
        kp.delete_group(group)
    elif kind == "folder_move":
        target = _group_or_root(kp, None if op.folder is False else op.folder)
        ancestor = target  # can't move a folder into itself or one of its subfolders
        while ancestor is not None and ancestor.uuid != group.uuid:
            ancestor = ancestor.parentgroup
        if ancestor is None:
            kp.move_group(group, target)


def inverse_op(kp, op):
    """The operation that undoes `op`; call it *before* applying `op`. None if not undoable."""
    kind = op.kind
    if kind == "create":
        return Op("delete", op.uuid, title=op.title)
    if kind == "insert":
        return Op("delete", op.uuid, title=op.title)
    if kind == "folder_create":
        return Op("folder_delete", op.uuid, title=op.title)
    if kind == "folder_insert":
        return Op("folder_delete", op.uuid, title=op.title)

    if kind.startswith("folder_"):
        group = _find_group(kp, op.uuid)
        if group is None:
            return None
        parent = _folder_id(kp, group.parentgroup)
        if kind == "folder_rename":
            return Op("folder_rename", op.uuid, fields={"name": group.name or ""}, title=op.title)
        if kind in ("folder_trash", "folder_move"):
            return Op("folder_move", op.uuid, folder=parent, title=op.title)
        if kind == "folder_delete":
            return Op("folder_insert", op.uuid, folder=parent, title=op.title,
                      element=etree.tostring(group._element))
        return None

    entry = _find_entry(kp, op.uuid)
    if entry is None:
        return None
    folder = _folder_id(kp, entry.group)
    if kind == "update":
        old = {name: (get_otp(entry) if name == "otp" else getattr(entry, name) or "") for name in op.fields}
        return Op("update", op.uuid, fields=old, folder=folder, title=op.title)
    if kind in ("trash", "move"):
        return Op("move", op.uuid, folder=folder, title=op.title)
    if kind == "delete":
        return Op("insert", op.uuid, folder=folder, title=op.title, element=etree.tostring(entry._element))
    if kind == "set_icon":
        return Op("set_icon", op.uuid, icon=entry._element.findtext("CustomIconUUID") or "", title=op.title)
    return None


def duplicate_op(kp, entry_uuid, suffix=" - Copy"):
    """An "insert" Op creating a full copy of an entry (fields, icon, attachments; no history)."""
    entry = _find_entry(kp, entry_uuid)
    element = copy.deepcopy(entry._element)
    history = element.find("History")
    if history is not None:
        element.remove(history)
    new_uuid = uuidlib.uuid4().hex
    element.find("UUID").text = b64_uuid(new_uuid)
    title = (entry.title or "") + suffix
    for s in element.findall("String"):
        if s.findtext("Key") == "Title":
            s.find("Value").text = title
    return Op("insert", new_uuid, folder=_folder_id(kp, entry.group), title=title,
              element=etree.tostring(element))


def keep_both_op(op):
    """For a conflict: save the user's version as a separate copy instead."""
    fields = dict(op.all_fields or op.fields)
    fields["title"] = (fields.get("title") or op.title or "Entry") + " (my copy)"
    return Op("create", uuidlib.uuid4().hex, fields=fields, all_fields=fields, folder=op.folder,
              title=fields["title"])


# ---------------------------------------------------------------- saving

class FileChanged(Exception):
    """The database file was changed by someone else; `data` is its current contents."""

    def __init__(self, data):
        super().__init__("The database was changed by another app or device.")
        self.data = data


def backup_dir():
    """Where backups go: next to Vault.exe for the portable Windows build, in Application Support
    on macOS (never inside Vault.app, which would break its signature), else the project folder."""
    import sys
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "Vault" / "backups"
    base = Path(sys.executable).parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parent
    return base / "backups"


def make_backup(path, data, directory=None, keep=MAX_BACKUPS):
    """Writes `data` (the encrypted file as it was on disk) to the backups folder and keeps
    only the newest `keep` backups of this database. Returns the backup path."""
    path = Path(path)
    directory = Path(directory) if directory else backup_dir()
    directory.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y-%m-%d %H-%M-%S")
    target = directory / f"{path.stem} {stamp}{path.suffix}"
    target.write_bytes(data)
    pattern = f"{path.stem} ????-??-?? ??-??-??{path.suffix}"
    backups = sorted(directory.glob(pattern), key=lambda p: p.name)
    for old in backups[:-keep]:
        old.unlink(missing_ok=True)
    return target


def save_database(kp, path, expected_digest, backup=False, backup_directory=None):
    """Safely writes `kp` to `path`. Raises FileChanged if the file isn't what we expect.

    Returns the digest of the newly written file. Runs on a background thread.
    """
    path = Path(path)
    current = path.read_bytes()
    if digest(current) != expected_digest:
        raise FileChanged(current)
    if backup:
        make_backup(path, current, backup_directory)

    buffer = io.BytesIO()
    kp.save(buffer)  # encrypt to memory first
    new_data = buffer.getvalue()

    # Verify: the new bytes must decrypt with the same credentials and hold the same entries.
    check = open_kp(new_data, kp.password, kp.keyfile)
    if {e.uuid for e in check.entries} != {e.uuid for e in kp.entries}:
        raise RuntimeError("Verification of the saved database failed; nothing was written.")

    # Last-moment check that nobody wrote the file while we were encrypting.
    if digest(path.read_bytes()) != expected_digest:
        raise FileChanged(path.read_bytes())

    tmp = path.with_name(f".{path.name}.vault-tmp")
    try:
        with open(tmp, "wb") as f:
            f.write(new_data)
            f.flush()
            os.fsync(f.fileno())
        for attempt in range(10):  # the file may be briefly locked by a sync client
            try:
                os.replace(tmp, path)
                break
            except PermissionError:
                if attempt == 9:
                    raise
                time.sleep(0.3)
    finally:
        if tmp.exists():
            tmp.unlink(missing_ok=True)
    return digest(new_data)
