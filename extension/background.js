// שירות הרקע: מפעיל את התוסף בלחיצה, מצלם את הלשונית, מעביר זיהוי טקסט לחלון העזר
// ומטפל במנועי הגיבוי. לא שומר מצב במשתנים — השירות נסגר ונפתח לבד.

const GEMINI_MODELS = ['gemini-flash-latest', 'gemini-3.5-flash'];
const COOLDOWN_MS = 30 * 60 * 1000;

// ---------- הפעלה ----------
async function activate(tab) {
  if (!tab || tab.id == null) return;
  try {
    await chrome.scripting.executeScript({ target: { tabId: tab.id }, files: ['content.js'] });
  } catch (e) {
    await setBadge(tab.id, 'err');
    console.warn('לא ניתן להפעיל בדף הזה:', e.message);
  }
}
chrome.action.onClicked.addListener(activate);
chrome.commands.onCommand.addListener(async (cmd, tab) => {
  if (cmd !== 'toggle-box') return;
  if (!tab) [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  await activate(tab);
});

// ---------- סמל ----------
async function setBadge(tabId, state) {
  const map = { on: ['●', '#107C10'], err: ['!', '#E51400'], '': ['', '#E51400'] };
  const [text, color] = map[state] || map[''];
  try {
    await chrome.action.setBadgeText({ tabId, text });
    await chrome.action.setBadgeBackgroundColor({ tabId, color });
  } catch (e) { /* הלשונית נסגרה */ }
}

// ---------- חלון עזר לזיהוי טקסט ----------
let creatingOffscreen = null;
async function ensureOffscreen() {
  const url = chrome.runtime.getURL('offscreen.html');
  const ctxs = await chrome.runtime.getContexts({ contextTypes: ['OFFSCREEN_DOCUMENT'], documentUrls: [url] });
  if (ctxs.length) return;
  if (!creatingOffscreen) {
    creatingOffscreen = chrome.offscreen.createDocument({
      url: 'offscreen.html', reasons: ['WORKERS'], justification: 'זיהוי טקסט מתוך תמונה בתוך הדפדפן'
    }).finally(() => { creatingOffscreen = null; });
  }
  await creatingOffscreen;
}

// ---------- מנועי גיבוי ----------
async function getSettings() {
  return chrome.storage.local.get({ geminiKey: '' });
}

async function inCooldown() {
  const { cooldownUntil = 0 } = await chrome.storage.session.get('cooldownUntil');
  return Date.now() < cooldownUntil;
}
async function startCooldown() {
  await chrome.storage.session.set({ cooldownUntil: Date.now() + COOLDOWN_MS });
}

// Google Translate (נקודת קצה לא רשמית). מחזיר מערך באותו אורך כמו הקלט.
async function googleBatch(texts, source, target) {
  const SEP = '\n';
  const body = new URLSearchParams({ q: texts.join(SEP) });
  const sl = source && source !== 'auto' ? (source === 'he' ? 'iw' : source) : 'auto';
  const tl = target === 'he' ? 'iw' : target;
  const res = await fetch(
    `https://translate.googleapis.com/translate_a/single?client=gtx&sl=${sl}&tl=${tl}&dt=t`,
    { method: 'POST', headers: { 'Content-Type': 'application/x-www-form-urlencoded' }, body });
  if (res.status === 429) { await startCooldown(); throw new Error('rate'); }
  if (res.status === 418) throw new Error('netfree');
  if (!res.ok) throw new Error('http ' + res.status);
  const j = await res.json();
  const full = (j[0] || []).map(s => s[0]).join('');
  const parts = full.split(SEP);
  if (parts.length !== texts.length) throw new Error('mismatch');
  return parts.map(s => s.trim());
}

async function googleTranslate(texts, source, target) {
  if (await inCooldown()) throw new Error('rate');
  // מנסים את כולם יחד; אם מספר השורות לא חוזר שווה — מחלקים לשניים (לא שורה-שורה, כדי לא לשלוח עשרות בקשות)
  const run = async (arr, depth) => {
    try { return await googleBatch(arr, source, target); }
    catch (e) {
      if (e.message === 'mismatch' && arr.length > 1 && depth < 6) {
        const mid = arr.length >> 1;
        return [...await run(arr.slice(0, mid), depth + 1), ...await run(arr.slice(mid), depth + 1)];
      }
      throw e;
    }
  };
  const out = [];
  const CHUNK = 2500;
  let cur = [], size = 0;
  const flush = async () => { if (cur.length) out.push(...await run(cur, 0)); cur = []; size = 0; };
  for (const t of texts.map(s => s.replace(/\n/g, ' '))) {
    if (size + t.length > CHUNK) await flush();
    cur.push(t); size += t.length;
  }
  await flush();
  return out;
}

async function geminiTranslate(texts, target, key) {
  const lang = target === 'he' ? 'Hebrew' : target;
  const prompt = `Translate each string in the JSON array to ${lang}. Keep the same order and the same number of items. ` +
    `Do not translate code, URLs or brand names. Reply with ONLY a JSON array of strings.\n` + JSON.stringify(texts);
  let lastErr = 'gemini';
  for (const model of GEMINI_MODELS) {
    const res = await fetch(
      `https://generativelanguage.googleapis.com/v1beta/models/${model}:generateContent`,
      { method: 'POST', headers: { 'Content-Type': 'application/json', 'x-goog-api-key': key },
        body: JSON.stringify({ contents: [{ parts: [{ text: prompt }] }], generationConfig: { responseMimeType: 'application/json' } }) });
    if (res.status === 429 || res.status === 404) { lastErr = 'gemini ' + res.status; continue; }
    if (res.status === 418) throw new Error('netfree');
    if (!res.ok) throw new Error('gemini http ' + res.status);
    const j = await res.json();
    const raw = j.candidates?.[0]?.content?.parts?.[0]?.text || '[]';
    const arr = JSON.parse(raw);
    if (Array.isArray(arr) && arr.length === texts.length) return arr.map(String);
    lastErr = 'gemini mismatch';
  }
  throw new Error(lastErr);
}

async function fallbackTranslate(texts, source, target) {
  const { geminiKey } = await getSettings();
  if (geminiKey) {
    try { return await geminiTranslate(texts, target, geminiKey); } catch (e) { if (e.message === 'netfree') throw e; }
  }
  return googleTranslate(texts, source, target);
}

// ---------- הודעות ----------
chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
  if (!msg || msg.target === 'offscreen') return false;
  const tabId = sender.tab && sender.tab.id;
  (async () => {
    switch (msg.type) {
      case 'capture': {
        const dataUrl = await chrome.tabs.captureVisibleTab(sender.tab.windowId, { format: 'png' });
        return { ok: true, dataUrl };
      }
      case 'ocr': {
        await ensureOffscreen();
        const r = await chrome.runtime.sendMessage({ target: 'offscreen', type: 'ocr-run', image: msg.image, langs: msg.langs, scale: msg.scale });
        return r || { ok: false, error: 'אין תשובה מחלון הזיהוי' };
      }
      case 'fallback': {
        const texts = await fallbackTranslate(msg.texts, msg.source, msg.target);
        return { ok: true, texts };
      }
      case 'badge': await setBadge(tabId, msg.state); return { ok: true };
      case 'fullpage': {
        // הפעלת תרגום דף בכל המסגרות שהתוסף רשאי להיכנס אליהן
        try {
          // הדגל מונע מההזרקה החוזרת להסתיר את הריבוע (הזרקה רגילה = הצג/הסתר)
          await chrome.scripting.executeScript({ target: { tabId, allFrames: true }, func: () => { globalThis.__stHeQuiet = true; } });
          await chrome.scripting.executeScript({ target: { tabId, allFrames: true }, files: ['content.js'] });
        } catch (e) { /* מסגרות שאין גישה אליהן */ }
        try { await chrome.tabs.sendMessage(tabId, { type: 'fp', on: msg.on, opts: msg.opts }); } catch (e) { /* ignore */ }
        return { ok: true };
      }
      case 'options': await chrome.runtime.openOptionsPage(); return { ok: true };
      default: return null;
    }
  })().then(sendResponse, e => sendResponse({ ok: false, error: e.message || String(e) }));
  return true;
});

chrome.tabs.onUpdated.addListener((tabId, info) => { if (info.status === 'loading') setBadge(tabId, ''); });
