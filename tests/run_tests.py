"""מריץ את האפליקציה מול חלון הבדיקה ושומר תמונות ויומן אירועים לתיקייה.

שימוש: run_tests.py <תיקיית פלט> <תרחיש>
תרחישים: pages | move | badkey | offline | real
"""
import ctypes
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PY = sys.executable
out = Path(sys.argv[1]) / sys.argv[2]
out.mkdir(parents=True, exist_ok=True)
for f in out.iterdir():
    f.unlink()
scenario = sys.argv[2]

env = dict(os.environ, ST_DEBUG_DIR=str(out), ST_GEOMETRY="70,40,840,610")
pages = ["A:60"]
run_for = 12
if scenario == "pages":
    pages, run_for = ["A:22", "B:12", "empty:12"], 40
elif scenario == "offline":
    run_for = 25
elif scenario == "badkey":
    env["GEMINI_API_KEY"] = "not-a-real-key"
if scenario == "offline":
    env["HTTPS_PROXY"] = env["HTTP_PROXY"] = "http://127.0.0.1:9"
elif scenario == "real":
    env["ST_NO_EXCLUDE"] = "1"

harness = subprocess.Popen([PY, str(ROOT / "tests" / "harness.py"), *pages])
time.sleep(9)
app = subprocess.Popen([PY, str(ROOT / "main.py")], env=env, cwd=ROOT)
try:
    if scenario == "move":
        time.sleep(1.5)
        user32 = ctypes.windll.user32
        hwnd = user32.FindWindowW(None, "תרגום מסך")
        print("hwnd", hwnd)
        for i in range(40):                      # 4 שניות של תזוזה רצופה
            user32.SetWindowPos(hwnd, 0, 50 + i * 4, 24 + i * 2, 0, 0, 0x0001 | 0x0004)
            time.sleep(0.1)
    if scenario == "mouse":
        # גרירה אמיתית בעכבר, שינוי גודל מהפינה, וקיצור המקלדת. המסך ב-150%.
        u = ctypes.windll.user32
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
        time.sleep(14)

        def drag(x0, y0, x1, y1):
            u.SetCursorPos(x0, y0); time.sleep(0.3)
            u.mouse_event(0x0002, 0, 0, 0, 0); time.sleep(0.2)
            for i in range(1, 11):
                u.SetCursorPos(x0 + (x1 - x0) * i // 10, y0 + (y1 - y0) * i // 10); time.sleep(0.05)
            time.sleep(0.2)
            u.mouse_event(0x0004, 0, 0, 0, 0); time.sleep(4)

        drag(735, 82, 835, 112)            # הפס העליון: הזזה
        drag(1460, 1000, 1300, 900)       # פינה ימנית-תחתונה: הקטנה
        for _ in range(2):                 # Ctrl+Alt+T פעמיים: כיבוי והפעלה
            for vk in (0x11, 0x12, 0x54):
                u.keybd_event(vk, 0, 0, 0)
            for vk in (0x54, 0x12, 0x11):
                u.keybd_event(vk, 0, 2, 0)
            time.sleep(1.5)
        time.sleep(6)
    elif scenario == "real":
        time.sleep(22)
        from PIL import ImageGrab
        ImageGrab.grab().save(out / "screen.png")
    else:
        time.sleep(run_for)
finally:
    app.terminate()
    harness.terminate()
log = out / "events.log"
print(log.read_text(encoding="utf-8") if log.exists() else "(no events)")
