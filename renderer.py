"""הצגת התרגום על המסך.

מקבל את הבלוקים מהמנוע ואת צילום האזור, ומחליט איך כל תרגום ייראה: צבע רקע
וצבע אותיות נדגמים מהמקור, והעברית נכתבת באותו מקום. אפשר להחליף את הקובץ הזה
בשיטת הצגה אחרת בלי לגעת בזיהוי ובתרגום.
"""
from dataclasses import dataclass

import numpy as np
from PyQt6.QtCore import QRectF, Qt
from PyQt6.QtGui import QColor, QFont, QFontMetricsF, QImage, QTextOption

import config


@dataclass
class StyledBlock:
    rect: QRectF      # ביחידות מסך, יחסית לפינת אזור התרגום
    he: str
    lines: int
    bg: QColor
    fg: QColor
    patch: object = None   # QImage לרקע לא אחיד, או None לרקע בצבע אחד
    font: object = None    # הגופן שהותאם לבלוק (מחושב פעם אחת, בציור הראשון)


def image_to_array(image):
    image = image.convertToFormat(QImage.Format.Format_RGB888)
    w, h = image.width(), image.height()
    bits = image.constBits()
    bits.setsize(image.sizeInBytes())
    arr = np.frombuffer(bits, np.uint8).reshape(h, image.bytesPerLine())[:, : w * 3]
    return arr.reshape(h, w, 3).copy()


def _luminance(c):
    return 0.299 * c[0] + 0.587 * c[1] + 0.114 * c[2]


def _sample_colors(arr, x0, y0, x1, y1):
    """צבע הרקע = הצבע הנפוץ במסגרת שסביב הטקסט; צבע האותיות = הרחוק ממנו ביותר."""
    H, W = arr.shape[:2]
    region = arr[max(y0, 0):min(y1, H), max(x0, 0):min(x1, W)]
    if region.shape[0] < 5 or region.shape[1] < 5:
        return (255, 255, 255), (0, 0, 0), None

    ring = np.concatenate([
        region[:2].reshape(-1, 3), region[-2:].reshape(-1, 3),
        region[:, :2].reshape(-1, 3), region[:, -2:].reshape(-1, 3),
    ])
    q = (ring >> 4).astype(np.int32)
    keys = (q[:, 0] << 8) | (q[:, 1] << 4) | q[:, 2]
    values, counts = np.unique(keys, return_counts=True)
    top = counts.argmax()
    busy = counts[top] / len(keys) < 0.45      # רקע לא אחיד (תמונה, מעבר צבע)
    bg = ring.mean(0) if busy else np.median(ring[keys == values[top]], axis=0)

    inner = region.reshape(-1, 3).astype(np.int32)
    dist = np.abs(inner - bg).sum(1)
    far = dist.max()
    fg = np.median(inner[dist >= 0.75 * far], axis=0) if far >= 60 else bg
    if busy or abs(_luminance(fg) - _luminance(bg)) < 70:
        fg = (0, 0, 0) if _luminance(bg) > 140 else (255, 255, 255)
    return tuple(int(v) for v in bg), tuple(int(v) for v in fg), (_blend_patch(region) if busy else None)


def _smooth(line):
    """ממוצע נע לאורך שורת/עמודת פיקסלים, כדי שלא ייווצרו פסים."""
    k = max(3, len(line) // 6) | 1
    padded = np.pad(line.astype(np.float32), ((k // 2, k // 2), (0, 0)), mode="edge")
    return np.stack([np.convolve(padded[:, c], np.ones(k) / k, mode="valid") for c in range(3)], axis=1)


def _blend_patch(region):
    """רקע לא אחיד: ממלאים את השטח במעבר רך בין הפיקסלים שמסביב לטקסט, במקום בצבע אחד."""
    h, w = region.shape[:2]
    left, right = _smooth(region[:, 0]), _smooth(region[:, -1])
    top, bottom = _smooth(region[0]), _smooth(region[-1])
    tx = np.linspace(0, 1, w, dtype=np.float32)[None, :, None]
    ty = np.linspace(0, 1, h, dtype=np.float32)[:, None, None]
    across = left[:, None, :] * (1 - tx) + right[:, None, :] * tx
    down = top[None, :, :] * (1 - ty) + bottom[None, :, :] * ty
    patch = np.ascontiguousarray(((across + down) / 2).clip(0, 255).astype(np.uint8))
    return QImage(patch.tobytes(), w, h, w * 3, QImage.Format.Format_RGB888).copy()


def style_blocks(arr, blocks, width, height):
    """arr = צילום האזור (פיקסלים פיזיים); width/height = גודל האזור ביחידות מסך."""
    H, W = arr.shape[:2]
    sx, sy = W / width, H / height
    styled = []
    for b in blocks:
        rect = QRectF(b.x * width, b.y * height, b.w * width, b.h * height)
        c = cover_of(rect)
        bg, fg, patch = _sample_colors(
            arr, int(c.left() * sx), int(c.top() * sy), int(c.right() * sx), int(c.bottom() * sy))
        styled.append(StyledBlock(rect, b.he, b.lines, QColor(*bg), QColor(*fg), patch))
    return styled


def cover_of(rect):
    """השטח שמכסה את הטקסט המקורי — קצת יותר גדול מהטקסט עצמו."""
    return rect.adjusted(-4, -3, 4, 3)


def _fit_font(block, cover):
    multi = block.lines > 1
    flags = (Qt.TextFlag.TextWordWrap.value if multi else Qt.TextFlag.TextSingleLine.value)
    if multi:
        px = block.rect.height() / block.lines * 0.78
    else:
        px = block.rect.height() * 1.05
    px = max(px, config.MIN_FONT_PX)
    font = QFont(config.FONT_FAMILY)
    while True:
        font.setPixelSize(int(px))
        need = QFontMetricsF(font).boundingRect(
            QRectF(0, 0, cover.width(), 100000), flags, block.he)
        if (need.width() <= cover.width() and need.height() <= cover.height() * 1.15) \
                or px <= config.MIN_FONT_PX:
            return font
        px -= 1


def paint_blocks(painter, styled):
    for block in styled:
        cover = cover_of(block.rect)
        if block.patch is not None:
            painter.drawImage(cover, block.patch)
        else:
            painter.fillRect(cover, block.bg)
        if block.font is None:
            block.font = _fit_font(block, cover)
        painter.setFont(block.font)
        painter.setPen(block.fg)
        option = QTextOption()
        option.setTextDirection(Qt.LayoutDirection.RightToLeft)
        if block.lines > 1:
            option.setWrapMode(QTextOption.WrapMode.WordWrap)
            option.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        else:
            option.setWrapMode(QTextOption.WrapMode.NoWrap)
            option.setAlignment(Qt.AlignmentFlag.AlignCenter)
        painter.drawText(cover, block.he, option)
