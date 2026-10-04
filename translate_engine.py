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
HEBREW = re.compile(r"[֐-׿]")
WORD = re.compile(r"[A-Za-z]{2,}")


class TranslateEngine:
    def __init__(self):
        self._ocr = None
        self._lock = threading.Lock()
        self._texts = OrderedDict()     # אנגלית -> עברית (בזיכרון בלבד)
        self._web_until = 0.0           # עד מתי משתמשים בערוץ של האתר במקום בערוץ המהיר
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

        paragraphs = _group(self._recognize(source))
        paragraphs = [p for p in paragraphs if WORD.search(p["text"])]
        if not paragraphs:
            return []
        hebrew = self._translate_texts([p["text"] for p in paragraphs])
        blocks = []
        for p, he in zip(paragraphs, hebrew):
            if not he or he == p["text"] or not HEBREW.search(he):
                continue
            blocks.append(Block(p["x0"] / W, p["y0"] / H, (p["x1"] - p["x0"]) / W,
                                (p["y1"] - p["y0"]) / H, p["text"], he, p["lines"]))
        return blocks

    # ---------- תרגום ----------
    def _translate_texts(self, texts):
        missing = [t for t in dict.fromkeys(texts) if t not in self._texts]
        if missing:
            for src, he in zip(missing, self._translate_many(missing)):
                self._texts[src] = he.strip()
            while len(self._texts) > TEXT_CACHE:
                self._texts.popitem(last=False)
        return [self._texts.get(t, "") for t in texts]

    def _translate_many(self, texts):
        if len(texts) == 1:
            return [self._request(texts[0])]
        translated = self._request("\n".join(texts)).split("\n")
        if len(translated) == len(texts):
            return translated
        # Google איחד שורות — מחלקים לשניים ומנסים שוב (ולא שולחים עשרות בקשות אחת-אחת, שמביא לחסימה)
        mid = len(texts) // 2
        return self._translate_many(texts[:mid]) + self._translate_many(texts[mid:])

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
            detail = e.read(300).decode("utf-8", "replace")
            if e.code == 418 or "netfree" in detail.lower():
                raise EngineError("blocked", detail)
            raise EngineError("rate" if e.code == 429 else "other", f"{e.code} {detail}")
        except (urllib.error.URLError, OSError) as e:
            raise EngineError("offline", repr(e)[:200])
        except (ValueError, IndexError, TypeError, StopIteration) as e:
            raise EngineError("other", repr(e)[:200])


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
        lines.append({"text": " ".join(w[0] for w in part), "x0": x0, "y0": y0, "x1": x1, "y1": y1})
    return lines


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
                break
        else:
            paragraphs.append(dict(line, lines=1, line_h=height))
    return paragraphs
