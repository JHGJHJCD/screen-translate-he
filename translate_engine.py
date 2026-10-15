"""מנוע "Google Translate": זיהוי הטקסט נעשה במחשב (Windows), והתרגום ב-Google Translate.

למה כך: תרגום התמונות של אתר Google Translate מחזיר "לא זוהה טקסט" ברשת הזו (נבדק 3/10/2026),
אבל תרגום הטקסט שלו עובד, מהיר, ובלי מכסה יומית. לכן התמונה עצמה לא יוצאת מהמחשב — רק הטקסט.
"""
import asyncio
import json
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import OrderedDict

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QImage

from google_engine import Block, EngineError

TRANSLATE_URL = "https://translate.googleapis.com/translate_a/single?client=gtx&sl=en&tl=iw&dt=t"
WEB_URL = "https://translate.google.com/_/TranslateWebserverUi/data/batchexecute?rpcids=MkEWBc&hl=en&rt=c"
WEB_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/126 Safari/537.36"
WEB_FALLBACK_S = 1800     # כמה זמן נשארים בערוץ של האתר אחרי שהערוץ המהיר נחסם
NIKUD = re.compile(r"[֑-ׇ]")
MIN_TEXT_HEIGHT = 30     # אם האותיות קטנות מזה (בפיקסלים) מגדילים את התמונה לפני הזיהוי
TEXT_CACHE = 600
BLOCK_SPLITS = 10         # כמה פעמים מותר לחצות קבוצה שנטפרי חסם, עד שמוותרים על המסך כולו
BLOCK_RETRY_S = 600       # כמה זמן לא שולחים שוב פסקה שנחסמה
HEBREW = re.compile(r"[֐-׿]")
DESCENDER = re.compile(r"[gjpqyQ,;()\[\]{}|@$_/]")   # מילה עם אות שיורדת מתחת לקו הבסיס
TALL = re.compile(r"[A-Z0-9bdfhkltij'\"!?#%&]")       # מילה עם אות גבוהה (לא רק בגובה x)
WORD = re.compile(r"[A-Za-z]{2,}")


class TranslateEngine:
    def __init__(self):
        self._ocr = None
        self._lock = threading.Lock()
        self._texts = OrderedDict()     # אנגלית -> עברית (בזיכרון בלבד)
        self._web_until = 0.0           # עד מתי משתמשים בערוץ של האתר במקום בערוץ המהיר
        self._state = threading.Lock()  # שומר על _texts ו-_blocked כשכמה בקשות רצות במקביל
        self._blocked = {}              # פסקה שנטפרי חסם -> עד מתי לא שולחים אותה שוב
        self._no_split_until = 0.0      # הכול נחסם (לא פסקה אחת): עד אז לא מנסים לחצות
        self.block_detail = ""          # מה שנטפרי ענה בחסימה האחרונה (ליומן; בלי הטקסט שנשלח)
        self.last_model = "Windows OCR + Google Translate"

    def warmup(self):
        try:
            self._get_ocr()
        except EngineError:
            pass

    def _get_ocr(self):
        with self._lock:
            if self._ocr is None:
                import truststore
                truststore.inject_into_ssl()  # נטפרי
                from winrt.windows.globalization import Language
                from winrt.windows.media.ocr import OcrEngine
                self._ocr = OcrEngine.try_create_from_language(Language("en-US"))
                if self._ocr is None:           # מחשב אחר: אולי מותקנת אנגלית אחרת (en-GB)
                    for language in OcrEngine.available_recognizer_languages:
                        if language.language_tag.lower().startswith("en"):
                            self._ocr = OcrEngine.try_create_from_language(language)
                            break
                if self._ocr is None:
                    raise EngineError("no_ocr", "Windows OCR for English is not installed")
            return self._ocr

    # ---------- זיהוי ----------
    def _recognize(self, image):
        from winrt.windows.graphics.imaging import BitmapPixelFormat, SoftwareBitmap
        from winrt.windows.storage.streams import DataWriter

        ocr = self._get_ocr()
        image = image.convertToFormat(QImage.Format.Format_ARGB32)
        bits = image.constBits()
        bits.setsize(image.sizeInBytes())
        writer = DataWriter()
        writer.write_bytes(bytes(bits))
        bitmap = SoftwareBitmap.create_copy_from_buffer(
            writer.detach_buffer(), BitmapPixelFormat.BGRA8, image.width(), image.height())

        async def run():
            return await ocr.recognize_async(bitmap)

        result = asyncio.run(run())
        lines = []
        for line in result.lines:
            words = [(w.text, w.bounding_rect.x, w.bounding_rect.y,
                      w.bounding_rect.width, w.bounding_rect.height) for w in line.words]
            lines.extend(_split_line(words))
        return lines

    def translate(self, image):
        # אותיות קטנות מזוהות טוב יותר כשמגדילים את התמונה
        scale = 2 if image.devicePixelRatio() < 1.4 else 1
        if scale * max(image.width(), image.height()) > 4000:
            scale = 1
        source = image if scale == 1 else image.scaled(
            image.width() * scale, image.height() * scale,
            Qt.AspectRatioMode.IgnoreAspectRatio, Qt.TransformationMode.SmoothTransformation)
        W, H = source.width(), source.height()

        paragraphs = _group([l for l in self._recognize(source) if looks_english(l["text"])])
        paragraphs = [p for p in paragraphs if WORD.search(p["text"])]
        if not paragraphs:
            return []
        hebrew = self._translate_texts([p["text"] for p in paragraphs])
        if not any(hebrew) and any(p["text"] in self._blocked for p in paragraphs):
            raise EngineError("blocked", self.block_detail)
        blocks = []
        for p, he in zip(paragraphs, hebrew):
            if not he or he == p["text"] or not HEBREW.search(he):
                continue
            rows = tuple((r["x0"] / W, r["top"] / H, r["x1"] / W, r["base"] / H) for r in p["rows"])
            blocks.append(Block(p["x0"] / W, p["y0"] / H, (p["x1"] - p["x0"]) / W,
                                (p["y1"] - p["y0"]) / H, p["text"], he, p["lines"], rows))
        return blocks

    # ---------- תרגום ----------
    def _translate_texts(self, texts):
        # בקשה ישנה (שהריבוע כבר ויתר עליה) יכולה לרוץ במקביל לחדשה, לכן הזיכרון המשותף נגיש רק תחת נעילה.
        # הרשת עצמה מחוץ לנעילה, כדי שבקשה איטית לא תעכב את החדשה.
        now = time.monotonic()
        with self._state:
            self._blocked = {t: until for t, until in self._blocked.items() if until > now}
            missing = [t for t in dict.fromkeys(texts) if t not in self._texts and t not in self._blocked]
            splits = BLOCK_SPLITS if now >= self._no_split_until else 0
        if missing:
            translated = self._translate_many(missing, [splits])
            with self._state:
                for src, he in zip(missing, translated):
                    if src not in self._blocked:
                        self._texts[src] = he.strip()
                answer = [self._texts.get(t, "") for t in texts]
                while len(self._texts) > TEXT_CACHE:
                    self._texts.popitem(last=False)
            return answer
        with self._state:
            return [self._texts.get(t, "") for t in texts]

    def _translate_many(self, texts, splits=None):
        """splits = [כמה חציות עוד מותרות] — של הבקשה הזו בלבד, לא משותף לבקשות אחרות."""
        if splits is None:
            splits = [BLOCK_SPLITS]
        try:
            if len(texts) == 1:
                return [self._request(texts[0])]
            translated = self._request("\n".join(texts)).split("\n")
        except EngineError as e:
            # נטפרי סורק את הטקסט שנשלח וחוסם את כל הבקשה בגלל פסקה אחת. מאתרים אותה בחצייה,
            # מדלגים עליה (נשארת באנגלית) ומתרגמים את השאר.
            if e.kind != "blocked":
                raise
            self.block_detail = str(e)[:600]
            if splits[0] <= 0:
                self._no_split_until = time.monotonic() + BLOCK_RETRY_S
                raise
            if len(texts) == 1:
                with self._state:
                    self._blocked[texts[0]] = time.monotonic() + BLOCK_RETRY_S
                return [""]
            splits[0] -= 1
            mid = len(texts) // 2
            return self._translate_many(texts[:mid], splits) + self._translate_many(texts[mid:], splits)
        if len(translated) == len(texts):
            return translated
        # Google איחד שורות — מחלקים לשניים ומנסים שוב (ולא שולחים עשרות בקשות אחת-אחת, שמביא לחסימה)
        mid = len(texts) // 2
        return self._translate_many(texts[:mid], splits) + self._translate_many(texts[mid:], splits)

    def _request(self, text):
        # הערוץ המהיר נחסם לפעמים ל-IP ("unusual traffic", 429) בזמן שהערוץ של האתר עצמו ממשיך לעבוד.
        if time.monotonic() >= self._web_until:
            try:
                return self._fetch(text, web=False)
            except EngineError as e:
                if e.kind != "rate":
                    raise
                self._web_until = time.monotonic() + WEB_FALLBACK_S
        self.last_model = "Windows OCR + Google Translate (web)"
        return self._fetch(text, web=True)

    def _fetch(self, text, web):
        if web:
            inner = json.dumps([[text, "en", "iw", 1], []])
            body = urllib.parse.urlencode({"f.req": json.dumps([[["MkEWBc", inner, None, "generic"]]])})
            request = urllib.request.Request(WEB_URL, data=body.encode("utf-8"), headers={
                "User-Agent": WEB_AGENT, "Content-Type": "application/x-www-form-urlencoded;charset=UTF-8"})
        else:
            body = urllib.parse.urlencode({"q": text}).encode("utf-8")
            request = urllib.request.Request(TRANSLATE_URL, data=body, headers={"User-Agent": "Mozilla/5.0"})
        try:
            with urllib.request.urlopen(request, timeout=15) as response:
                raw = response.read().decode("utf-8")
            if web:
                line = next(l for l in raw.split("\n") if '"MkEWBc"' in l)
                data = json.loads(json.loads(line)[0][2])
                # תרגום של מילה בודדת חוזר מנוקד — מורידים את הניקוד
                text = ""
                for part in data[1][0][0][5]:       # משפטים; רווח ביניהם לא תמיד חוזר
                    if part[0]:
                        glue = " " if text and not text[-1].isspace() and not part[0][0].isspace() else ""
                        text += glue + part[0]
                return NIKUD.sub("", text)
            data = json.loads(raw)
            return "".join(part[0] for part in data[0] if part[0])
        except urllib.error.HTTPError as e:
            detail = e.read(600).decode("utf-8", "replace")
            if "google.com%2fsorry" in detail.lower() or "google.com/sorry" in detail.lower():
                # Google הגביל את הקצב והפנה לדף "sorry", ונטפרי חסם את הדף הזה: זו הגבלת קצב, לא טקסט חסום
                raise EngineError("rate", f"{e.code} google sorry")
            if e.code == 418 or "netfree" in detail.lower():
                raise EngineError("blocked", detail)
            raise EngineError("rate" if e.code == 429 else "other", f"{e.code} {detail}")
        except (urllib.error.URLError, OSError) as e:
            raise EngineError("offline", repr(e)[:200])
        except (ValueError, IndexError, TypeError, StopIteration) as e:
            raise EngineError("other", repr(e)[:200])


LETTERS = re.compile(r"[A-Za-z]+")
CAMEL = re.compile(r"[A-Z]?[a-z]+(?:[A-Z][a-z]+)*")       # Settings, GitHub, PyQt
Y_WORDS = set("by my fly try why sky gym shy dry cry spy sync rhythm myth lynx ply sly pry style".split())
# גרשיים בין אותיות ("O\"IJ"), או גרש שאינו קיצור אנגלי (don't, it's, we're, O'Connor)
HEBREW_MARKS = re.compile(r"[A-Za-z]\"[A-Za-z]|[A-Za-z]'(?!(?:s|t|re|ll|ve|d|m)\b)(?<!\bO')[A-Za-z]")


def _english_word(word):
    if len(word) == 1:
        return None
    if not (word.isupper() or CAMEL.fullmatch(word)):           # "nilVDl", "DblDb"
        return False
    lower = word.lower()
    if not re.search(r"[aeiou]", lower):                         # "nnnvn", "nmyn"
        return (word.isupper() and len(word) <= 5) or lower in Y_WORDS
    if lower.startswith("nn") or re.search(r"(.)\1\1", lower):
        return False
    return not (len(lower) > 2 and sum(c in "no" for c in lower) / len(lower) > 0.7)


def looks_english(text):
    """הזיהוי של Windows מכיר רק אנגלית, ועברית שעל המסך יוצאת ממנו ג'יבריש באותיות לטיניות
    ("nnnvn D'oopo nilVDl"). את זה לא מתרגמים — אחרת התרגום מצויר מעל העברית ומעוות אותה.
    הסימנים: הרבה n (ה/ח/ת/ת נקראות n), מילים בלי תנועות, אותיות גדולות באמצע מילה, גרשיים."""
    if HEBREW_MARKS.search(text):
        return False
    words = LETTERS.findall(text)
    verdict = [v for v in map(_english_word, words) if v is not None]
    if not verdict:
        return False
    letters = "".join(words)
    many_n = sum(c in "nN" for c in letters) / len(letters) >= 0.3 and len(letters) >= 4
    return sum(verdict) / len(verdict) >= 0.6 and not many_n


def _split_line(words):
    """שורה ש-Windows זיהה יכולה לכלול שני כפתורים רחוקים. מפצלים במקום שיש רווח גדול."""
    parts, current = [], []
    for word in words:
        if current:
            _, px, _, pw, ph = current[-1]
            if word[1] - (px + pw) > 1.6 * max(ph, word[4]):
                parts.append(current)
                current = []
        current.append(word)
    if current:
        parts.append(current)
    lines = []
    for part in parts:
        x0 = min(w[1] for w in part)
        y0 = min(w[2] for w in part)
        x1 = max(w[1] + w[3] for w in part)
        y1 = max(w[2] + w[4] for w in part)
        line = {"text": " ".join(w[0] for w in part), "x0": x0, "y0": y0, "x1": x1, "y1": y1}
        line.update(_baseline(part, y0, y1))
        line["rows"] = [dict(line)]
        lines.append(line)
    return lines


def _baseline(words, y0, y1):
    """איפה בדיוק השורה: קו הבסיס (תחתית האותיות בלי זנבות כמו g,p,y) וראש האותיות הגבוהות.
    המסגרת של כל מילה ש-Windows מחזיר צמודה לאותיות, לכן אפשר לחשב את זה מהמילים עצמן."""
    flat = [w[2] + w[4] for w in words if not DESCENDER.search(w[0])]
    if flat:
        base = sorted(flat)[len(flat) // 2]
    else:                                   # בכל המילים יש זנב: הזנב הוא כרבע מגובה השורה
        base = y1 - 0.22 * (y1 - y0)
    tall = [w[2] for w in words if TALL.search(w[0])]
    if tall:
        top = sorted(tall)[len(tall) // 2]
    else:                                   # רק אותיות בגובה x (כמו "over a"): אות גדולה גבוהה פי 1.4 בערך
        top = base - 1.4 * (base - y0)
    return {"top": top, "base": max(base, top + 1)}


def _group(lines):
    """מחברים שורות סמוכות של אותה פסקה לבלוק אחד, כדי שהמשפט יתורגם כמשפט שלם."""
    paragraphs = []
    for line in sorted(lines, key=lambda l: (l["y0"], l["x0"])):
        height = line["y1"] - line["y0"]
        if height <= 0:
            continue
        for p in reversed(paragraphs):
            gap = line["y0"] - p["y1"]
            same_size = 0.7 < height / p["line_h"] < 1.4
            aligned = abs(line["x0"] - p["x0"]) < 1.5 * height or \
                abs((line["x0"] + line["x1"]) - (p["x0"] + p["x1"])) < 2 * height
            if same_size and aligned and -0.3 * height < gap < 0.9 * height:
                p["text"] += " " + line["text"]
                p["x0"], p["x1"] = min(p["x0"], line["x0"]), max(p["x1"], line["x1"])
                p["y1"] = line["y1"]
                p["lines"] += 1
                p["rows"] += line.get("rows", [])
                break
        else:
            paragraphs.append(dict(line, lines=1, line_h=height, rows=list(line.get("rows", []))))
    return paragraphs
