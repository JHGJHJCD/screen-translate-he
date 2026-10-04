"""מפרסם את הגרסה שב-config.VERSION ב-GitHub, כדי שהתוכנות המותקנות יציעו אותה כעדכון.

לפני כן: להעלות את config.VERSION, להריץ build_share.py ולבדוק את ההתקנה.
הרצה: python release.py "מה חדש בגרסה"   (Python 3.12, מתוך תיקיית הפרויקט; דורש git ו-gh מחוברים)
"""
import shutil
import subprocess
import sys
from pathlib import Path

import config
import updater

HERE = Path(__file__).resolve().parent
SETUP = HERE / "לשיתוף" / "התקנת תרגום מסך.exe"
TAG = f"v{config.VERSION}"


def run(*args, **kwargs):
    return subprocess.run(args, cwd=HERE, check=True, **kwargs)


def main():
    notes = sys.argv[1] if len(sys.argv) > 1 else f"גרסה {config.VERSION}"
    if not updater.is_ours(SETUP):
        raise SystemExit("קובץ ההתקנה לא חתום בתעודה של התוכנה. להריץ קודם build_share.py")
    dirty = subprocess.run(["git", "status", "--porcelain"], cwd=HERE, capture_output=True, text=True).stdout.strip()
    if dirty:
        raise SystemExit("יש שינויים שלא נשמרו ב-git. לעשות commit לפני פרסום גרסה.")
    asset = HERE / "build" / updater.ASSET          # שם באנגלית: כך התוכנה מחפשת אותו
    shutil.copy2(SETUP, asset)
    run("git", "push", "origin", "HEAD")
    run("gh", "release", "create", TAG, f"build/{updater.ASSET}", "--repo", config.REPO,
        "--title", f"תרגום מסך {config.VERSION}", "--notes", notes)
    print(f"https://github.com/{config.REPO}/releases/tag/{TAG}")


if __name__ == "__main__":
    main()
