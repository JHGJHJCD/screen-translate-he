"""בדיקת עדכונים מול GitHub. רק מודיעים שיש גרסה חדשה; מורידים ומתקינים רק כשהמשתמש מאשר.

קובץ ההתקנה שיורד מופעל רק אם הוא חתום באותה תעודה שאיתה נחתמה הגרסה הזו (config.SIGNER)
ולא שונה אחרי החתימה. כך גם מי שישתלט על המאגר ב-GitHub לא יוכל להתקין משהו אחר.
"""
import json
import os
import subprocess
import tempfile
import urllib.request
from pathlib import Path

import config

API = f"https://api.github.com/repos/{config.REPO}/releases/latest"
PAGE = f"https://github.com/{config.REPO}/releases/latest"
DOWNLOAD_PREFIX = f"https://github.com/{config.REPO}/releases/download/"
ASSET = "ScreenTranslateSetup.exe"
TIMEOUT_S = 20
MAX_BYTES = 300 * 1024 * 1024       # קובץ התקנה גדול מזה הוא לא שלנו
GOOD_STATUS = ("Valid", "UnknownError")     # UnknownError = חתימה שלמה מתעודה ש-Windows לא מכיר (עצמית)


class UpdateError(Exception):
    pass


def current_version():
    """הגרסה שרצה עכשיו. בבדיקות (ST_DEBUG_DIR) אפשר להציג אותה כישנה יותר עם ST_VERSION."""
    if os.environ.get("ST_DEBUG_DIR") and os.environ.get("ST_VERSION"):
        return os.environ["ST_VERSION"]
    return config.VERSION


def parse_version(text):
    """"v1.2.0" -> (1, 2, 0). טקסט שאינו מספר גרסה -> ()."""
    try:
        return tuple(int(part) for part in str(text).strip().lstrip("vV").split("."))
    except ValueError:
        return ()


def pick(release, current):
    """מתוך התשובה של GitHub: (גרסה, כתובת קובץ ההתקנה) אם היא חדשה מהנוכחית, אחרת None."""
    if not isinstance(release, dict) or release.get("draft") or release.get("prerelease"):
        return None
    latest = parse_version(release.get("tag_name", ""))
    if not latest or latest <= parse_version(current):
        return None
    for asset in release.get("assets") or []:
        url = str(asset.get("browser_download_url", ""))
        if asset.get("name") == ASSET and url.startswith(DOWNLOAD_PREFIX):
            return ".".join(str(n) for n in latest), url
    return None


def _open(url):
    try:
        import truststore
        truststore.inject_into_ssl()        # נטפרי וסינונים דומים: סומכים על התעודות של Windows
    except Exception:
        pass
    request = urllib.request.Request(url, headers={"User-Agent": f"ScreenTranslate/{config.VERSION}",
                                                   "Accept": "application/vnd.github+json"})
    return urllib.request.urlopen(request, timeout=TIMEOUT_S)


def find():
    """(גרסה, כתובת) אם יש גרסה חדשה, None אם אין. תקלת רשת -> UpdateError."""
    try:
        with _open(API) as answer:
            release = json.loads(answer.read(2_000_000).decode("utf-8"))
    except Exception as e:
        raise UpdateError(repr(e))
    return pick(release, current_version())


def download(url, version):
    folder = Path(tempfile.gettempdir()) / "ScreenTranslateUpdate"
    folder.mkdir(exist_ok=True)
    target = folder / f"ScreenTranslateSetup-{version}.exe"
    try:
        with _open(url) as answer, open(target, "wb") as f:
            total = 0
            while chunk := answer.read(1 << 16):
                total += len(chunk)
                if total > MAX_BYTES:
                    raise UpdateError("too big")
                f.write(chunk)
    except UpdateError:
        raise
    except Exception as e:
        raise UpdateError(repr(e))
    return target


def signature(path):
    """(מצב החתימה, טביעת האצבע של התעודה החותמת) כפי ש-Windows רואה אותן."""
    script = ("$s = Get-AuthenticodeSignature -LiteralPath $env:ST_CHECK_FILE; "
              "$s.Status.ToString() + '|' + $s.SignerCertificate.Thumbprint")
    try:
        out = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
                             env=dict(os.environ, ST_CHECK_FILE=str(path)), capture_output=True, timeout=60,
                             creationflags=subprocess.CREATE_NO_WINDOW)
        status, _, thumbprint = out.stdout.decode("ascii", "replace").strip().partition("|")
    except Exception as e:
        raise UpdateError(repr(e))
    return status, thumbprint.strip().upper()


def is_ours(path):
    status, thumbprint = signature(path)
    return bool(config.SIGNER) and thumbprint == config.SIGNER.upper() and status in GOOD_STATUS


def fetch(url, version):
    """מוריד את קובץ ההתקנה ומחזיר את מיקומו רק אם החתימה שלו שלנו."""
    path = download(url, version)
    if not is_ours(path):
        path.unlink(missing_ok=True)
        raise UpdateError("bad signature")
    return path


def install(path):
    """מפעיל את ההתקנה. היא סוגרת את התוכנה, מחליפה את הקבצים ומפעילה אותה מחדש."""
    subprocess.Popen([str(path), "/SILENT", "/UPDATE=1", "/NORESTART"], close_fds=True,
                     creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP)
