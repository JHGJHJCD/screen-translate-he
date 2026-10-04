"""ביקורת חבילת השיתוף: מה כתוב על הקובץ, מה נכנס לחבילה, ומה חסר במתקין. רק קורא — לא משנה כלום.

הרצה: python tests/audit.py   (Python 3.12, אחרי build_share.py)
"""
import json
import marshal
import re
import subprocess
import sys
import winreg
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DIST = ROOT / "build" / "dist" / "ScreenTranslate"
EXE = DIST / "ScreenTranslate.exe"
SETUP = ROOT / "לשיתוף" / "התקנת תרגום מסך.exe"
ISS = ROOT / "build" / "installer.iss"
SOURCES = ["main.py", "config.py", "renderer.py", "translate_engine.py", "google_engine.py", "updater.py",
           "build_share.py", "release.py"]

rows = []


def row(name, ok, detail=""):
    rows.append((name, ok, detail))
    print(f"{'PASS' if ok else 'FAIL'}  {name}  {detail}")


def ps(script):
    out = subprocess.run(["powershell", "-NoProfile", "-Command",
                          "[Console]::OutputEncoding=[Text.Encoding]::UTF8; " + script],
                         capture_output=True, cwd=ROOT)
    return out.stdout.decode("utf-8", "replace").strip()


def file_info(path):
    rel = path.relative_to(ROOT)
    raw = ps(f"$f = Get-Item -LiteralPath '{rel}'; $v = $f.VersionInfo; "
             f"$s = Get-AuthenticodeSignature -LiteralPath '{rel}'; "
             "@{version=$v.FileVersion; product=$v.ProductName; company=$v.CompanyName; "
             "description=$v.FileDescription; signed=$s.Status.ToString()} | ConvertTo-Json")
    return json.loads(raw)


def consts(code):
    for c in code.co_consts:
        if hasattr(c, "co_consts"):
            yield from consts(c)
        else:
            yield c


def bundled_module_strings(name):
    """המחרוזות שבתוך מודול שנארז בקובץ ה-exe."""
    from PyInstaller.archive.readers import CArchiveReader, ZlibArchiveReader
    import tempfile
    arch = CArchiveReader(str(EXE))
    with tempfile.TemporaryDirectory() as tmp:
        pyz = Path(tmp) / "PYZ.pyz"
        pyz.write_bytes(arch.extract("PYZ.pyz"))
        z = ZlibArchiveReader(str(pyz))
        code = z.extract(name)
        if isinstance(code, tuple):
            code = code[1]
        if isinstance(code, bytes):
            code = marshal.loads(code)
        return [str(c) for c in consts(code)], sorted(z.toc)


# ---------- האם החבילה עדכנית ----------
newest = max((ROOT / s).stat().st_mtime for s in SOURCES)
row("חבילת השיתוף נבנתה אחרי השינוי האחרון בקוד", SETUP.stat().st_mtime > newest,
    f"קוד: {newest:.0f}, מתקין: {SETUP.stat().st_mtime:.0f}")

# ---------- מה כתוב על הקבצים ----------
for label, path in (("התוכנה", EXE), ("המתקין", SETUP)):
    info = file_info(path)
    row(f"{label}: מספר גרסה בקובץ", bool(info["version"]) and info["version"].strip() not in ("", "0.0.0.0"), repr(info["version"]))
    row(f"{label}: שם מוצר ושם מפיץ בקובץ", bool(info["product"]) and bool(info["company"]),
        f"product={info['product']!r} company={info['company']!r}")
    row(f"{label}: חתימה דיגיטלית", info["signed"] == "Valid", info["signed"])

# ---------- הגדרות המתקין ----------
iss = ISS.read_text(encoding="utf-8-sig")
for key, why in (("AppPublisher", "שם מפיץ ב'אפליקציות מותקנות'"),
                 ("AppVersion", "מספר גרסה"),
                 ("VersionInfoVersion", "מספר גרסה על קובץ המתקין"),
                 ("ArchitecturesAllowed", "הגבלה ל-64 ביט"),
                 ("MinVersion", "גרסת Windows מינימלית"),
                 ("LicenseFile", "הצגת רישיון בהתקנה"),
                 ("AppSupportURL", "כתובת תמיכה"),
                 ("CloseApplications", "סגירת התוכנה לפני התקנה")):
    m = re.search(rf"^{key}=(.*)$", iss, re.M)
    row(f"מתקין: {why} ({key})", bool(m), m.group(1) if m else "חסר")
row("מתקין: הסרה רשומה בתפריט התחל", "{uninstallexe}" in iss)
row("מתקין: התקנה בלי הרשאות מנהל", "PrivilegesRequired=lowest" in iss)

# ---------- גודל ותכולה ----------
total = sum(f.stat().st_size for f in DIST.rglob("*") if f.is_file())
row("גודל מותקן", total < 150e6, f"{total / 1e6:.0f}MB מותקן, מתקין {SETUP.stat().st_size / 1e6:.0f}MB")
sizes = {}
for f in (DIST / "_internal").rglob("*"):
    if f.is_file():
        top = f.relative_to(DIST / "_internal").parts[0]
        sizes[top] = sizes.get(top, 0) + f.stat().st_size
print("   הגדולים:", ", ".join(f"{k} {v / 1e6:.1f}MB" for k, v in sorted(sizes.items(), key=lambda kv: -kv[1])[:12]))

strings, modules = bundled_module_strings("config")
tops = sorted({m.split(".")[0] for m in modules})
unused = [m for m in ("google", "mcp", "opentelemetry", "websockets", "httpx", "httpx2", "httpcore", "httpcore2",
                      "pydantic", "jsonschema", "anyio", "click", "setuptools", "numpy", "cryptography", "PIL",
                      "tkinter", "unittest", "pytest", "IPython")
          if m in tops or (DIST / "_internal" / m).exists()]
needed_by_default = {"numpy"}
extra = [m for m in unused if m not in needed_by_default]
row("אין בחבילה ספריות שהמנוע הרגיל לא צריך", not extra, ", ".join(extra))

# ---------- פרטיות: מה דלף לחבילה ----------
personal = [s for s in strings if "יהודה" in s or "Users\\" in s]
row("אין נתיב אישי בתוך התוכנה המשותפת", not personal, "; ".join(personal))
keys = [f.name for f in DIST.rglob("*") if re.search(r"api_key|\.env$|secret", f.name, re.I)]
row("אין קובץ מפתח בחבילה", not keys, ", ".join(keys))
row("קוד הבדיקות לא נכנס לחבילה", not any(m.startswith(("harness", "run_tests", "test_units")) for m in modules))

# ---------- רישוי ----------
licenses = [str(f.relative_to(DIST)) for f in DIST.rglob("*") if re.search(r"licen[sc]e|copying|notice", f.name, re.I)]
qt_license = [l for l in licenses if "pyqt" in l.lower() or "qt6" in l.lower()]
row("רישיון PyQt/Qt מצורף לחבילה (GPL מחייב)", bool(qt_license), f"{len(licenses)} קובצי רישיון, של Qt: {len(qt_license)}")
row("קובץ הסבר מצורף להתקנה", "קרא אותי.txt" in iss)

# ---------- המחשב הזה ----------
try:
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Run") as k:
        run = winreg.QueryValueEx(k, "ScreenTranslateHe")[0]
except OSError:
    run = None
print("   ערך העלייה עם המחשב:", run)
log = ROOT / "error.log"
print("   error.log:", f"{log.stat().st_size} בתים" if log.exists() else "לא קיים")

failed = [r for r in rows if not r[1]]
print(f"\n{len(rows) - len(failed)} עברו, {len(failed)} נכשלו/חסרים")
(ROOT / "tests" / "audit_result.json").write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")
