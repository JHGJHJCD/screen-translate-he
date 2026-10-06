// חלון העזר: זיהוי טקסט מתוך תמונה (Tesseract) בתוך הדפדפן, בלי לשלוח כלום החוצה.
// אנגלית ארוזה בתוך התוסף; שפות אחרות יורדות פעם אחת מהרשת ונשמרות.

const BASE = chrome.runtime.getURL('vendor/tesseract/');
const CDN_LANG = 'https://cdn.jsdelivr.net/npm/@tesseract.js-data/{lang}/4.0.0_best_int';
let current = { key: '', worker: null };
let queue = Promise.resolve();

async function getWorker(langs) {
  if (current.key === langs && current.worker) return current.worker;
  if (current.worker) { try { await current.worker.terminate(); } catch (e) { /* ignore */ } }
  const bundledOnly = langs === 'eng';
  const opts = {
    workerPath: BASE + 'worker.min.js',
    corePath: BASE + 'core',
    workerBlobURL: false,
    gzip: true,
    cacheMethod: bundledOnly ? 'none' : 'write',
    logger: () => {}
  };
  if (bundledOnly) opts.langPath = BASE + 'lang';
  else opts.langPath = CDN_LANG.replace('{lang}', langs.split('+')[0]);
  const worker = await Tesseract.createWorker(langs, 1, opts);
  current = { key: langs, worker };
  return worker;
}

// img.decode() נתקע במסמך נסתר, לכן טוענים דרך createImageBitmap
async function loadImage(src) {
  return createImageBitmap(await (await fetch(src)).blob());
}

async function runOcr({ image, langs = 'eng', scale = 2 }) {
  console.log('[ocr] start', langs, scale, image && image.length);
  const img = await loadImage(image);
  const s = Math.max(1, Math.min(3, scale));
  const c = document.createElement('canvas');
  c.width = Math.round(img.width * s); c.height = Math.round(img.height * s);
  const g = c.getContext('2d');
  g.imageSmoothingQuality = 'high';
  g.drawImage(img, 0, 0, c.width, c.height);
  console.log('[ocr] image', img.width, img.height);
  const worker = await getWorker(langs);
  console.log('[ocr] worker ready');
  const { data } = await worker.recognize(c, {}, { blocks: true });
  console.log('[ocr] done, blocks:', (data.blocks || []).length);
  const paragraphs = [];
  for (const b of data.blocks || []) {
    for (const p of b.paragraphs || []) {
      const lines = (p.lines || []).map(l => ({
        text: (l.text || '').trim(), conf: l.confidence,
        x0: l.bbox.x0 / s, y0: l.bbox.y0 / s, x1: l.bbox.x1 / s, y1: l.bbox.y1 / s
      })).filter(l => l.text);
      if (!lines.length) continue;
      paragraphs.push({
        text: lines.map(l => l.text).join(' '),
        conf: p.confidence,
        x0: p.bbox.x0 / s, y0: p.bbox.y0 / s, x1: p.bbox.x1 / s, y1: p.bbox.y1 / s,
        lines
      });
    }
  }
  return { paragraphs, width: img.width, height: img.height };
}

chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
  if (!msg || msg.target !== 'offscreen' || msg.type !== 'ocr-run') return false;
  // זיהוי אחד בכל פעם (העובד לא תומך בריצה מקבילה)
  queue = queue.then(() => runOcr(msg)).then(
    r => sendResponse({ ok: true, ...r }),
    e => sendResponse({ ok: false, error: e && e.message || String(e) }));
  return true;
});
