"""הגדרות שאפשר לשנות בקלות. אין כאן מפתחות — רק מיקומים של קובצי מפתח."""
import os
import sys
from pathlib import Path

FROZEN = getattr(sys, "frozen", False)   # גרסת השיתוף (exe עצמאי, בלי Python)
HERE = Path(sys.executable).resolve().parent if FROZEN else Path(__file__).resolve().parent

# --- מה שכתוב על הקבצים של גרסת השיתוף (build_share.py קורא מכאן) ---
VERSION = "1.2.0"
PUBLISHER = "תרגום מסך"

# --- עדכונים ---
REPO = "JHGJHJCD/screen-translate-he"     # המאגר ב-GitHub שבו מתפרסמות גרסאות (release.py)
# טביעת האצבע של תעודת החתימה (CN=ScreenTranslate במחשב הבנייה). עדכון מותקן רק אם הוא חתום בה.
SIGNER = "B59ED57132BB55E5C9CB04E530C1A0380993F77B"
UPDATE_FIRST_S = 30    # כמה אחרי ההפעלה בודקים בפעם הראשונה אם יש גרסה חדשה
UPDATE_EVERY_H = 24    # ואחר כך כל כמה שעות

# --- תזמונים ---
SETTLE_MS = 600        # כמה לחכות אחרי שהריבוע הפסיק לזוז לפני שמתרגמים
WATCH_MS = 700         # כל כמה זמן בודקים אם התוכן שמתחת לריבוע השתנה
MESSAGE_MS = 3500      # כמה זמן הודעה קטנה ("לא נמצא טקסט") נשארת על המסך

# --- הגנה מפני שליחה בלתי פוסקת ל-Google ---
MIN_GAP_S = 0.8        # מרווח מינימלי בין שתי בקשות אוטומטיות
MAX_GAP_S = 300.0      # עד כמה המרווח גדל כשהתוכן "זז" אבל הטקסט לא משתנה (וידאו, אנימציה)
MAX_PER_MINUTE = 15    # תקרת בקשות בדקה (ל-Gemini החינמי כדאי 8). 30 הביא לחסימת 429 מ-Google (4/10/2026)
CACHE_SIZE = 40        # כמה תרגומים אחרונים לזכור (בזיכרון בלבד, לא בדיסק)

# --- קיצור מקלדת להפעלה/כיבוי: Ctrl+Alt+T ---
HOTKEY_MODIFIERS = 0x0002 | 0x0001   # MOD_CONTROL | MOD_ALT
HOTKEY_KEY = ord("T")
HOTKEY_LABEL = "Ctrl+Alt+T"

# --- Google ---
# "translate" = זיהוי הטקסט במחשב (Windows) + תרגום ב-Google Translate. בלי מפתח ובלי מכסה יומית.
# "gemini"    = התמונה נשלחת ל-Gemini שעושה הכול. דורש מפתח; 20 בקשות ביום לכל מודל בחינם.
ENGINE = "translate"

# לכל מודל מכסה יומית חינמית נפרדת (ל-gemini-3.5-flash נמדדו 20 ביום). כשמכסה נגמרת
# עוברים אוטומטית למודל הבא ברשימה. הסדר: איכות תרגום קודם; מודלי ה-lite בסוף
# (בבדיקה gemini-3.5-flash-lite החזיר פעם עברית משובשת).
MODELS = [
    "gemini-3.5-flash",
    "gemini-3-flash-preview",
    "gemini-3.6-flash",
    "gemini-flash-latest",
    "gemini-3.8-flash",
    "gemini-3.7-flash",
    "gemini-flash-lite-latest",
    "gemini-3.1-flash-lite",
    "gemini-3.5-flash-lite",
]
REQUEST_TIMEOUT_MS = 25000
MAX_IMAGE_SIDE = 1600  # תמונה גדולה מזה מוקטנת לפני השליחה

# המפתח נקרא מ-GEMINI_API_KEY, ואם אין — מהקובץ הראשון שקיים ברשימה.
KEY_FILES = [HERE / "api_key.txt"]
# גרסת הפיתוח בלבד: מיקום נוסף של קובץ מפתח, מ-ST_KEY_FILE או מהשורה שב-key_path.local.txt.
# הנתיב עצמו לא כתוב בקוד, כדי שלא ייארז לתוך גרסת השיתוף.
if not FROZEN:
    _extra = os.environ.get("ST_KEY_FILE", "").strip()
    if not _extra:
        try:
            _extra = (HERE / "key_path.local.txt").read_text(encoding="utf-8-sig").strip()
        except OSError:
            _extra = ""
    if _extra:
        KEY_FILES.append(Path(_extra))

# סימון שהודעת הפרטיות של ההפעלה הראשונה כבר הוצגה (קובץ ריק; ההסרה מוחקת אותו)
PRIVACY_MARK = HERE / "privacy_seen"
# המיקום והגודל האחרונים של הריבוע ("x,y,רוחב,גובה"), באותו מקום ובאותה שיטה; ההסרה מוחקת גם אותו
PLACE_FILE = HERE / "window_place"

# --- מראה ---
RED = "#E51400"        # האדום של Windows 8
GREEN = "#107C10"      # המסגרת כשהתרגום מוצג
BAR_OFF ="#5A5A5A"
BAR_HEIGHT = 30
BORDER = 2
GRIP = 7               # רוחב אזור האחיזה לשינוי גודל (כמעט בלתי נראה)
FONT_FAMILY = "Segoe UI"
MIN_FONT_PX = 9
