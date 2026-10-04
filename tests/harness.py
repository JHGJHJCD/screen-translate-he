"""חלון בדיקה: מציג דף אינטרנט אמיתי עם המקרים שצריך לבדוק, ומחליף תוכן לפי לוח זמנים.

שימוש: harness.py A:9 B:9 empty:9   (שם דף : שניות)
"""
import base64
import io
import sys

from PIL import Image, ImageDraw, ImageFilter, ImageFont
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtWebEngineWidgets import QWebEngineView
from PyQt6.QtWidgets import QApplication


def photo_with_text():
    img = Image.new("RGB", (380, 150))
    px = img.load()
    for y in range(150):
        for x in range(380):
            px[x, y] = (40 + x // 3, 90 + y // 2, 150 - x // 5 + y // 3)
    d = ImageDraw.Draw(img)
    for i in range(0, 380, 38):
        d.ellipse((i, 90 - i % 60, i + 70, 160 - i % 60), fill=(30 + i // 3, 120, 60))
    img = img.filter(ImageFilter.GaussianBlur(6))
    d = ImageDraw.Draw(img)
    d.text((24, 50), "Summer sale starts today", font=ImageFont.truetype("segoeuib.ttf", 28), fill="white")
    buf = io.BytesIO()
    img.save(buf, "PNG")
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()


STYLE = """<style>
body{font-family:Segoe UI,Arial;margin:24px;background:#fff;color:#111}
h1{font-size:28px;margin:0 0 10px} p{font-size:17px;line-height:1.5;max-width:560px}
.band{background:#6a1b9a;color:#fff;padding:14px 18px;font-size:18px;margin:14px 0;width:520px}
.warn{background:#ffe082;color:#3e2723;padding:10px 18px;font-size:16px;width:520px}
button{background:#1565c0;color:#fff;border:0;padding:12px 26px;font-size:17px;margin:14px 12px 14px 0}
button.g{background:#2e7d32}
</style>"""

PAGES = {
    "A": STYLE + """
<h1>Getting started with your account</h1>
<p>Your profile is almost complete. Add a photo so your friends can recognize you.
You can change these settings at any time from the menu.</p>
<div class="band">Free shipping on all orders over $50</div>
<div class="warn">Your password will expire in 3 days.</div>
<button>Save changes</button><button class="g">Create account</button><br>
<img src="%IMG%">
""",
    "B": STYLE + """
<h1>Frequently asked questions</h1>
<p>How do I reset my password? Open the login page and click the link below the form.
We will send you an email with further instructions.</p>
<div class="band">Our support team is available 24 hours a day</div>
<button>Contact us</button>
""",
    "dark": """<style>body{font-family:Segoe UI;margin:24px;background:#121212;color:#e0e0e0}
h1{font-size:28px;margin:0 0 10px} p{font-size:17px;line-height:1.5;max-width:560px} a{color:#8ab4f8}
.card{background:#1e1e1e;border:1px solid #333;padding:14px 18px;width:500px;font-size:16px;color:#bdbdbd}</style>
<h1>Dark mode is now available</h1>
<p>Switch between light and dark themes whenever you like. Your choice is saved on this device.</p>
<div class="card">Notifications are turned off for this conversation.</div>
<p><a>Learn more about privacy settings</a></p>""",
    "small": """<style>body{font-family:Segoe UI;margin:24px;background:#fff;color:#111}</style>
<p style="font-size:9px">This footnote is written in very small letters and is hard to read.</p>
<p style="font-size:11px">Terms and conditions apply. Prices may change without notice.</p>
<p style="font-size:13px;color:#888">Last updated two hours ago by the administrator.</p>
<div style="font-size:64px;font-weight:700">Welcome back</div>
<p style="font-size:40px">Big news today</p>""",
    "mixed": """<style>body{font-family:Segoe UI;margin:24px;background:#fff;color:#111;font-size:18px}
p{max-width:560px;line-height:1.5}</style>
<p dir="rtl">זו פסקה שכבר כתובה בעברית ואין סיבה לגעת בה בכלל.</p>
<p>This paragraph is written in English and should be translated.</p>
<p dir="rtl">לחץ על הכפתור Download now כדי להמשיך.</p>
<p>Shalom, the word שלום means peace in Hebrew.</p>""",
    "tech": """<style>body{font-family:Segoe UI;margin:24px;background:#fff;color:#111;font-size:18px}
pre{background:#f5f5f5;padding:12px;font:15px Consolas;width:520px}</style>
<p>Total price: $1,234.56 (including 17% tax)</p>
<p>Visit https://www.example.com/help or write to support@example.com</p>
<p>Version 2.4.1 was released on March 5, 2024 at 10:30 AM</p>
<pre>pip install requests
git commit -m "fix login bug"</pre>
<p>Press Ctrl+S to save the file.</p>""",
    "cols": """<style>body{font-family:Segoe UI;margin:24px;background:#fff;color:#111;font-size:16px}
.row{display:flex;gap:40px} .row div{width:340px;line-height:1.45}</style>
<div class="row"><div><b>Morning schedule</b><br>The bus leaves the station at eight o'clock every
morning and arrives at the school twenty minutes later.</div>
<div><b>Evening schedule</b><br>The library closes at nine in the evening, so please return your
books before you leave the building.</div></div>""",
    "long": STYLE + "<title>ST-top</title><script>onscroll=()=>document.title='scroll '+Math.round(scrollY)</script>"
            + "".join(f"<h1>Chapter {i}: A new beginning</h1><p>The weather was cold that morning and nobody "
                      f"wanted to leave the house. We waited by the window for a long time.</p>" for i in range(1, 9)),
    "anim": STYLE + """<style>@keyframes b{50%{opacity:0}} @keyframes s{to{transform:rotate(360deg)}}
.cur{display:inline-block;width:2px;height:20px;background:#111;animation:b 1s steps(1) infinite}
.spin{width:22px;height:22px;border:4px solid #1565c0;border-top-color:transparent;border-radius:50%;
animation:s 1s linear infinite;margin:20px 0}</style>
<h1>Type your message here</h1>
<p>We are checking your connection. This may take a few moments.<span class="cur"></span></p>
<div class="spin"></div><div class="band">Please do not close this window</div>""",
    "empty": "<body style='background:#eceff1'><div style='width:300px;height:200px;margin:80px;"
             "background:#90a4ae'></div><div style='width:120px;height:120px;margin:80px;"
             "border-radius:60px;background:#ef6c00'></div></body>",
}

app = QApplication(sys.argv)
view = QWebEngineView()
view.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint)
view.setGeometry(60, 60, 860, 600)
view.setWindowTitle("ST-harness")
view.titleChanged.connect(lambda t: view.setWindowTitle(t) if t.startswith("scroll") else None)
schedule = [(a.split(":")[0], int(a.split(":")[1])) for a in sys.argv[1:]] or [("A", 3600)]
image = photo_with_text()


def step():
    if not schedule:
        app.quit()
        return
    name, seconds = schedule.pop(0)
    view.setHtml(PAGES[name].replace("%IMG%", image))
    QTimer.singleShot(seconds * 1000, step)


step()
view.show()
sys.exit(app.exec())
