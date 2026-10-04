"""בונה את גרסת השיתוף: קובץ התקנה אחד (בלי Python) ב-"לשיתוף", עם הסרה דרך Windows.

הרצה: python build_share.py   (Python 3.12, מתוך תיקיית הפרויקט)
"""
import os
import shutil
import subprocess
import sys
from importlib import metadata
from pathlib import Path

from PyQt6.QtWidgets import QApplication

import config

HERE = Path(__file__).resolve().parent
OUT = HERE / "לשיתוף"
NAME = "ScreenTranslate"          # שם באנגלית: כלי הבנייה לא אוהב עברית בשם הקובץ
FOLDER = "תרגום מסך"
SETUP = "התקנת תרגום מסך.exe"
ISCC = Path(r"C:\Program Files (x86)\Inno Setup 6\ISCC.exe")
VERSION4 = (config.VERSION.split(".") + ["0"] * 4)[:4]      # Windows רוצה ארבעה מספרים
DESCRIPTION = "תרגום מסך (אנגלית לעברית)"

README = """תרגום מסך (אנגלית -> עברית)
===========================

איך מתחילים
התוכנה כבר מותקנת. מפעילים אותה מ"תרגום מסך" בתפריט התחל (או מהקיצור בשולחן העבודה).

איך מסירים
הגדרות -> אפליקציות -> אפליקציות מותקנות -> "תרגום מסך" -> הסר התקנה.
או: תפריט התחל -> "הסרת תרגום מסך".

איך משתמשים
- מופיע ריבוע עם מסגרת אדומה. גוררים אותו (מהפס שלמעלה) מעל טקסט באנגלית,
  והעברית מופיעה במקום האנגלית. אפשר למתוח אותו מהצדדים ומהפינות.
- מסגרת אדומה = עובד על התרגום. מסגרת ירוקה = התרגום מוצג.
- Ctrl+Alt+T  מציג / מסתיר את הריבוע.
- ה-X רק מסתיר. התוכנה נשארת ליד השעון (ריבוע אדום קטן עם "א").
- לחיצה ימנית על הסמל שליד השעון:
    "לעלות עם המחשב" - כדי שתהיה מוכנה תמיד בלי לחפש אותה.
    "בדוק אם יש גרסה חדשה" - בודק עכשיו.
    "אודות" - מספר הגרסה.
    "יציאה" - סגירה אמיתית.
- הריבוע זוכר איפה היה ובאיזה גודל, ונפתח שם גם בפעם הבאה.

אם כתוב "חסרה שפת אנגלית ב-Windows"
הגדרות -> זמן ושפה -> שפה ואזור -> הוסף שפה -> English (United States).

מה צריך
Windows 10 או 11, וחיבור לאינטרנט. התמונה של המסך לא נשלחת לשום מקום -
רק הטקסט האנגלי נשלח ל-Google Translate לתרגום.

עדכונים
פעם ביום התוכנה בודקת ב-GitHub אם יצאה גרסה חדשה. אם יש, היא שואלת אם להתקין;
שום דבר לא יורד ולא מותקן בלי אישור. בבדיקה הזו לא נשלח שום מידע על המחשב או על מה שתורגם.
אפשר גם להוריד ידנית: https://github.com/@REPO@/releases/latest

רישיונות וקוד מקור
התוכנה בנויה על רכיבים חופשיים (PyQt, Qt, Python, numpy ועוד). הפירוט בקובץ
"רישיונות צד שלישי.txt" שבתיקיית התוכנה, והרישיונות עצמם בתיקייה licenses.
קוד המקור של התוכנה נמצא בתיקייה source, וגם ב-https://github.com/@REPO@ . התוכנה מופצת ברישיון GPL גרסה 3:
מותר להשתמש בה, לשנות אותה ולהעביר אותה הלאה, באותם תנאים.
"""

# הרכיבים שנארזים בחבילה: (שם, חבילת pip שממנה נלקח טקסט הרישיון, רישיון, איפה הקוד שלו)
COMPONENTS = [
    ("PyQt6", "PyQt6", "GPL v3", "https://www.riverbankcomputing.com/software/pyqt/"),
    ("Qt6", "PyQt6-Qt6", "LGPL v3", "https://www.qt.io/download-open-source"),
    ("PyQt6-sip", "PyQt6-sip", "BSD 2-Clause", "https://github.com/Python-SIP/sip"),
    ("numpy", "numpy", "BSD 3-Clause", "https://github.com/numpy/numpy"),
    ("truststore", "truststore", "MIT", "https://github.com/sethmlarson/truststore"),
    ("winrt", "winrt-runtime", "MIT", "https://github.com/pywinrt/pywinrt"),
    ("PyInstaller", "pyinstaller", "GPL v2+ עם חריג שמתיר הפצה", "https://github.com/pyinstaller/pyinstaller"),
    ("Python", None, "PSF License", "https://www.python.org/downloads/source/"),
]
# חבילה שלא מצרפת קובץ רישיון: מפנים לטקסט שבמאגר שלה
NO_LICENSE_FILE = "This component is distributed under the {license} license.\nThe full license text: {url}\n"

THIRD_PARTY = r"""רישיונות צד שלישי - תרגום מסך @VERSION@
==========================================

התוכנה "תרגום מסך" מופצת ברישיון GNU General Public License גרסה 3 (GPL v3),
כי היא בנויה על PyQt6 שמופץ ברישיון הזה. הטקסט המלא: licenses\PyQt6-LICENSE.txt
קוד המקור של התוכנה: התיקייה source שליד הקובץ הזה.
אין לתוכנה אחריות מכל סוג, כמפורט ברישיון.

הרכיבים שבתוך החבילה (הטקסט המלא של כל רישיון בתיקייה licenses):

@LIST@

את ספריות Qt (קובצי Qt6*.dll שבתיקייה _internal\PyQt6\Qt6\bin) אפשר להחליף בגרסה אחרת
שלהן, כפי שרישיון LGPL דורש.
"""

# מנוע Gemini (google_engine.py) מייבא את הספריות האלה רק כשמשתמשים בו. גרסת השיתוף עובדת
# רק עם מנוע translate, ולכן הן וכל מה שהן גוררות נשארות בחוץ.
EXCLUDED = ["google", "mcp", "opentelemetry", "websockets", "httpx", "httpx2", "httpcore", "httpcore2",
            "pydantic", "pydantic_core", "jsonschema", "anyio", "click", "setuptools", "cryptography",
            "unittest", "PyQt6.QtWebEngineCore", "PyQt6.QtWebEngineWidgets", "PIL", "tkinter"]
SOURCES = ["main.py", "config.py", "renderer.py", "translate_engine.py", "google_engine.py", "updater.py",
           "build_share.py", "release.py"]

# קובץ ההתקנה (Inno Setup). הנתיבים יחסיים לתיקיית build, כי כלי הבנייה לא קורא עברית בשורת הפקודה.
INSTALLER = r'''[Setup]
AppId={{6B0E4C1A-52D7-4E0B-9A3F-7C1D2E8F4A90}
AppName=תרגום מסך
AppVersion=@VERSION@
AppPublisher=@PUBLISHER@
AppSupportURL=https://github.com/@REPO@
AppUpdatesURL=https://github.com/@REPO@/releases/latest
VersionInfoVersion=@VERSION4@
VersionInfoProductVersion=@VERSION4@
VersionInfoProductTextVersion=@VERSION@
VersionInfoCompany=@PUBLISHER@
VersionInfoProductName=תרגום מסך
VersionInfoDescription=התקנת תרגום מסך
VersionInfoCopyright=@PUBLISHER@
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0.19041
DefaultDirName={localappdata}\Programs\ScreenTranslate
PrivilegesRequired=lowest
DisableDirPage=yes
DisableProgramGroupPage=yes
OutputDir=installer
OutputBaseFilename=ScreenTranslateSetup
SetupIconFile=icon.ico
UninstallDisplayIcon={app}\ScreenTranslate.exe
UninstallDisplayName=תרגום מסך
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
CloseApplications=no

[Languages]
Name: "he"; MessagesFile: "compiler:Languages\Hebrew.isl"

[Tasks]
Name: "desktopicon"; Description: "קיצור בשולחן העבודה"
Name: "startup"; Description: "להפעיל עם המחשב (מוסתרת, מחכה ל-Ctrl+Alt+T)"

[Files]
Source: "dist\ScreenTranslate\*"; DestDir: "{app}"; Flags: recursesubdirs ignoreversion
Source: "readme.txt"; DestDir: "{app}"; DestName: "קרא אותי.txt"; Flags: ignoreversion
Source: "third_party.txt"; DestDir: "{app}"; DestName: "רישיונות צד שלישי.txt"; Flags: ignoreversion

[Icons]
Name: "{userprograms}\תרגום מסך"; Filename: "{app}\ScreenTranslate.exe"
Name: "{userprograms}\הסרת תרגום מסך"; Filename: "{uninstallexe}"
Name: "{userdesktop}\תרגום מסך"; Filename: "{app}\ScreenTranslate.exe"; Tasks: desktopicon

[Registry]
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: string; ValueName: "ScreenTranslateHe"; ValueData: """{app}\ScreenTranslate.exe"" --hidden"; Tasks: startup

[Run]
Filename: "{app}\ScreenTranslate.exe"; Description: "להפעיל את תרגום מסך"; Flags: nowait postinstall skipifsilent
Filename: "{app}\ScreenTranslate.exe"; Flags: nowait; Check: IsUpdate

[UninstallRun]
Filename: "{sys}\taskkill.exe"; Parameters: "/F /IM ScreenTranslate.exe"; Flags: runhidden; RunOnceId: "StopApp"

[UninstallDelete]
Type: files; Name: "{app}\error.log"
Type: files; Name: "{app}\privacy_seen"
Type: files; Name: "{app}\window_place"
Type: dirifempty; Name: "{app}"

[Code]
const RunKey = 'Software\Microsoft\Windows\CurrentVersion\Run';

{ עדכון מתוך התוכנה (/UPDATE=1): בסוף ההתקנה השקטה מפעילים אותה מחדש }
function IsUpdate: Boolean;
begin
  Result := ExpandConstant('{param:UPDATE|0}') = '1';
end;

function PrepareToInstall(var NeedsRestart: Boolean): String;
var Code: Integer;
begin
  Exec(ExpandConstant('{sys}\taskkill.exe'), '/F /IM ScreenTranslate.exe', '', SW_HIDE, ewWaitUntilTerminated, Code);
  Result := '';
end;

procedure CurUninstallStepChanged(Step: TUninstallStep);
var Value: String;
begin
  { מוחקים את העלייה עם המחשב רק אם היא מצביעה על ההתקנה הזו }
  if (Step = usUninstall) and RegQueryStringValue(HKCU, RunKey, 'ScreenTranslateHe', Value) then
    if Pos(Lowercase(ExpandConstant('{app}')), Lowercase(Value)) > 0 then
      RegDeleteValue(HKCU, RunKey, 'ScreenTranslateHe');
end;
'''

# מה שכתוב על ScreenTranslate.exe (לחיצה ימנית -> מאפיינים -> פרטים)
VERSION_FILE = '''VSVersionInfo(
  ffi=FixedFileInfo(filevers=(@TUPLE@), prodvers=(@TUPLE@), mask=0x3f, flags=0x0, OS=0x40004,
                    fileType=0x1, subtype=0x0, date=(0, 0)),
  kids=[
    StringFileInfo([StringTable('040904B0', [
      StringStruct('CompanyName', '@PUBLISHER@'),
      StringStruct('FileDescription', '@DESCRIPTION@'),
      StringStruct('FileVersion', '@VERSION4@'),
      StringStruct('InternalName', 'ScreenTranslate'),
      StringStruct('LegalCopyright', '@PUBLISHER@'),
      StringStruct('OriginalFilename', 'ScreenTranslate.exe'),
      StringStruct('ProductName', 'תרגום מסך'),
      StringStruct('ProductVersion', '@VERSION@')])]),
    VarFileInfo([VarStruct('Translation', [1033, 1200])])
  ]
)
'''


def fill(template):
    for mark, value in (("@VERSION4@", ".".join(VERSION4)), ("@TUPLE@", ", ".join(VERSION4)),
                        ("@VERSION@", config.VERSION), ("@PUBLISHER@", config.PUBLISHER),
                        ("@DESCRIPTION@", DESCRIPTION), ("@REPO@", config.REPO)):
        template = template.replace(mark, value)
    return template


def license_text(package, license, url):
    """טקסט הרישיון כפי שהחבילה המותקנת מצרפת אותו."""
    if package is None:
        return (Path(sys.base_prefix) / "LICENSE.txt").read_text(encoding="utf-8", errors="replace")
    dist = metadata.distribution(package)
    found = [f for f in dist.files or []
             if ".dist-info" in f.as_posix() and f.name.upper().startswith(("LICENSE", "COPYING"))]
    if not found:
        return NO_LICENSE_FILE.format(license=license, url=url)
    main_file = min(found, key=lambda f: len(f.parts))       # הרישיון הראשי, לא של תת-רכיב
    return main_file.locate().read_text(encoding="utf-8", errors="replace")


def add_licenses_and_source(dist, build):
    """מצרף לחבילה את הרישיונות של הרכיבים ואת קוד המקור (GPL מחייב את שניהם)."""
    folder = dist / "licenses"
    folder.mkdir(exist_ok=True)
    lines = []
    for name, package, license, url in COMPONENTS:
        version = metadata.version(package) if package else sys.version.split()[0]
        (folder / f"{name}-LICENSE.txt").write_text(license_text(package, license, url), encoding="utf-8")
        lines.append(f"- {name} {version}: {license}\n  קוד המקור: {url}")
    text = fill(THIRD_PARTY).replace("@LIST@", "\n".join(lines))
    (build / "third_party.txt").write_text(text, encoding="utf-8-sig", newline="\r\n")

    source = dist / "source"
    source.mkdir(exist_ok=True)
    for name in SOURCES:
        code = (HERE / name).read_text(encoding="utf-8")
        if Path.home().name in code or "Users" + "\\" in code:
            raise SystemExit(f"נתיב אישי בתוך {name} - לא מצרפים אותו לחבילה")
        shutil.copy2(HERE / name, source / name)


def sign(path):
    """חותם על קובץ בתעודה של התוכנה (config.SIGNER). בלי חתימה עדכון מתוך התוכנה לא יותקן."""
    script = ("$c = Get-Item -LiteralPath ('Cert:/CurrentUser/My/' + $env:ST_SIGNER); "
              "$s = Set-AuthenticodeSignature -LiteralPath $env:ST_SIGN_FILE -Certificate $c -HashAlgorithm SHA256; "
              "$g = Get-AuthenticodeSignature -LiteralPath $env:ST_SIGN_FILE; "
              "$g.Status.ToString() + '|' + $g.SignerCertificate.Thumbprint")
    out = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", script], capture_output=True,
                         env=dict(os.environ, ST_SIGNER=config.SIGNER, ST_SIGN_FILE=str(path)))
    status, _, thumbprint = out.stdout.decode("ascii", "replace").strip().partition("|")
    if thumbprint.strip().upper() != config.SIGNER.upper() or status not in ("Valid", "UnknownError"):
        raise SystemExit(f"החתימה על {path.name} נכשלה: {status} {out.stderr.decode('utf-8', 'replace')}")


def main():
    app = QApplication([])
    from main import app_icon
    icon = HERE / "build" / "icon.ico"
    icon.parent.mkdir(exist_ok=True)
    app_icon().pixmap(256, 256).save(str(icon), "ICO")
    version_file = icon.with_name("version.txt")
    version_file.write_text(fill(VERSION_FILE), encoding="utf-8")

    subprocess.run([sys.executable, "-m", "PyInstaller", "main.py", "--name", NAME, "--noconsole", "--noconfirm",
                    "--icon", str(icon), "--version-file", str(version_file), "--distpath", "build/dist", "--workpath", "build/work",
                    "--specpath", "build", "--collect-submodules", "winrt",
                    *[arg for module in EXCLUDED for arg in ("--exclude-module", module)]],
                   cwd=HERE, check=True)

    build = HERE / "build"
    sign(build / "dist" / NAME / f"{NAME}.exe")
    add_licenses_and_source(build / "dist" / NAME, build)
    (build / "readme.txt").write_text(README.replace("\n", "\r\n"), encoding="utf-8-sig")
    (build / "installer.iss").write_text(fill(INSTALLER), encoding="utf-8-sig")
    subprocess.run([str(ISCC), "/Q", r"build\installer.iss"], cwd=HERE, check=True)

    sign(build / "installer" / "ScreenTranslateSetup.exe")

    shutil.rmtree(OUT, ignore_errors=True)
    OUT.mkdir()
    setup = OUT / SETUP
    shutil.move(build / "installer" / "ScreenTranslateSetup.exe", setup)
    print(f"{setup.stat().st_size / 1e6:.0f} MB")


if __name__ == "__main__":
    main()
