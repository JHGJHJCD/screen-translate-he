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


def signature(image):
    """טביעת אצבע קטנה של האזור, כדי לזהות שהתוכן השתנה בלי לשלוח כלום."""
    small = image.scaled(64, 64, Qt.AspectRatioMode.IgnoreAspectRatio,
                         Qt.TransformationMode.SmoothTransformation)
    small = small.convertToFormat(QImage.Format.Format_Grayscale8)
    bits = small.constBits()
    bits.setsize(small.sizeInBytes())
    return np.frombuffer(bits, np.uint8).reshape(64, small.bytesPerLine())[:, :64].astype(np.int16)


def changed_cells(a, b, mask=None):
    """כמה משבצות (מתוך 4096) השתנו בין שתי טביעות אצבע. mask = משבצות שמתעלמים מהן."""
    diff = np.abs(a - b) > 16
    if mask is not None:
        diff &= ~mask
    return int(diff.sum())


SMALL_CHANGE = 8      # פחות מזה = אותו תוכן (סמן מהבהב וכדומה)
BIG_CHANGE = 400      # יותר מזה = תוכן אחר לגמרי (גלילה, מעבר דף)

MIN_WIDTH, MIN_HEIGHT = 170, config.BAR_HEIGHT + 60
BAR_REACH = 100       # כמה מהפס העליון חייב להיות על מסך כדי שיהיה אפשר לתפוס ולגרור את הריבוע


def parse_place(text, screens):
    """המיקום והגודל השמורים ("x,y,רוחב,גובה") כ-QRect, או None אם אי אפשר להשתמש בהם.

    screens = השטחים של המסכים המחוברים כרגע. מיקום שנשאר מחוץ להם (מסך שנותק, רזולוציה
    שהשתנתה) נפסל, והריבוע חוזר למרכז.
    """
    try:
        x, y, w, h = (int(v) for v in text.strip().split(","))
    except ValueError:
        return None
    if w < MIN_WIDTH or h < MIN_HEIGHT:
        return None
    bar = QRect(x, y, w, config.BAR_HEIGHT)
    for screen in screens:
        seen = bar.intersected(screen)
        if seen.width() >= BAR_REACH and seen.height() >= config.BAR_HEIGHT:
            return QRect(x, y, w, h)
    return None


def saved_place():
    try:
        text = config.PLACE_FILE.read_text(encoding="utf-8")
    except OSError:
        return None
    return parse_place(text, [s.availableGeometry() for s in QGuiApplication.screens()])


def about_text():
    lines = [f"גרסה {config.VERSION}", "",
             "מתרגם לעברית את האנגלית שמתחת לריבוע.",
             f"{config.HOTKEY_LABEL} מציג ומסתיר את הריבוע."]
    lines += ["", f"גרסאות חדשות וקוד המקור: github.com/{config.REPO}"]
    if config.FROZEN:
        lines += ["", "רישיונות הרכיבים וקוד המקור נמצאים בתיקיית התוכנה",
                  "(התיקיות licenses ו-source)."]
    return "\n".join(lines)


def autostart_enabled():
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
            winreg.QueryValueEx(key, RUN_NAME)
        return True
    except OSError:
        return False


def set_autostart(on):
    """עלייה עם המחשב: התוכנה נפתחת מוסתרת ומחכה לקיצור המקלדת."""
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as key:
        if on:
            if config.FROZEN:
                command = f'"{sys.executable}" --hidden'
            else:
                pythonw = Path(sys.executable).with_name("pythonw.exe")
                command = f'"{pythonw}" "{config.HERE / "main.py"}" --hidden'
            winreg.SetValueEx(key, RUN_NAME, 0, winreg.REG_SZ, command)
        else:
            try:
                winreg.DeleteValue(key, RUN_NAME)
            except OSError:
                pass


def app_icon():
    pix = QPixmap(64, 64)
    pix.fill(Qt.GlobalColor.transparent)
    p = QPainter(pix)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setPen(QPen(QColor(config.RED), 8))
    p.setBrush(QColor("white"))
    p.drawRoundedRect(6, 6, 52, 52, 8, 8)
    font = QFont(config.FONT_FAMILY)
    font.setPixelSize(38)
    font.setBold(True)
    p.setFont(font)
    p.setPen(QColor(config.RED))
    p.drawText(QRect(0, 0, 64, 64), Qt.AlignmentFlag.AlignCenter, "א")
    p.end()
    return QIcon(pix)


class Signals(QObject):
    done = pyqtSignal(int, str, object)
    update = pyqtSignal(str, object, bool)      # מה קרה בבדיקת העדכון, פרטים, והאם המשתמש ביקש אותה


class TranslatorWindow(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(WINDOW_TITLE)
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setMouseTracking(True)
        self.setMinimumSize(MIN_WIDTH, MIN_HEIGHT)

        self.engine = GoogleEngine() if config.ENGINE == "gemini" else TranslateEngine()
        threading.Thread(target=self.engine.warmup, daemon=True).start()
        self.signals = Signals()
        self.signals.done.connect(self._on_done)
        self.signals.update.connect(self._on_update)

        self.enabled = True
        self.quitting = False
        self.told_hidden = False       # ההסבר "אני ליד השעון" מוצג פעם אחת בלבד
        self.notice = None             # הודעת הפרטיות, כל עוד היא פתוחה (עד "הבנתי" לא שולחים כלום)
        self.about_box = None
        self.update_box = None
        self.update_busy = False       # בדיקה או הורדה של עדכון באמצע
        self.offered = None            # הגרסה שכבר הוצעה בהפעלה הזו (לא מציעים שוב לבד)
        self.keep_place = True         # לזכור מיקום וגודל להפעלה הבאה (לא כשהמיקום נכפה לבדיקה)
        self.saved_place = None        # מה שכבר כתוב בקובץ, כדי לא לכתוב שוב בלי צורך
        self.excluded = False         # האם Windows מסתיר את החלון מהצילומים שלנו
        self.shown = []                # התרגומים שמוצגים כרגע
        self.result = None             # התרגומים של התוכן האחרון שנשלח
        self.busy = False
        self.failed = False            # הבקשה האחרונה נכשלה (רשת/חסימה) — מנסים שוב אחרי המרווח
        self.gen = 0                  # מספר רץ; תשובה ישנה מ-Google נזרקת
        self.pending_arr = None
        self.sig_sent = None
        self.prev_sig = None
        self.calm_ticks = 0
        self.mask = np.zeros((64, 64), bool)   # משבצות "רועשות" שלא נחשבות שינוי
        self.prev_sent_sig = None
        self.pending_auto = False
        self.last_geometry = None
        self.last_texts = None
        self.gap = config.MIN_GAP_S
        self.last_send = 0.0
        self.sends = deque()
        self.cache = OrderedDict()
        self.status = "גרור אותי מעל טקסט באנגלית"
        self.hover = None
        self.debug_n = 0

        self.settle = QTimer(self, singleShot=True, timeout=self._on_settle)
        self.watch = QTimer(self, interval=config.WATCH_MS, timeout=self._on_watch)
        self.status_timer = QTimer(self, singleShot=True, timeout=lambda: self._set_status(""))

        geo = os.environ.get("ST_GEOMETRY")
        place = None if geo else saved_place()
        if geo:
            self.keep_place = False
            self.setGeometry(*[int(v) for v in geo.split(",")])
        elif place:
            self.setGeometry(place)
        else:
            screen = QGuiApplication.primaryScreen().availableGeometry()
            self.setGeometry(screen.center().x() - 280, screen.center().y() - 180, 560, 360)

    # ---------- הפעלה ----------
    def start(self, hidden=False):
        hwnd = int(self.winId())
        self._make_tray()
        if not hidden:
            self.show_square()
        if config.FROZEN:               # גרסת הפיתוח לא מתעדכנת לבד
            first = 3 if DEBUG_DIR else config.UPDATE_FIRST_S
            QTimer.singleShot(first * 1000, self.check_update)
            self.update_timer = QTimer(self, interval=config.UPDATE_EVERY_H * 3600 * 1000, timeout=self.check_update)
            self.update_timer.start()
        if not user32.RegisterHotKey(hwnd, HOTKEY_ID, config.HOTKEY_MODIFIERS | MOD_NOREPEAT, config.HOTKEY_KEY):
            self._set_status(f"קיצור המקלדת {config.HOTKEY_LABEL} תפוס", config.MESSAGE_MS)
            if hidden:      # אין ריבוע שיציג את ההודעה
                self.tray.showMessage(WINDOW_TITLE, f"קיצור המקלדת {config.HOTKEY_LABEL} תפוס על ידי תוכנה אחרת. "
                                      "אפשר להציג את הריבוע בלחיצה על הסמל הזה.",
                                      QSystemTrayIcon.MessageIcon.NoIcon, 6000)

    def _make_tray(self):
        self.tray = QSystemTrayIcon(app_icon(), self)
        self.tray.setToolTip(f"{WINDOW_TITLE}  ({config.HOTKEY_LABEL})")
        self.tray_menu = QMenu()
        self.tray_menu.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        self.tray_menu.addAction(f"הצג / הסתר את הריבוע   {config.HOTKEY_LABEL}", self.flip)
        auto = self.tray_menu.addAction("לעלות עם המחשב")
        auto.setCheckable(True)
        auto.setChecked(autostart_enabled())
        auto.toggled.connect(set_autostart)
        self.tray_menu.addAction("בדוק אם יש גרסה חדשה", lambda: self.check_update(manual=True))
        self.tray_menu.addAction("אודות", self.about)
        self.tray_menu.addSeparator()
        self.tray_menu.addAction("יציאה", self.quit)
        self.tray.setContextMenu(self.tray_menu)
        self.tray.activated.connect(
            lambda reason: self.flip() if reason == QSystemTrayIcon.ActivationReason.Trigger else None)
        self.tray.show()

    def show_square(self):
        self.show()
        self.raise_()
        if not NO_EXCLUDE and not self.excluded:
            self.excluded = bool(user32.SetWindowDisplayAffinity(int(self.winId()), WDA_EXCLUDEFROMCAPTURE))
        self.enabled = True
        self._drop_request()
        self.shown, self.result, self.sig_sent = [], None, None
        self._set_status("")
        self.watch.start()
        self.settle.start(config.SETTLE_MS)
        self._privacy_notice()

    def _privacy_notice(self):
        """בפעם הראשונה שהריבוע מוצג: מה נשלח ל-Google. עד שסוגרים את ההודעה לא מתרגמים."""
        if self.notice or DEBUG_DIR or config.PRIVACY_MARK.exists():
            return
        box = QMessageBox(QMessageBox.Icon.Information, WINDOW_TITLE, "כדאי לדעת לפני שמתחילים")
        box.setInformativeText(PRIVACY_SENT.get(config.ENGINE, PRIVACY_SENT["translate"]) + "\n\n" + PRIVACY_ADVICE)
        box.setWindowIcon(app_icon())
        box.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        box.addButton("הבנתי", QMessageBox.ButtonRole.AcceptRole)
        box.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint)      # הריבוע תמיד למעלה; שלא יסתיר אותה
        box.setModal(False)
        box.finished.connect(self._privacy_done)
        self.notice = box
        box.show()

    def _privacy_done(self, *_):
        self.notice = None
        try:
            config.PRIVACY_MARK.touch()
        except OSError:
            pass                        # אין הרשאת כתיבה: ההודעה תוצג שוב בהפעלה הבאה
        if self.isVisible() and self.enabled:
            self.settle.start(config.SETTLE_MS)

    def about(self):
        if self.about_box:
            self.about_box.raise_()
            self.about_box.activateWindow()
            return
        box = QMessageBox(QMessageBox.Icon.NoIcon, f"אודות {WINDOW_TITLE}", WINDOW_TITLE)
        box.setInformativeText(about_text())
        box.setIconPixmap(app_icon().pixmap(48, 48))
        box.setWindowIcon(app_icon())
        box.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        box.addButton("סגור", QMessageBox.ButtonRole.AcceptRole)
        box.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint)
        box.setModal(False)
        box.finished.connect(lambda *_: setattr(self, "about_box", None))
        self.about_box = box
        box.show()

    # ---------- עדכונים ----------
    def check_update(self, manual=False):
        if self.update_busy:
            return
        self.update_busy = True
        self._debug(f"update check ({'manual' if manual else 'auto'})")

        def work():
            try:
                found = updater.find()
                self.signals.update.emit("found" if found else "none", found, manual)
            except Exception as e:
                self.signals.update.emit("error", repr(e), manual)
        threading.Thread(target=work, daemon=True).start()

    def _fetch_update(self, version, url):
        self.update_busy = True
        self._tell("מוריד את הגרסה החדשה…")

        def work():
            try:
                self.signals.update.emit("ready", updater.fetch(url, version), True)
            except Exception as e:
                self.signals.update.emit("failed", repr(e), True)
        threading.Thread(target=work, daemon=True).start()

    def _tell(self, text):
        self.tray.showMessage(WINDOW_TITLE, text, QSystemTrayIcon.MessageIcon.NoIcon, 6000)

    def _on_update(self, kind, detail, manual):
        self.update_busy = False
        self._debug(f"update {kind} {detail if kind != 'ready' else ''}")
        if kind == "found":
            version, url = detail
            if manual or version != self.offered:
                self.offered = version
                self._offer_update(version, url)
        elif kind == "none" and manual:
            self._tell(f"הגרסה שלך ({config.VERSION}) היא העדכנית.")
        elif kind == "error" and manual:
            self._tell("לא הצלחתי לבדוק כרגע אם יש גרסה חדשה (אין חיבור ל-GitHub).")
        elif kind == "ready":
            self.save_place()
            self._debug("update install")
            try:
                updater.install(detail)
            except OSError as e:
                self._on_update("failed", repr(e), True)
        elif kind == "failed":
            self._tell(f"העדכון לא הותקן. אפשר להוריד אותו ידנית: github.com/{config.REPO}")

    def _offer_update(self, version, url):
        if self.update_box:
            self.update_box.raise_()
            return
        box = QMessageBox(QMessageBox.Icon.NoIcon, f"עדכון {WINDOW_TITLE}", f"יש גרסה חדשה: {version}")
        if config.FROZEN:
            box.setInformativeText(f"הגרסה שלך: {updater.current_version()}\n\n"
                                   "להתקין אותה עכשיו? התוכנה תיסגר לרגע ותיפתח מחדש.")
            yes = box.addButton("התקן", QMessageBox.ButtonRole.AcceptRole)
            box.addButton("לא עכשיו", QMessageBox.ButtonRole.RejectRole)
            box.setDefaultButton(yes)
        else:
            yes = None
            box.setInformativeText(f"זו גרסת הפיתוח ({config.VERSION}); היא לא מתעדכנת לבד.")
            box.addButton("סגור", QMessageBox.ButtonRole.RejectRole)
        box.setIconPixmap(app_icon().pixmap(48, 48))
        box.setWindowIcon(app_icon())
        box.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        box.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint)
        box.setModal(False)

        def closed(*_):
            accepted = yes is not None and box.clickedButton() is yes
            self.update_box = None
            if accepted:
                self._fetch_update(version, url)
        box.finished.connect(closed)
        self.update_box = box
        box.show()

    def save_place(self):
        """זוכרים איפה הריבוע ובאיזה גודל, כדי שייפתח שם גם בהפעלה הבאה."""
        if not self.keep_place:
            return
        g = self.geometry()
        text = f"{g.x()},{g.y()},{g.width()},{g.height()}"
        if text == self.saved_place:
            return
        try:
            config.PLACE_FILE.write_text(text, encoding="utf-8")
            self.saved_place = text
        except OSError:
            pass                        # אין הרשאת כתיבה: בהפעלה הבאה הריבוע ייפתח במרכז

    def hide_square(self):
        """הריבוע נעלם אבל התוכנה נשארת ליד השעון, מוכנה לקיצור המקלדת."""
        self.save_place()
        self.watch.stop()
        self.settle.stop()
        self._drop_request()
        self.shown, self.result, self.sig_sent = [], None, None
        self.hide()
        if not self.told_hidden:
            self.told_hidden = True
            self.tray.showMessage(WINDOW_TITLE, f"אני עדיין כאן. {config.HOTKEY_LABEL} מחזיר את הריבוע.",
                                  QSystemTrayIcon.MessageIcon.NoIcon, 4000)

    def flip(self):
        if self.isVisible():
            self.hide_square()
        else:
            self.show_square()

    def quit(self):
        self.quitting = True
        self.save_place()
        user32.UnregisterHotKey(int(self.winId()), HOTKEY_ID)
        self.tray.hide()
        QApplication.quit()

    def nativeEvent(self, event_type, message):
        if event_type == b"windows_generic_MSG":
            msg = wintypes.MSG.from_address(int(message))
            if msg.message == WM_HOTKEY and msg.wParam == HOTKEY_ID:
                self._debug("hotkey")
                self.flip()
                return True, 0
            if msg.message == WM_SHOW:
                self._debug("second launch -> show")
                self.show_square()
                return True, 0
        return False, 0

    def toggle(self):
        self.enabled = not self.enabled
        self._debug(f"toggle -> {'on' if self.enabled else 'off'}")
        self._drop_request()
        self.shown, self.result, self.sig_sent = [], None, None
        if self.enabled:
            self._set_status("")
            self.settle.start(config.SETTLE_MS)
        else:
            self.settle.stop()
            self._set_status("כבוי")
        self.update()

    # ---------- גיאומטריה ----------
    def _region(self):
        b = config.BORDER
        top_left = self.mapToGlobal(QPoint(b, config.BAR_HEIGHT + b))
        return QRect(top_left.x(), top_left.y(), self.width() - 2 * b,
                     self.height() - config.BAR_HEIGHT - 2 * b)

    def _grab(self):
        r = self._region()
        screen = QGuiApplication.screenAt(r.center()) or QGuiApplication.primaryScreen()
        g = screen.geometry()
        return screen.grabWindow(0, r.x() - g.x(), r.y() - g.y(), r.width(), r.height()).toImage()

    def moveEvent(self, event):
        self._geometry_changed()

    def resizeEvent(self, event):
        self._geometry_changed()

    def _geometry_changed(self):
        geometry = self.geometry()
        if not self.enabled or geometry == self.last_geometry:
            return
        self.last_geometry = geometry
        self._debug(f"moved/resized {geometry.x()},{geometry.y()} {geometry.width()}x{geometry.height()}")
        self._drop_request()
        self.shown, self.result, self.sig_sent = [], None, None
        self.gap = config.MIN_GAP_S
        self.mask[:] = False
        self.update()
        self.settle.start(config.SETTLE_MS)

    # ---------- מתי מתרגמים ----------
    def _on_settle(self):
        if not self.enabled or self.notice:
            return
        if user32.GetAsyncKeyState(0x01) & 0x8000:      # עדיין גוררים
            self.settle.start(config.SETTLE_MS)
            return
        self.save_place()       # גם כאן, לא רק בהסתרה: כיבוי פתאומי או התקנת גרסה חדשה לא יאבדו את המיקום
        if not self._under_minute_cap():
            self._set_status("רגע, ממתין למכסה של Google…")
            self.settle.start(3000)
            return
        self.prev_sig = None
        self._translate(self._grab(), auto=False)

    def _on_watch(self):
        if not self.enabled or not self.excluded or self.settle.isActive() or self.sig_sent is None:
            return
        image = self._grab()
        sig = signature(image)
        stable = self.prev_sig is not None and changed_cells(sig, self.prev_sig, self.mask) < SMALL_CHANGE
        self.prev_sig = sig
        change = changed_cells(sig, self.sig_sent, self.mask)
        if change < SMALL_CHANGE:
            # התוכן לא השתנה. אם התרגום הוסתר (למשל בגלילה שלא הזיזה כלום) — מחזירים אותו.
            self.calm_ticks += 1
            if not self.shown and self.result and not self.busy and self.calm_ticks >= 2:
                self.shown = self.result
                self.update()
            # תקלה זמנית (אין רשת, Google חסם): מנסים שוב לבד, במרווחים שהולכים וגדלים
            if self.failed and not self.busy and time.monotonic() - self.last_send >= self.gap \
                    and self._under_minute_cap():
                self._debug("retry after error")
                self._translate(image, auto=False)
            return
        self.calm_ticks = 0
        if change >= BIG_CHANGE and (self.shown or self.busy):
            # תוכן אחר לגמרי: התרגום הישן כבר לא שייך למה שרואים
            self._drop_request()
            self.shown = []
            self._set_status("")
            self.update()
        if stable and not self.busy and time.monotonic() - self.last_send >= self.gap \
                and self._under_minute_cap():
            self._debug(f"content changed ({change} cells)")
            self._translate(image, auto=True)

    def _under_minute_cap(self):
        now = time.monotonic()
        while self.sends and now - self.sends[0] > 60:
            self.sends.popleft()
        return len(self.sends) < config.MAX_PER_MINUTE

    def _drop_request(self):
        self.gen += 1
        self.busy = False
        self.pending_arr = None

    def _translate(self, image, auto):
        self._drop_request()
        self.failed = False
        arr = renderer.image_to_array(image)
        key = hashlib.md5(arr.tobytes()).hexdigest()
        self.prev_sent_sig = self.sig_sent if auto else None
        self.sig_sent = signature(image)
        self.calm_ticks = 0
        self.pending_arr = arr
        self.pending_auto = auto
        if key in self.cache:
            self.cache.move_to_end(key)
            self._debug("cache")
            self._on_done(self.gen, key, self.cache[key])
            return
        self.busy = True
        self._set_status("מתרגם…")
        self.last_send = time.monotonic()
        self.sends.append(self.last_send)
        self._debug("send")
        threading.Thread(target=self._work, args=(self.gen, key, image.copy()), daemon=True).start()

    def _work(self, gen, key, image):
        try:
            started = time.monotonic()
            result = self.engine.translate(image)
            self._debug(f"answered in {time.monotonic() - started:.1f}s ({self.engine.last_model})")
        except EngineError as e:
            result = e
        except Exception as e:
            result = EngineError("other", repr(e))
        self.signals.done.emit(gen, key, result)

    def _on_done(self, gen, key, result):
        if isinstance(result, list):
            self.cache[key] = result
            while len(self.cache) > config.CACHE_SIZE:
                self.cache.popitem(last=False)
        if gen != self.gen:
            self._debug("stale result ignored")
            return
        self.busy = False
        arr, self.pending_arr = self.pending_arr, None
        if isinstance(result, EngineError):
            self._debug(f"error {result.kind}")
            # אחרי תקלה לא מנסים שוב ושוב: המרווח גדל עד שהתוכן באמת משתנה או שמזיזים את הריבוע
            self.gap = min(max(self.gap * 2, 60.0 if result.kind == "rate" else 10.0), config.MAX_GAP_S)
            self.shown, self.result = [], None
            self.failed = result.kind in ("offline", "rate", "blocked", "other")
            self._set_status(MESSAGES.get(result.kind, MESSAGES["other"]), config.MESSAGE_MS)
        elif not result:
            self._debug("result 0")
            self.shown, self.result = [], None
            self._set_status("לא נמצא כאן טקסט באנגלית", config.MESSAGE_MS)
        else:
            self._debug(f"result {len(result)}")
            r = self._region()
            self.shown = self.result = renderer.style_blocks(arr, result, r.width(), r.height())
            self._set_status("")
        # תוכן ש"זז" כל הזמן אבל הטקסט בו זהה (וידאו, אנימציה) — מאטים את הקצב.
        texts = [b.text for b in result] if isinstance(result, list) else None
        if self.pending_auto and texts is not None and texts == self.last_texts:
            self.gap = min(self.gap * 2, config.MAX_GAP_S)
            self._learn_noise()
        elif texts is not None:
            self.gap = config.MIN_GAP_S
        self.last_texts = texts
        self.update()
        self._debug_frame(arr)

    def _learn_noise(self):
        """שלחנו שוב וקיבלנו אותו טקסט: מה שהשתנה הוא רק "רעש" (אנימציה, סמן). מתעלמים ממנו מעכשיו."""
        if self.prev_sent_sig is None or self.sig_sent is None:
            return
        noise = np.abs(self.sig_sent - self.prev_sent_sig) > 16
        if noise.sum() >= BIG_CHANGE:
            return
        grown = noise.copy()
        grown[1:] |= noise[:-1]
        grown[:-1] |= noise[1:]
        grown[:, 1:] |= noise[:, :-1]
        grown[:, :-1] |= noise[:, 1:]
        self.mask |= grown
        self._debug(f"learned noise ({int(self.mask.sum())} cells ignored)")

    # ---------- הודעות ----------
    def _set_status(self, text, ms=0):
        self.status = text
        self.status_timer.stop()
        if ms:
            self.status_timer.start(ms)
        self.update()

    # ---------- ציור ----------
    def _close_rect(self):
        return QRect(0, 0, config.BAR_HEIGHT, config.BAR_HEIGHT)

    def _toggle_rect(self):
        return QRect(config.BAR_HEIGHT, 0, config.BAR_HEIGHT, config.BAR_HEIGHT)

    def paintEvent(self, event):
        p = QPainter(self)
        w, h, bar, b, grip = self.width(), self.height(), config.BAR_HEIGHT, config.BORDER, config.GRIP
        # אדום = עובד/מחכה, ירוק = התרגום מוצג
        red = QColor(config.GREEN if self.shown and not self.busy else config.RED)

        # אזור אחיזה כמעט שקוף, כדי שיהיה אפשר לתפוס את המסגרת הדקה
        ghost = QColor(255, 255, 255, 1)
        p.fillRect(0, bar, grip, h - bar, ghost)
        p.fillRect(w - grip, bar, grip, h - bar, ghost)
        p.fillRect(0, h - grip, w, grip, ghost)

        # המסגרת
        p.fillRect(0, bar, w, b, red)
        p.fillRect(0, bar, b, h - bar, red)
        p.fillRect(w - b, bar, b, h - bar, red)
        p.fillRect(0, h - b, w, b, red)

        # הפס העליון
        p.fillRect(0, 0, w, bar, red if self.enabled else QColor(config.BAR_OFF))
        hover = QColor(255, 255, 255, 50)
        if self.hover == "close":
            p.fillRect(self._close_rect(), hover)
        if self.hover == "toggle":
            p.fillRect(self._toggle_rect(), hover)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        white = QColor("white")
        p.setPen(QPen(white, 1.6))
        c = self._close_rect().center()
        p.drawLine(c.x() - 5, c.y() - 5, c.x() + 5, c.y() + 5)
        p.drawLine(c.x() - 5, c.y() + 5, c.x() + 5, c.y() - 5)
        c = self._toggle_rect().center()
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(white)
        if self.enabled:
            p.drawRect(QRectF(c.x() - 5, c.y() - 6, 3.5, 12))
            p.drawRect(QRectF(c.x() + 1.5, c.y() - 6, 3.5, 12))
        else:
            p.drawPolygon(QPolygonF([QPointF(c.x() - 4, c.y() - 6), QPointF(c.x() - 4, c.y() + 6),
                                     QPointF(c.x() + 6, c.y())]))

        font = QFont(config.FONT_FAMILY)
        font.setPixelSize(13)
        p.setFont(font)
        p.setPen(white)
        text_rect = QRectF(2 * bar + 6, 0, w - 2 * bar - 16, bar)
        text = self.status or f"תרגום מסך  ·  {config.HOTKEY_LABEL}"
        text = QFontMetricsF(font).elidedText(text, Qt.TextElideMode.ElideLeft, text_rect.width())
        p.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        p.drawText(text_rect, Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight, text)

        # התרגומים
        if self.shown:
            p.setClipRect(b, bar + b, w - 2 * b, h - bar - 2 * b)
            p.translate(b, bar + b)
            renderer.paint_blocks(p, self.shown)

    # ---------- עכבר ----------
    def _edges(self, pos):
        x, y, w, h = pos.x(), pos.y(), self.width(), self.height()
        edges = Qt.Edge(0)
        if y > config.BAR_HEIGHT:
            if x < config.GRIP:
                edges |= Qt.Edge.LeftEdge
            elif x >= w - config.GRIP:
                edges |= Qt.Edge.RightEdge
        if y >= h - config.GRIP:
            edges |= Qt.Edge.BottomEdge
        elif y < 4 and x > 2 * config.BAR_HEIGHT:
            edges |= Qt.Edge.TopEdge
        return edges

    def mouseMoveEvent(self, event):
        pos = event.position().toPoint()
        hover = "close" if self._close_rect().contains(pos) else \
                "toggle" if self._toggle_rect().contains(pos) else None
        if hover != self.hover:
            self.hover = hover
            self.setToolTip({"close": f"הסתר ({config.HOTKEY_LABEL} מחזיר)", "toggle": "השהה / המשך"}.get(hover, ""))
            self.update()
        edges = self._edges(pos)
        L, R, T, B = Qt.Edge.LeftEdge, Qt.Edge.RightEdge, Qt.Edge.TopEdge, Qt.Edge.BottomEdge
        if edges in (L | B,):
            shape = Qt.CursorShape.SizeBDiagCursor
        elif edges in (R | B,):
            shape = Qt.CursorShape.SizeFDiagCursor
        elif edges in (L, R):
            shape = Qt.CursorShape.SizeHorCursor
        elif edges in (T, B):
            shape = Qt.CursorShape.SizeVerCursor
        elif pos.y() < config.BAR_HEIGHT and not hover:
            shape = Qt.CursorShape.SizeAllCursor
        else:
            shape = Qt.CursorShape.ArrowCursor
        self.setCursor(shape)

    def leaveEvent(self, event):
        if self.hover:
            self.hover = None
            self.update()

    def mousePressEvent(self, event):
        if event.button() != Qt.MouseButton.LeftButton:
            return
        pos = event.position().toPoint()
        if self._close_rect().contains(pos):
            self.hide_square()
        elif self._toggle_rect().contains(pos):
            self.toggle()
        elif self._edges(pos):
            self.windowHandle().startSystemResize(self._edges(pos))
        elif pos.y() < config.BAR_HEIGHT:
            self.windowHandle().startSystemMove()

    def wheelEvent(self, event):
        """גלילה מעל תרגום: מסתירים אותו ומעבירים את הגלילה לחלון שמתחת."""
        b = config.BORDER
        pos = event.position() - QPointF(b, config.BAR_HEIGHT + b)
        if not any(renderer.cover_of(block.rect).contains(pos) for block in self.shown):
            return
        delta = event.angleDelta().y()
        self.shown = []
        self.calm_ticks = 0
        self.repaint()
        QTimer.singleShot(40, lambda: user32.mouse_event(0x0800, 0, 0, delta, 0))

    def closeEvent(self, event):
        if not self.quitting:           # Alt+F4 רק מסתיר; יציאה אמיתית מהתפריט שליד השעון
            event.ignore()
            self.hide_square()

    # ---------- בדיקות (רק כש-ST_DEBUG_DIR מוגדר) ----------
    def _debug(self, text):
        if DEBUG_DIR:
            with open(os.path.join(DEBUG_DIR, "events.log"), "a", encoding="utf-8") as f:
                f.write(f"{time.strftime('%H:%M:%S')} {text}\n")

    def _debug_frame(self, arr):
        if not DEBUG_DIR or arr is None:
            return
        h, w = arr.shape[:2]
        r = self._region()
        frame = QImage(arr.tobytes(), w, h, w * 3, QImage.Format.Format_RGB888).scaled(r.width(), r.height())
        p = QPainter(frame)
        if self.shown:
            renderer.paint_blocks(p, self.shown)
        p.end()
        self.debug_n += 1
        frame.save(os.path.join(DEBUG_DIR, f"frame_{self.debug_n:02d}.png"))
        self._debug(f"frame_{self.debug_n:02d} status={self.status!r} shown={len(self.shown)}")


def _log_crash(kind, value, tb):
    path = config.HERE / "error.log"
    try:                                                # שלא יגדל בלי גבול: משאירים רק את הסוף
        if path.stat().st_size > config.ERROR_LOG_MAX:
            tail = path.read_bytes()[-config.ERROR_LOG_MAX // 2:]
            path.write_bytes(tail[tail.find(b"\n") + 1:])
    except OSError:
        pass
    with open(path, "a", encoding="utf-8") as f:
        f.write(time.strftime("%Y-%m-%d %H:%M:%S\n"))
        traceback.print_exception(kind, value, tb, file=f)


def main():
    sys.excepthook = _log_crash
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateMutexW(None, False, "ScreenTranslateHe.SingleInstance")
    if ctypes.get_last_error() == 183:                  # כבר רץ: רק מבקשים ממנו להציג את הריבוע
        hwnd = user32.FindWindowW(None, WINDOW_TITLE)
        if hwnd and "--hidden" not in sys.argv:
            user32.PostMessageW(hwnd, WM_SHOW, 0, 0)
        return
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    window = TranslatorWindow()
    # כיבוי/יציאה מ-Windows: לא מעכבים אותו בגלל שהחלון "מסרב להיסגר"
    app.commitDataRequest.connect(lambda *_: (setattr(window, "quitting", True), window.save_place()))
    window.start(hidden="--hidden" in sys.argv)
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
