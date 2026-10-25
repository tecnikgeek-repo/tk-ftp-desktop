"""Voci di elenco (locali e remote) e lettura delle risposte LIST / MLSD dei server FTP."""
import calendar
import datetime
import os
import re
import stat
from dataclasses import dataclass

TEXT_EXT = {
    "html", "htm", "php", "phtml", "css", "scss", "less", "js", "mjs", "cjs", "ts", "jsx", "tsx", "json", "xml", "svg",
    "txt", "md", "markdown", "ini", "conf", "cfg", "env", "htaccess", "htpasswd", "sql", "csv", "tsv", "log", "yml",
    "yaml", "toml", "properties", "sh", "bash", "py", "java", "kt", "rb", "go", "c", "cpp", "h", "vue", "twig",
    "tpl", "phps", "inc", "lock", "map", "po", "pot", "bat", "cmd", "ps1", "user.ini",
}
IMAGE_EXT = {"jpg", "jpeg", "png", "gif", "webp", "bmp", "ico", "tif", "tiff", "avif", "heic"}
ARCHIVE_EXT = {"zip", "gz", "tgz", "tar", "rar", "7z", "bz2", "xz", "wpress"}
DOC_EXT = {"pdf", "doc", "docx", "xls", "xlsx", "ppt", "pptx", "odt", "ods", "rtf"}
MEDIA_EXT = {"mp3", "mp4", "mov", "avi", "mkv", "wav", "ogg", "webm", "m4a", "flac"}
CODE_EXT = {"php", "js", "mjs", "ts", "jsx", "tsx", "py", "css", "scss", "less", "html", "htm", "vue", "sh", "sql",
            "json", "xml", "twig", "java", "kt", "go", "rb", "c", "cpp", "h"}


@dataclass
class Entry:
    name: str
    is_dir: bool = False
    size: int = 0
    mtime: float = 0.0          # secondi epoch (0 = sconosciuta)
    perms: str = ""             # «rwxr-xr-x» (senza il tipo)
    owner: str = ""
    is_link: bool = False
    link_target: str = ""

    @property
    def ext(self):
        n = self.name.lower()
        if n.startswith(".") and n.count(".") == 1:
            return n[1:]
        return n.rsplit(".", 1)[1] if "." in n else ""

    @property
    def kind(self):
        """Categoria per l'icona: dir, code, text, image, archive, doc, media, file."""
        if self.is_dir:
            return "dir"
        e = self.ext
        if e in CODE_EXT:
            return "code"
        if e in TEXT_EXT:
            return "text"
        if e in IMAGE_EXT:
            return "image"
        if e in ARCHIVE_EXT:
            return "archive"
        if e in DOC_EXT:
            return "doc"
        if e in MEDIA_EXT:
            return "media"
        return "file"

    @property
    def type_label(self):
        if self.is_dir:
            return "Cartella" + (" (collegamento)" if self.is_link else "")
        e = self.ext
        return f"File {e.upper()}" if e else "File"

    @property
    def octal(self):
        return perms_to_octal(self.perms)


def perms_to_octal(perms):
    p = (perms or "")[-9:]
    if len(p) != 9:
        return ""
    v = 0
    for i, ch in enumerate(p):
        if ch in "rwx" or (i % 3 == 2 and ch in "st"):  # s/t minuscole = anche eseguibile; S/T = no
            v |= 1 << (8 - i)
    return f"{v:03o}"


def octal_to_perms(octal):
    v = int(octal, 8)
    out = ""
    for i in range(9):
        out += "rwx"[i % 3] if v & (1 << (8 - i)) else "-"
    return out


def local_entries(folder, show_hidden=False):
    out = []
    with os.scandir(folder) as it:
        for d in it:
            try:
                if not show_hidden and _is_hidden(d):
                    continue
                st = d.stat(follow_symlinks=True)
                is_dir = stat.S_ISDIR(st.st_mode)
                out.append(Entry(d.name, is_dir, 0 if is_dir else st.st_size, st.st_mtime,
                                 stat.filemode(st.st_mode)[1:] if os.name != "nt" else "", "", d.is_symlink()))
            except OSError:
                continue
    return out


def _is_hidden(d):
    if d.name.startswith("."):
        return True
    if os.name == "nt":
        try:
            attrs = d.stat(follow_symlinks=False).st_file_attributes
            return bool(attrs & (stat.FILE_ATTRIBUTE_HIDDEN | stat.FILE_ATTRIBUTE_SYSTEM))
        except (OSError, AttributeError):
            return False
    return False


# --------------------------------------------------------------------------- LIST (Unix e DOS)
_MONTHS = {m: i for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1)}
_MONTHS.update({"gen": 1, "mag": 5, "giu": 6, "lug": 7, "ago": 8, "set": 9, "ott": 10, "dic": 12})
_UNIX = re.compile(
    r"^([\-ldcbpsD])([rwxsStTl\-]{9})[+@.]?\s+\d+\s+(\S+)\s+(?:(\S+)\s+)?(\d+)\s+(\S{3,4})\.?\s+(\d{1,2})\s+"
    r"(\d{1,2}:\d{2}|\d{4})\s(.*)$")
_DOS = re.compile(r"^(\d{2})-(\d{2})-(\d{2,4})\s+(\d{1,2}):(\d{2})\s*([AaPp][Mm])?\s+(<DIR>|\d+)\s+(.+)$")


def parse_list_line(line, now=None):
    line = line.rstrip("\r\n")
    if not line or line.lower().startswith("total "):
        return None
    m = _UNIX.match(line)
    if m:
        t, perms, owner, _group, size, mon, day, ty, name = m.groups()
        is_link = t == "l"
        target = ""
        if is_link and " -> " in name:
            name, target = name.split(" -> ", 1)
        mtime = _unix_time(mon, int(day), ty, now)
        return Entry(name, t == "d", int(size) if t != "d" else 0, mtime, perms, owner, is_link, target)
    m = _DOS.match(line)
    if m:
        mm, dd, yy, hh, mi, ampm, size, name = m.groups()
        y = int(yy)
        y = y + (2000 if y < 70 else 1900) if y < 100 else y
        h = int(hh) % 12 + (12 if ampm and ampm.lower() == "pm" else 0) if ampm else int(hh)
        try:
            mtime = calendar.timegm(datetime.datetime(y, int(mm), int(dd), h, int(mi)).timetuple())
        except ValueError:
            mtime = 0
        is_dir = size.upper() == "<DIR>"
        return Entry(name, is_dir, 0 if is_dir else int(size), mtime)
    return None


def _unix_time(mon, day, ty, now=None):
    month = _MONTHS.get(mon[:3].lower())
    if not month:
        return 0
    now = now or datetime.datetime.now(datetime.timezone.utc)
    try:
        if ":" in ty:
            hh, mi = (int(x) for x in ty.split(":"))
            dt = datetime.datetime(now.year, month, day, hh, mi)
            if dt > now.replace(tzinfo=None) + datetime.timedelta(days=2):
                dt = dt.replace(year=now.year - 1)
        else:
            dt = datetime.datetime(int(ty), month, day)
        return calendar.timegm(dt.timetuple())
    except ValueError:
        return 0


def parse_mlsd(name, facts):
    t = facts.get("type", "").lower()
    if t in ("cdir", "pdir") or name in (".", ".."):
        return None
    is_link = t.startswith("os.unix=slink") or t.startswith("os.unix=symlink")
    is_dir = t == "dir" or (is_link and facts.get("unix.mode", "").startswith("04"))
    mtime = 0
    mod = facts.get("modify", "")
    if len(mod) >= 14:
        try:
            mtime = calendar.timegm(datetime.datetime.strptime(mod[:14], "%Y%m%d%H%M%S").timetuple())
        except ValueError:
            pass
    perms = ""
    mode = facts.get("unix.mode", "")
    if mode:
        try:
            perms = octal_to_perms(mode[-3:])
        except ValueError:
            perms = ""
    owner = facts.get("unix.ownername") or facts.get("unix.owner") or facts.get("unix.uid", "")
    try:
        size = int(facts.get("size") or facts.get("sizd") or 0)
    except ValueError:
        size = 0
    return Entry(name, is_dir, 0 if is_dir else size, mtime, perms, owner, is_link)


def join(folder, name):
    """Unisce cartella remota e nome come fa il server ("/a" + "b" → "/a/b")."""
    return (folder.rstrip("/") + "/" + name) if folder not in ("", "/") else "/" + name


def parent(path):
    t = path.rstrip("/")
    if not t:
        return "/"
    i = t.rfind("/")
    return "/" if i <= 0 else t[:i]


def basename(path):
    return path.rstrip("/").rsplit("/", 1)[-1]
