"""בדיקות ממשק שלא כוסו ב-run_tests.py: דפים נוספים, כפתורי הפס, גלגלת, Alt+F4, הפעלה שנייה, עומס לאורך זמן.

שימוש: run_ui.py <תיקיית פלט> <extra|buttons|soak> [שניות]
מזיז את העכבר ולוחץ בעצמו — לא לגעת במחשב בזמן הריצה.
"""
import ctypes
import json
import os
import subprocess
import sys
import time
from ctypes import wintypes
from pathlib import Path

import psutil

ROOT = Path(__file__).resolve().parent.parent
PY = sys.executable
scenario = sys.argv[2]
out = Path(sys.argv[1]) / scenario
out.mkdir(parents=True, exist_ok=True)
for f in out.glob("*"):
    if f.suffix in (".png", ".log", ".json"):
        f.unlink()

u = ctypes.windll.user32
ctypes.windll.shcore.SetProcessDpiAwareness(2)
u.FindWindowW.restype = wintypes.HWND
TITLE = "תרגום מסך"
results = {}
log_path = out / "events.log"


def events():
    return log_path.read_text(encoding="utf-8").splitlines() if log_path.exists() else []


def wait_for(text, timeout, start=0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if any(text in line for line in events()[start:]):
            return True
        time.sleep(0.2)
    return False


def rect(hwnd):
    r = wintypes.RECT()
    u.GetWindowRect(hwnd, ctypes.byref(r))
    return r.left, r.top, r.right, r.bottom


def click(x, y):
    u.SetCursorPos(int(x), int(y)); time.sleep(0.3)
    u.mouse_event(0x0002, 0, 0, 0, 0); time.sleep(0.08)
    u.mouse_event(0x0004, 0, 0, 0, 0); time.sleep(0.8)


def keys(*vks):
    for vk in vks:
        u.keybd_event(vk, 0, 0, 0)
    for vk in reversed(vks):
        u.keybd_event(vk, 0, 2, 0)
    time.sleep(1.2)


def usage(proc):
    return {"rss_mb": round(proc.memory_info().rss / 1e6, 1), "threads": proc.num_threads(),
            "handles": proc.num_handles()}


def cpu_percent(proc, seconds):
    a = proc.cpu_times()
    time.sleep(seconds)
    b = proc.cpu_times()
    return round(((b.user + b.system) - (a.user + a.system)) / seconds * 100, 2)


pages = {"extra": ["dark:13", "small:13", "mixed:13", "tech:13", "cols:13"],
         "buttons": ["long:300"], "soak": ["anim:3600"]}[scenario]
env = dict(os.environ, ST_DEBUG_DIR=str(out), ST_GEOMETRY="70,40,840,610")
harness = subprocess.Popen([PY, str(ROOT / "tests" / "harness.py"), *pages])
time.sleep(9)
started = time.monotonic()
app = subprocess.Popen([PY, str(ROOT / "main.py")], env=env, cwd=ROOT)
proc = psutil.Process(app.pid)
try:
    hwnd = None
    while time.monotonic() - started < 20:
        hwnd = u.FindWindowW(None, TITLE)
        if hwnd and u.IsWindowVisible(hwnd):
            break
        time.sleep(0.05)
    results["seconds_until_window"] = round(time.monotonic() - started, 2)
    results["first_translation_ok"] = wait_for("result ", 25)
    results["seconds_until_translation"] = round(time.monotonic() - started, 2)
    scale = u.GetDpiForWindow(hwnd) / 96
    results["scale"] = scale

    if scenario == "extra":
        time.sleep(13 * 5 - 6)

    elif scenario == "soak":
        seconds = int(sys.argv[3]) if len(sys.argv) > 3 else 360
        time.sleep(5)
        results["start"] = usage(proc)
        results["cpu_percent_first_30s"] = cpu_percent(proc, 30)
        time.sleep(max(seconds - 65, 0))
        results["cpu_percent_last_30s"] = cpu_percent(proc, 30)
        results["end"] = usage(proc)
        results["sends"] = sum(" send" in line for line in events())
        results["seconds"] = seconds

    elif scenario == "buttons":
        left, top, right, bottom = rect(hwnd)
        bar = 30 * scale
        results["idle"] = usage(proc)
        results["cpu_percent_idle_with_translation"] = cpu_percent(proc, 20)

        # גלגלת מעל תרגום: אמורה לגלול את הדף שמתחת
        page = u.FindWindowW(None, "ST-harness")
        n = len(events())
        u.SetCursorPos(int(left + 200 * scale), int(top + 70 * scale)); time.sleep(0.5)
        u.mouse_event(0x0800, 0, 0, -360, 0); time.sleep(1.5)
        title = ctypes.create_unicode_buffer(100)
        u.GetWindowTextW(page, title, 100)
        results["wheel_over_translation_scrolled_page"] = title.value.startswith("scroll")
        results["wheel_page_title"] = title.value
        results["retranslated_after_scroll"] = wait_for("result ", 15, n)

        # ⏸ : השהיה והמשך
        n = len(events())
        click(left + bar * 1.5, top + bar / 2)
        results["pause_click"] = any("toggle -> off" in line for line in events()[n:])
        click(left + bar * 1.5, top + bar / 2)
        results["resume_click"] = any("toggle -> on" in line for line in events()[n:])
        results["translated_after_resume"] = wait_for("result ", 15, n)

        # ✕ : מסתיר, לא סוגר
        click(left + bar / 2, top + bar / 2)
        results["close_click_hides"] = not u.IsWindowVisible(hwnd)
        results["close_click_keeps_running"] = app.poll() is None

        # הפעלה שנייה: מציגה את הריבוע ולא פותחת עוד עותק
        second = subprocess.Popen([PY, str(ROOT / "main.py")], cwd=ROOT)
        results["second_launch_exit_code"] = second.wait(15)
        time.sleep(1)
        results["second_launch_shows_square"] = bool(u.IsWindowVisible(hwnd))
        results["only_one_window"] = sum(1 for p in psutil.process_iter(["cmdline"])
                                         if p.info["cmdline"] and any(c.endswith("main.py") for c in p.info["cmdline"])) == 1

        # ✕ מיד אחרי שהריבוע חזר (העכבר נשאר מעל הכפתור), ואז שוב אחרי שהעכבר זז
        click(left + bar / 2, top + bar / 2)
        results["close_click_right_after_reshow_hides"] = not u.IsWindowVisible(hwnd)
        if u.IsWindowVisible(hwnd):
            u.SetCursorPos(int(left + 400 * scale), int(top + 300 * scale)); time.sleep(0.6)
            click(left + bar / 2, top + bar / 2)
            results["close_click_after_moving_mouse_hides"] = not u.IsWindowVisible(hwnd)

        # הפעלה שנייה עם --hidden (עלייה עם המחשב כשהתוכנה כבר רצה): לא מקפיצה את הריבוע
        hidden = subprocess.Popen([PY, str(ROOT / "main.py"), "--hidden"], cwd=ROOT)
        hidden.wait(15)
        time.sleep(1)
        results["hidden_launch_stays_hidden"] = not u.IsWindowVisible(hwnd)

        # Ctrl+Alt+T מחזיר, Alt+F4 רק מסתיר
        if not u.IsWindowVisible(hwnd):
            keys(0x11, 0x12, 0x54)
        results["hotkey_shows"] = bool(u.IsWindowVisible(hwnd))
        click(left + 300 * scale, top + bar / 2)          # לחיצה על הפס כדי שהחלון יהיה הפעיל
        results["window_is_active_before_alt_f4"] = u.GetForegroundWindow() == hwnd
        keys(0x12, 0x73)
        results["alt_f4_hides"] = not u.IsWindowVisible(hwnd)
        results["alt_f4_keeps_running"] = app.poll() is None
        results["alt_f4_did_not_close_page_below"] = harness.poll() is None
        keys(0x11, 0x12, 0x54)
        results["shown_again"] = bool(u.IsWindowVisible(hwnd))
        time.sleep(4)
        results["end"] = usage(proc)
finally:
    app.terminate()
    harness.terminate()

(out / "results.json").write_text(json.dumps(results, ensure_ascii=False, indent=1), encoding="utf-8")
print(json.dumps(results, ensure_ascii=False, indent=1))
print("\n".join(events()))
