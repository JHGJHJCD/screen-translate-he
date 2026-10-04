"""בדיקות יחידה: פונקציות החישוב, פענוח התשובות של Google, והתנהגות מול תקלות רשת (שרת מדומה מקומי).

הרצה: python tests/test_units.py   (Python 3.12). לא פונה ל-Google ולא פותח חלון.
"""
import json
import sys
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np
from PyQt6.QtCore import QRectF
from PyQt6.QtGui import QColor, QImage
from PyQt6.QtWidgets import QApplication

import config
import google_engine
import main
import renderer
import translate_engine
from google_engine import Block, EngineError

app = QApplication.instance() or QApplication(sys.argv)


# ---------- שרת מדומה במקום Google ----------
class FakeGoogle(BaseHTTPRequestHandler):
    mode = "ok"
    seen = []          # (נתיב, גוף) של כל בקשה שהגיעה

    def log_message(self, *a):
        pass

    def do_POST(self):
        body = self.rfile.read(int(self.headers.get("Content-Length", 0))).decode("utf-8")
        FakeGoogle.seen.append((self.path, body, dict(self.headers)))
        web = "batchexecute" in self.path
        mode = FakeGoogle.mode
        if mode == "429" or (mode == "429-fast-only" and not web):
            return self._send(429, "unusual traffic from your computer network")
        if mode == "418":
            return self._send(418, "Blocked by NetFree")
        if mode == "500":
            return self._send(500, "server error")
        if mode == "html":
            return self._send(200, "<html><body>Sign in to the hotel Wi-Fi</body></html>")
        if mode == "empty":
            return self._send(200, "")
        if mode == "slow":
            time.sleep(17)
            return self._send(200, "[]")
        if web:
            inner = json.dumps([None, [[[None, None, None, None, None,
                                         [["שָׁלוֹם"], ["עולם"]]]]]])
            return self._send(200, ")]}'\n\n123\n" + json.dumps([["wrb.fr", "MkEWBc", inner]]) + "\n")
        return self._send(200, json.dumps([[["שלום ", "Hello", None], ["עולם", "world", None]]]))

    def _send(self, code, text):
        data = text.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        try:
            self.wfile.write(data)
        except OSError:
            pass


class NetworkCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), FakeGoogle)
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()
        base = f"http://127.0.0.1:{cls.server.server_address[1]}"
        cls.saved = translate_engine.TRANSLATE_URL, translate_engine.WEB_URL
        translate_engine.TRANSLATE_URL = base + "/translate_a/single?client=gtx"
        translate_engine.WEB_URL = base + "/batchexecute"

    @classmethod
    def tearDownClass(cls):
        translate_engine.TRANSLATE_URL, translate_engine.WEB_URL = cls.saved
        cls.server.shutdown()

    def setUp(self):
        FakeGoogle.mode = "ok"
        FakeGoogle.seen.clear()
        self.engine = translate_engine.TranslateEngine()

    def kind(self, call):
        with self.assertRaises(EngineError) as ctx:
            call()
        return ctx.exception.kind

    def test_fast_channel_parses(self):
        self.assertEqual(self.engine._fetch("Hello world", web=False), "שלום עולם")

    def test_web_channel_parses_and_strips_nikud(self):
        self.assertEqual(self.engine._fetch("Hello world", web=True), "שלום עולם")

    def test_only_text_is_sent(self):
        self.engine._fetch("Hello world", web=False)
        path, body, headers = FakeGoogle.seen[0]
        self.assertEqual(body, "q=Hello+world")
        self.assertNotIn("Cookie", headers)

    def test_429_is_rate(self):
        FakeGoogle.mode = "429"
        self.assertEqual(self.kind(lambda: self.engine._fetch("x", web=False)), "rate")

    def test_418_is_blocked(self):
        FakeGoogle.mode = "418"
        self.assertEqual(self.kind(lambda: self.engine._fetch("x", web=False)), "blocked")

    def test_500_is_other(self):
        FakeGoogle.mode = "500"
        self.assertEqual(self.kind(lambda: self.engine._fetch("x", web=False)), "other")

    def test_html_instead_of_json_is_other(self):
        FakeGoogle.mode = "html"
        self.assertEqual(self.kind(lambda: self.engine._fetch("x", web=False)), "other")
        self.assertEqual(self.kind(lambda: self.engine._fetch("x", web=True)), "other")

    def test_empty_answer_is_other(self):
        FakeGoogle.mode = "empty"
        self.assertEqual(self.kind(lambda: self.engine._fetch("x", web=False)), "other")

    def test_refused_connection_is_offline(self):
        saved = translate_engine.TRANSLATE_URL
        translate_engine.TRANSLATE_URL = "http://127.0.0.1:9/x"
        try:
            self.assertEqual(self.kind(lambda: self.engine._fetch("x", web=False)), "offline")
        finally:
            translate_engine.TRANSLATE_URL = saved

    def test_429_falls_back_to_web_and_stays_there(self):
        FakeGoogle.mode = "429-fast-only"
        self.assertEqual(self.engine._request("Hello world"), "שלום עולם")
        self.assertEqual(len(FakeGoogle.seen), 2)                   # מהיר (נחסם) + אתר
        self.assertEqual(self.engine._request("Hello world"), "שלום עולם")
        self.assertEqual(len(FakeGoogle.seen), 3)                   # ישר לאתר, בלי לנסות שוב את המהיר
        self.assertIn("batchexecute", FakeGoogle.seen[-1][0])

    def test_both_channels_blocked_is_rate(self):
        FakeGoogle.mode = "429"
        self.assertEqual(self.kind(lambda: self.engine._request("x")), "rate")

    def test_slow_server_times_out_as_offline(self):
        FakeGoogle.mode = "slow"
        started = time.monotonic()
        self.assertEqual(self.kind(lambda: self.engine._fetch("x", web=False)), "offline")
        self.assertLess(time.monotonic() - started, 16.5)


# ---------- קיבוץ שורות ----------
def word(text, x, y, w=40, h=20):
    return (text, x, y, w, h)


class GroupingCase(unittest.TestCase):
    def test_split_line_on_big_gap(self):
        lines = translate_engine._split_line([word("Save", 0, 0), word("changes", 45, 0), word("Create", 300, 0)])
        self.assertEqual([l["text"] for l in lines], ["Save changes", "Create"])
        self.assertEqual((lines[0]["x0"], lines[0]["x1"]), (0, 85))

    def test_split_line_empty(self):
        self.assertEqual(translate_engine._split_line([]), [])

    def test_group_joins_paragraph_lines(self):
        lines = [{"text": "first line", "x0": 10, "y0": 0, "x1": 300, "y1": 20},
                 {"text": "second line", "x0": 10, "y0": 26, "x1": 280, "y1": 46}]
        groups = translate_engine._group(lines)
        self.assertEqual(len(groups), 1)
        self.assertEqual(groups[0]["text"], "first line second line")
        self.assertEqual(groups[0]["lines"], 2)

    def test_group_keeps_far_lines_apart(self):
        lines = [{"text": "a", "x0": 10, "y0": 0, "x1": 300, "y1": 20},
                 {"text": "b", "x0": 10, "y0": 80, "x1": 280, "y1": 100}]
        self.assertEqual(len(translate_engine._group(lines)), 2)

    def test_group_keeps_heading_apart(self):
        lines = [{"text": "Heading", "x0": 10, "y0": 0, "x1": 300, "y1": 40},
                 {"text": "body", "x0": 10, "y0": 46, "x1": 280, "y1": 62}]
        self.assertEqual(len(translate_engine._group(lines)), 2)

    def test_group_skips_zero_height(self):
        self.assertEqual(translate_engine._group([{"text": "x", "x0": 0, "y0": 5, "x1": 9, "y1": 5}]), [])


# ---------- שליחה בקבוצות ומטמון ----------
class BatchCase(unittest.TestCase):
    def engine(self, merge):
        e = translate_engine.TranslateEngine()
        e.calls = []

        def fake(text):
            e.calls.append(text)
            parts = [f"ע{p}" for p in text.split("\n")]
            return " ".join(parts) if merge(parts) else "\n".join(parts)
        e._request = fake
        return e

    def test_one_request_for_many_lines(self):
        e = self.engine(lambda parts: False)
        self.assertEqual(e._translate_many(["a", "b", "c", "d"]), ["עa", "עb", "עc", "עd"])
        self.assertEqual(len(e.calls), 1)

    def test_merged_lines_are_bisected_not_sent_one_by_one(self):
        e = self.engine(lambda parts: len(parts) > 8)
        texts = [f"t{i}" for i in range(32)]
        self.assertEqual(e._translate_many(texts), [f"עt{i}" for i in range(32)])
        self.assertLess(len(e.calls), 10)

    def test_always_merging_still_ends(self):
        e = self.engine(lambda parts: len(parts) > 1)
        self.assertEqual(len(e._translate_many([f"t{i}" for i in range(16)])), 16)
        self.assertEqual(len(e.calls), 31)          # המקרה הגרוע: 2n-1 בקשות

    def test_text_cache_and_duplicates(self):
        e = self.engine(lambda parts: False)
        self.assertEqual(e._translate_texts(["a", "a", "b"]), ["עa", "עa", "עb"])
        e._translate_texts(["a", "b"])
        self.assertEqual(len(e.calls), 1)

    def test_text_cache_is_capped(self):
        e = self.engine(lambda parts: False)
        for i in range(0, 700, 50):
            e._translate_texts([f"t{j}" for j in range(i, i + 50)])
        self.assertLessEqual(len(e._texts), translate_engine.TEXT_CACHE)


# ---------- פענוח Gemini ----------
class ParseCase(unittest.TestCase):
    def test_valid(self):
        blocks = google_engine._parse(json.dumps([{"box_2d": [100, 200, 300, 600], "text": "Hi", "he": "היי"}]))
        self.assertEqual(len(blocks), 1)
        b = blocks[0]
        self.assertEqual((b.x, b.y, round(b.w, 3), round(b.h, 3), b.lines), (0.2, 0.1, 0.4, 0.2, 1))

    def test_skips_untranslated_tiny_and_broken(self):
        items = [{"box_2d": [0, 0, 100, 100], "text": "OK", "he": "OK"},
                 {"box_2d": [0, 0, 2, 2], "text": "a", "he": "א"},
                 {"box_2d": [0, 0, 100], "text": "a", "he": "א"},
                 {"text": "a", "he": "א"},
                 {"box_2d": [0, 0, 100, 100], "text": "a", "he": ""}]
        self.assertEqual(google_engine._parse(json.dumps(items)), [])

    def test_clamps_out_of_range(self):
        b = google_engine._parse(json.dumps([{"box_2d": [-50, -50, 2000, 2000], "text": "a", "he": "א"}]))[0]
        self.assertEqual((b.x, b.y, b.w, b.h), (0, 0, 1, 1))

    def test_empty_and_garbage(self):
        self.assertEqual(google_engine._parse(""), [])
        self.assertEqual(google_engine._parse(None), [])
        with self.assertRaises(ValueError):
            google_engine._parse("not json")

    def test_object_instead_of_list_does_not_crash_the_app(self):
        # translate() תופס ValueError/KeyError/TypeError; כל חריגה אחרת הייתה מוצגת כ"אין אינטרנט"
        try:
            google_engine._parse('{"error": "x"}')
        except (ValueError, KeyError, TypeError):
            pass
        except Exception as e:
            self.fail(f"חריגה שלא נתפסת נכון: {e!r}")


# ---------- טביעת אצבע וזיהוי שינוי ----------
class SignatureCase(unittest.TestCase):
    def image(self, w, h, color="white"):
        img = QImage(w, h, QImage.Format.Format_RGB32)
        img.fill(QColor(color))
        return img

    def test_shape_for_odd_sizes(self):
        for size in ((101, 57), (1, 1), (3000, 17), (64, 64)):
            self.assertEqual(main.signature(self.image(*size)).shape, (64, 64), size)

    def test_same_image_no_change(self):
        a = main.signature(self.image(300, 200))
        self.assertEqual(main.changed_cells(a, a.copy()), 0)

    def test_full_change_is_big(self):
        a, b = main.signature(self.image(300, 200)), main.signature(self.image(300, 200, "black"))
        self.assertGreaterEqual(main.changed_cells(a, b), main.BIG_CHANGE)

    def test_mask_hides_noise(self):
        a = np.zeros((64, 64), np.int16)
        b = a.copy()
        b[:2, :2] = 200
        mask = np.zeros((64, 64), bool)
        self.assertEqual(main.changed_cells(a, b), 4)
        mask[:2, :2] = True
        self.assertEqual(main.changed_cells(a, b, mask), 0)


# ---------- ציור ----------
class RendererCase(unittest.TestCase):
    def test_plain_background(self):
        arr = np.full((60, 200, 3), 255, np.uint8)
        arr[20:40, 30:170] = 0
        bg, fg, patch = renderer._sample_colors(arr, 0, 0, 200, 60)
        self.assertEqual((bg, fg, patch), ((255, 255, 255), (0, 0, 0), None))

    def test_dark_background(self):
        arr = np.full((60, 200, 3), 20, np.uint8)
        arr[20:40, 30:170] = 240
        bg, fg, _ = renderer._sample_colors(arr, 0, 0, 200, 60)
        self.assertLess(sum(bg), 100)
        self.assertGreater(sum(fg), 600)

    def test_low_contrast_text_gets_readable_color(self):
        arr = np.full((60, 200, 3), 200, np.uint8)
        arr[20:40, 30:170] = 170
        bg, fg, _ = renderer._sample_colors(arr, 0, 0, 200, 60)
        self.assertGreaterEqual(abs(renderer._luminance(fg) - renderer._luminance(bg)), 70)

    def test_busy_background_gets_patch(self):
        rng = np.random.default_rng(1)
        arr = rng.integers(0, 255, (60, 200, 3), dtype=np.uint8)
        _, _, patch = renderer._sample_colors(arr, 0, 0, 200, 60)
        self.assertIsNotNone(patch)

    def test_tiny_and_outside_regions(self):
        arr = np.full((60, 200, 3), 255, np.uint8)
        self.assertEqual(renderer._sample_colors(arr, 0, 0, 3, 3)[:2], ((255, 255, 255), (0, 0, 0)))
        self.assertEqual(renderer._sample_colors(arr, 500, 500, 600, 600)[:2], ((255, 255, 255), (0, 0, 0)))

    def test_style_blocks_scales_to_screen_units(self):
        arr = np.full((300, 600, 3), 255, np.uint8)          # צילום ב-150%
        styled = renderer.style_blocks(arr, [Block(0.5, 0.5, 0.25, 0.1, "a", "א", 1)], 400, 200)
        self.assertEqual(styled[0].rect, QRectF(200, 100, 100, 20))

    def test_font_never_below_minimum_and_ends(self):
        block = renderer.StyledBlock(QRectF(0, 0, 20, 6), "טקסט ארוך מאוד שלא נכנס בשום אופן", 1,
                                     QColor("white"), QColor("black"))
        font = renderer._fit_font(block, renderer.cover_of(block.rect))
        self.assertEqual(font.pixelSize(), config.MIN_FONT_PX)


# ---------- מצב החלון (בלי להציג אותו) ----------
class WindowStateCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.w = main.TranslatorWindow()

    def setUp(self):
        w = self.w
        w.gap, w.failed, w.busy, w.shown, w.result = config.MIN_GAP_S, False, True, [], None
        w.cache.clear()
        w.last_texts = None

    def test_rate_error_backs_off_and_retries(self):
        w = self.w
        gaps = []
        for _ in range(5):
            w._on_done(w.gen, "k", EngineError("rate"))
            gaps.append(w.gap)
        self.assertEqual(gaps, [60, 120, 240, 300, 300])
        self.assertTrue(w.failed)
        self.assertFalse(w.busy)
        self.assertEqual(w.status, main.MESSAGES["rate"])

    def test_offline_backs_off_from_10s(self):
        self.w._on_done(self.w.gen, "k", EngineError("offline"))
        self.assertEqual(self.w.gap, 10)

    def test_permanent_errors_do_not_retry(self):
        for kind in ("no_ocr", "no_key", "bad_key"):
            self.w._on_done(self.w.gen, "k", EngineError(kind))
            self.assertFalse(self.w.failed, kind)
            self.assertEqual(self.w.status, main.MESSAGES[kind])

    def test_every_error_kind_has_a_message(self):
        for kind in ("no_key", "bad_key", "offline", "rate", "blocked", "no_ocr", "other"):
            self.assertIn(kind, main.MESSAGES)

    def test_stale_answer_is_ignored_but_cached(self):
        w = self.w
        w._on_done(w.gen - 1, "old", [Block(0, 0, 0.5, 0.5, "a", "א", 1)])
        self.assertTrue(w.busy)
        self.assertEqual(w.shown, [])
        self.assertIn("old", w.cache)

    def test_cache_is_capped(self):
        for i in range(config.CACHE_SIZE + 25):
            self.w._on_done(self.w.gen - 1, f"k{i}", [])
        self.assertEqual(len(self.w.cache), config.CACHE_SIZE)

    def test_empty_result_says_no_text(self):
        self.w._on_done(self.w.gen, "k", [])
        self.assertEqual(self.w.status, "לא נמצא כאן טקסט באנגלית")

    def test_result_is_shown(self):
        w = self.w
        w.pending_arr = np.full((300, 500, 3), 255, np.uint8)
        w._on_done(w.gen, "k", [Block(0.1, 0.1, 0.5, 0.1, "Hello", "שלום", 1)])
        self.assertEqual(len(w.shown), 1)
        self.assertEqual(w.status, "")

    def test_minute_cap(self):
        w = self.w
        now = time.monotonic()
        w.sends.clear()
        w.sends.extend([now] * config.MAX_PER_MINUTE)
        self.assertFalse(w._under_minute_cap())
        w.sends.clear()
        w.sends.extend([now - 61] * config.MAX_PER_MINUTE)
        self.assertTrue(w._under_minute_cap())

    def test_pause_clears_translation(self):
        w = self.w
        w.enabled, w.shown = True, ["x"]
        w.toggle()
        self.assertEqual((w.enabled, w.shown, w.status), (False, [], "כבוי"))
        w.toggle()
        self.assertTrue(w.enabled)
        w.settle.stop()

    def test_edges_cover_all_sides(self):
        from PyQt6.QtCore import QPoint, Qt
        w = self.w
        w.resize(400, 300)
        E = Qt.Edge
        self.assertEqual(w._edges(QPoint(2, 150)), E.LeftEdge)
        self.assertEqual(w._edges(QPoint(397, 150)), E.RightEdge)
        self.assertEqual(w._edges(QPoint(200, 298)), E.BottomEdge)
        self.assertEqual(w._edges(QPoint(2, 298)), E.LeftEdge | E.BottomEdge)
        self.assertEqual(w._edges(QPoint(397, 298)), E.RightEdge | E.BottomEdge)
        self.assertEqual(w._edges(QPoint(200, 1)), E.TopEdge)
        self.assertEqual(w._edges(QPoint(200, 150)), E(0))


# ---------- זכירת המיקום והגודל של הריבוע ----------
class PlaceCase(unittest.TestCase):
    from PyQt6.QtCore import QRect
    ONE = [QRect(0, 0, 1920, 1040)]
    TWO = [QRect(0, 0, 1920, 1040), QRect(1920, 0, 1280, 984)]

    def test_saved_place_is_restored(self):
        self.assertEqual(main.parse_place("300,200,640,480", self.ONE), self.QRect(300, 200, 640, 480))

    def test_place_on_second_screen_is_restored(self):
        self.assertEqual(main.parse_place("2100,100,560,360", self.TWO), self.QRect(2100, 100, 560, 360))

    def test_place_on_disconnected_screen_is_dropped(self):
        self.assertIsNone(main.parse_place("2100,100,560,360", self.ONE))

    def test_place_outside_every_screen_is_dropped(self):
        for text in ("-3000,100,560,360", "100,-500,560,360", "100,5000,560,360", "5000,5000,560,360"):
            self.assertIsNone(main.parse_place(text, self.TWO), text)

    def test_bar_must_stay_reachable(self):
        # רק 40 פיקסלים מהפס על המסך: אי אפשר לתפוס אותו
        self.assertIsNone(main.parse_place("1880,100,560,360", self.ONE))
        # הפס מתחת לקצה התחתון של שטח העבודה (מאחורי שורת המשימות)
        self.assertIsNone(main.parse_place("100,1030,560,360", self.ONE))
        # חלק מהריבוע מחוץ למסך אבל הפס בהישג יד: בסדר
        self.assertIsNotNone(main.parse_place("1700,900,560,360", self.ONE))
        self.assertIsNotNone(main.parse_place("-300,100,560,360", self.ONE))

    def test_smaller_resolution_drops_place(self):
        self.assertIsNone(main.parse_place("1500,800,560,360", [self.QRect(0, 0, 1280, 680)]))

    def test_broken_file_is_dropped(self):
        for text in ("", "abc", "1,2,3", "1,2,3,4,5", "10,10,x,300", "10,10,5,5", "10,10,-560,360", "1.5,2,560,360"):
            self.assertIsNone(main.parse_place(text, self.ONE), repr(text))

    def test_save_and_reopen(self):
        import tempfile
        old = config.PLACE_FILE
        with tempfile.TemporaryDirectory() as tmp:
            config.PLACE_FILE = Path(tmp) / "window_place"
            try:
                self.assertIsNone(main.saved_place())               # אין קובץ: מרכז המסך
                screen = QApplication.primaryScreen().availableGeometry()
                w = main.TranslatorWindow()
                w.setGeometry(screen.x() + 120, screen.y() + 90, 420, 310)
                w.save_place()
                again = main.TranslatorWindow()
                self.assertEqual(again.geometry(), w.geometry())
                config.PLACE_FILE.write_text("-9000,-9000,420,310", encoding="utf-8")
                centered = main.TranslatorWindow()
                self.assertEqual((centered.width(), centered.height()), (560, 360))
                self.assertTrue(screen.contains(centered.geometry().center()))
            finally:
                config.PLACE_FILE = old

    def test_forced_test_geometry_is_not_saved(self):
        import os
        import tempfile
        old = config.PLACE_FILE
        with tempfile.TemporaryDirectory() as tmp:
            config.PLACE_FILE = Path(tmp) / "window_place"
            os.environ["ST_GEOMETRY"] = "70,40,840,610"
            try:
                w = main.TranslatorWindow()
                w.save_place()
                self.assertFalse(config.PLACE_FILE.exists())
                self.assertEqual((w.width(), w.height()), (840, 610))
            finally:
                del os.environ["ST_GEOMETRY"]
                config.PLACE_FILE = old

    def test_about_shows_version(self):
        self.assertIn(config.VERSION, main.about_text())


# ---------- עדכונים ----------
class UpdateCase(unittest.TestCase):
    import updater
    GOOD = updater.DOWNLOAD_PREFIX + "v9.0.0/" + updater.ASSET

    def release(self, tag="v9.0.0", name=None, url=None, **more):
        return {"tag_name": tag, "assets": [{"name": name or self.updater.ASSET,
                                             "browser_download_url": url or self.GOOD}], **more}

    def test_versions_compare_as_numbers(self):
        p = self.updater.parse_version
        self.assertEqual(p("v1.2.0"), (1, 2, 0))
        self.assertGreater(p("1.10.0"), p("1.9.9"))
        self.assertEqual(p("latest"), ())

    def test_newer_release_is_offered(self):
        self.assertEqual(self.updater.pick(self.release(), "1.2.0"), ("9.0.0", self.GOOD))

    def test_same_or_older_release_is_not_offered(self):
        self.assertIsNone(self.updater.pick(self.release("v1.2.0"), "1.2.0"))
        self.assertIsNone(self.updater.pick(self.release("v1.1.9"), "1.2.0"))

    def test_draft_and_prerelease_are_ignored(self):
        self.assertIsNone(self.updater.pick(self.release(draft=True), "1.2.0"))
        self.assertIsNone(self.updater.pick(self.release(prerelease=True), "1.2.0"))

    def test_file_from_another_place_is_refused(self):
        self.assertIsNone(self.updater.pick(self.release(url="https://evil.example/ScreenTranslateSetup.exe"), "1.2.0"))
        self.assertIsNone(self.updater.pick(self.release(
            url="https://github.com/someone-else/screen-translate-he/releases/download/v9/ScreenTranslateSetup.exe"), "1.2.0"))
        self.assertIsNone(self.updater.pick(self.release(name="other.exe"), "1.2.0"))

    def test_garbage_answer_is_ignored(self):
        for answer in (None, [], "x", {}, {"tag_name": "new"}, {"tag_name": "v9.0.0"}, {"tag_name": "v9.0.0", "assets": None}):
            self.assertIsNone(self.updater.pick(answer, "1.2.0"), repr(answer))

    def test_file_signed_by_someone_else_is_refused(self):
        import os
        windows_file = Path(os.environ["WINDIR"]) / "System32" / "notepad.exe"      # חתום, אבל לא בתעודה שלנו
        self.assertFalse(self.updater.is_ours(windows_file))

    def test_unsigned_file_is_refused(self):
        self.assertFalse(self.updater.is_ours(Path(__file__)))


if __name__ == "__main__":
    unittest.main(verbosity=2)
