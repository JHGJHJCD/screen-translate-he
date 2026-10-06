"""תרגום מסך — ריבוע אדום שמתרגם לעברית את מה שמתחתיו.

החלון, הצילום וניהול המצב נמצאים כאן. הזיהוי והתרגום ב-google_engine.py,
ציור העברית ב-renderer.py, וכל המספרים שאפשר לכוון ב-config.py.
"""
import ctypes
import hashlib
import os
import sys
import threading
import time
import traceback
import winreg
from collections import OrderedDict, deque
from ctypes import wintypes
from pathlib import Path

import numpy as np
from PyQt6.QtCore import QObject, QPoint, QPointF, QRect, QRectF, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import (QColor, QCursor, QFont, QFontMetricsF, QGuiApplication, QIcon, QImage, QPainter, QPen,
                         QPixmap, QPolygonF)
from PyQt6.QtWidgets import QApplication, QMenu, QMessageBox, QSystemTrayIcon, QWidget

import config
import renderer
import updater
from google_engine import EngineError, GoogleEngine
from translate_engine import TranslateEngine

user32 = ctypes.windll.user32
WM_HOTKEY = 0x0312
WDA_EXCLUDEFROMCAPTURE = 0x11
MOD_NOREPEAT = 0x4000
HOTKEY_ID = 1
WM_SHOW = 0x8000 + 1                   # WM_APP+1: הפעלה נוספת של התוכנה מבקשת להציג את הריבוע
WINDOW_TITLE = "תרגום מסך"
RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
RUN_NAME = "ScreenTranslateHe"
user32.FindWindowW.restype = wintypes.HWND
user32.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]

# מצבי בדיקה (לא בשימוש רגיל): תיקייה לשמירת תמונות בדיקה, ומיקום התחלתי.
DEBUG_DIR = os.environ.get("ST_DEBUG_DIR")
NO_EXCLUDE = os.environ.get("ST_NO_EXCLUDE") == "1"

MESSAGES = {
    "no_key": "לא נמצא מפתח Google",
    "bad_key": "מפתח Google לא תקין",
    "offline": "אין חיבור לאינטרנט",
    "rate": "Google מגביל כרגע את הבקשות, מנסה שוב בעוד רגע",
    "blocked": "הבקשה נחסמה על ידי נטפרי",
    "no_ocr": "חסרה שפת אנגלית ב-Windows (הגדרות ← זמן ושפה ← שפה ← הוסף English)",
    "other": "Google לא הגיב כרגע",
}

# הודעת הפרטיות של ההפעלה הראשונה: מה נשלח ל-Google בכל מנוע
PRIVACY_SENT = {
    "translate": "הטקסט שמתחת לריבוע נשלח ל-Google Translate כדי לתרגם אותו.\n"
                 "התמונה של המסך עצמה לא יוצאת מהמחשב.",
    "gemini": "התמונה של מה שמתחת לריבוע נשלחת ל-Google (Gemini) כדי לתרגם אותה.",
}
PRIVACY_ADVICE = "לכן לא כדאי להניח את הריבוע מעל סיסמאות, פרטי בנק או מידע רגיש אחר."


def truncate_error_log():
    log_path = Path("error.log")
    if log_path.exists() and log_path.stat().st_size > 200 * 1024:
        try:
            content = log_path.read_bytes()
            log_path.write_bytes(content[-200 * 1024:])
        except Exception:
            pass


def log_error(msg):
    truncate_error_log()
    try:
        with open("error.log", "a", encoding="utf-8") as f:
            f.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} - {msg}\n")
    except Exception:
        pass


def signature(image):
    """טביעת אצבע קטנה של האזור, כדי לזהות שהתוכן השתנה בלי לשלוח כלום."""
    small = image.scaled(64, 64, Qt.AspectRatioMode.IgnoreAspectRatio,
                         Qt.TransformationMode.SmoothTransformation)
    small = small.convertToFormat(QImage.Format.Format_Grayscale8)
    bits = small.constBits()
    bits.setsize(small.sizeInBytes())
    return np.frombuffer(bits, np.uint8).reshape(64, small.bytesPerLine())[:, :64].astype(np.int16)
