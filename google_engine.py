"""המנוע של Google: תמונה נכנסת -> רשימת בלוקים (מיקום, מקור, תרגום).

זה הקובץ היחיד שמדבר עם Google. כדי לעבור בעתיד ל-Cloud Vision + Translation
מספיק לכתוב מחלקה אחרת עם אותה פונקציה translate().
"""
import json
import os
import threading
import time
from dataclasses import dataclass

import config

PROMPT = (
    "This is a screenshot of part of a computer screen. Find all English text in it. "
    "Group it into natural blocks: one block per paragraph, heading, button label, menu item "
    "or caption. Merge the lines of one paragraph into a single block, but never merge "
    "separate UI elements. For each block return: box_2d = [ymin, xmin, ymax, xmax] "
    "normalized to 0-1000, tight around the text of the block; text = the original English; "
    "he = a natural, fluent Hebrew translation (keep numbers, product names, code and URLs "
    "as they are); lines = how many text lines the block occupies in the image. "
    "Ignore text that is not English and text made only of numbers or symbols. "
    "If there is no English text, return an empty list."
)

SCHEMA = {
    "type": "array",
    "items": {
        "type": "object",
        "properties": {
            "box_2d": {"type": "array", "items": {"type": "integer"}},
            "text": {"type": "string"},
            "he": {"type": "string"},
            "lines": {"type": "integer"},
        },
        "required": ["box_2d", "text", "he", "lines"],
    },
}


@dataclass
class Block:
    # מיקום כשבר מגודל התמונה (0..1), כדי שלא יהיה תלוי ברזולוציה
    x: float
    y: float
    w: float
    h: float
    text: str
    he: str
    lines: int


class EngineError(Exception):
    """kind: no_key | bad_key | offline | rate | blocked | other"""

    def __init__(self, kind, detail=""):
        super().__init__(f"{kind}: {detail}")
        self.kind = kind


def _read_key():
    key = os.environ.get("GEMINI_API_KEY", "").strip()
    if key:
        return key
    for path in config.KEY_FILES:
        try:
            key = path.read_text(encoding="utf-8").strip()
        except OSError:
            continue
        if key:
            return key
    raise EngineError("no_key")


class GoogleEngine:
    def __init__(self):
        self._client = None
        self.last_model = ""
        self._skip_until = {}            # מודל -> עד מתי לדלג עליו (מכסה נגמרה / עומס)
        self._no_thinking_flag = set()
        self._lock = threading.Lock()

    def warmup(self):
        """טעינת הספרייה מראש (ברקע), כדי שהתרגום הראשון לא יתעכב."""
        try:
            self._get_client()
        except EngineError:
            pass

    def _get_client(self):
        with self._lock:
            if self._client is None:
                key = _read_key()
                import truststore
                truststore.inject_into_ssl()  # נטפרי
                from google import genai
                from google.genai import types
                self._client = genai.Client(
                    api_key=key,
                    http_options=types.HttpOptions(timeout=config.REQUEST_TIMEOUT_MS),
                )
            return self._client

    def translate(self, image):
        """image = QImage של האזור. מוקטן אם צריך ונשלח ל-Gemini כ-PNG."""
        from PyQt6.QtCore import QBuffer, QIODevice, Qt
        side = max(image.width(), image.height())
        if side > config.MAX_IMAGE_SIDE:
            image = image.scaled(image.width() * config.MAX_IMAGE_SIDE // side,
                                 image.height() * config.MAX_IMAGE_SIDE // side,
                                 Qt.AspectRatioMode.IgnoreAspectRatio,
                                 Qt.TransformationMode.SmoothTransformation)
        buf = QBuffer()
        buf.open(QIODevice.OpenModeFlag.WriteOnly)
        image.save(buf, "PNG")
        png_bytes = bytes(buf.data())
        client = self._get_client()
        from google.genai import errors, types

        # לכל מודל מכסה חינמית נפרדת. מודל שהמכסה שלו נגמרה מדולג, ועוברים לבא בתור.
        last = EngineError("rate")
        for model in config.MODELS:
            if time.monotonic() < self._skip_until.get(model, 0):
                continue
            while True:
                cfg = dict(response_mime_type="application/json", response_schema=SCHEMA)
                if model not in self._no_thinking_flag:
                    cfg["thinking_config"] = types.ThinkingConfig(thinking_budget=0)
                try:
                    response = client.models.generate_content(
                        model=model,
                        contents=[types.Part.from_bytes(data=png_bytes, mime_type="image/png"), PROMPT],
                        config=types.GenerateContentConfig(**cfg),
                    )
                    self.last_model = model
                    return _parse(response.text)
                except errors.APIError as e:
                    last = _classify_api_error(e)
                    if last.kind in ("bad_key", "blocked"):
                        raise last
                    code = getattr(e, "code", None)
                    if code == 400 and model not in self._no_thinking_flag:
                        self._no_thinking_flag.add(model)   # המודל לא מקבל את הגדרת ה"חשיבה"
                        continue
                    if code == 429 and "PerDay" in str(e):
                        self._skip_until[model] = time.monotonic() + 6 * 3600
                    elif code == 404:
                        self._skip_until[model] = float("inf")
                    else:
                        self._skip_until[model] = time.monotonic() + 60
                except (ValueError, KeyError, TypeError) as e:
                    last = EngineError("other", repr(e))
                except Exception as e:  # רשת: httpx / ssl / timeout
                    if "netfree" in str(e).lower():
                        raise EngineError("blocked", str(e)[:200])
                    raise EngineError("offline", repr(e)[:200])
                break
        raise last


def _classify_api_error(e):
    text = str(e)
    low = text.lower()
    code = getattr(e, "code", None)
    if "netfree" in low or code == 418:
        return EngineError("blocked", text[:200])
    if "api key" in low or "api_key" in low or code in (401, 403):
        return EngineError("bad_key", text[:200])
    if code == 429:
        return EngineError("rate", text[:200])
    return EngineError("other", text[:200])


def _parse(text):
    blocks = []
    data = json.loads(text or "[]")
    if not isinstance(data, list):              # למשל {"error": ...}: תשובה פגומה, לא תקלת רשת
        raise ValueError("unexpected response shape")
    for item in data:
        if not isinstance(item, dict):
            continue
        box = item.get("box_2d") or []
        he = (item.get("he") or "").strip()
        src = (item.get("text") or "").strip()
        if len(box) != 4 or not he or he == src:
            continue
        y0, x0, y1, x1 = (min(max(v, 0), 1000) / 1000 for v in box)
        if x1 - x0 < 0.004 or y1 - y0 < 0.004:
            continue
        blocks.append(Block(x0, y0, x1 - x0, y1 - y0, src, he, max(int(item.get("lines") or 1), 1)))
    return blocks
