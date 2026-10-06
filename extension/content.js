// הסקריפט שרץ בתוך הדף: הריבוע האדום, תרגום כל הדף, וציור התרגום.
// הזרקה חוזרת = הצג/הסתר (אלא אם background סימן __stHeQuiet).
(() => {
  const g = globalThis;
  const quiet = !!g.__stHeQuiet;
  g.__stHeQuiet = false;
  if (g.__stHe) { if (!quiet) g.__stHe.toggleUI(); return; }

  const IS_TOP = window === window.top;
  const RTL_LANGS = ['he', 'ar', 'fa', 'ur'];
  const BANK_RE = /(^|\.)(bank|banking|paypal|leumi|hapoalim|discountbank|mizrahi-tefahot|fibi|isracard|cal-online|max\.co\.il|chase|wellsfargo|bankofamerica)/i;
  const RED = '#E51400', GREEN = '#107C10', GRAY = '#5A5A5A';
  const BORDER = 4, BAR_H = 30;

  // ---------- הגדרות ----------
  const S = { source: 'auto', target: 'he', ocrLangs: 'eng', fallback: 'safe' };
  const settingsReady = chrome.storage.local.get(S).then(v => Object.assign(S, v)).catch(() => {});
  chrome.storage.onChanged.addListener((ch, area) => {
    if (area !== 'local') return;
    for (const k of Object.keys(S)) if (ch[k]) S[k] = ch[k].newValue;
  });

  const send = async (msg) => {
    try { return await chrome.runtime.sendMessage(msg); }
    catch (e) { return { ok: false, error: 'התוסף עודכן — רענן את הדף' }; }
  };

  // ---------- מנוע תרגום ----------
  const E = { translators: new Map(), detector: null, cache: new Map() };

  function isSensitive() {
    try { if (document.querySelector('input[type=password]')) return true; } catch (e) { /* ignore */ }
    return BANK_RE.test(location.hostname);
  }
  function allowFallback() {
    return S.fallback === 'always' || (S.fallback === 'safe' && !isSensitive());
  }

  async function detectLang(text) {
    if (!('LanguageDetector' in self)) return null;
    try {
      if (!E.detector) {
        if ((await LanguageDetector.availability()) !== 'available') return null;
        E.detector = await LanguageDetector.create();
      }
      const r = await E.detector.detect(text.slice(0, 600));
      return r[0] && r[0].confidence > 0.5 && r[0].detectedLanguage !== 'und' ? r[0].detectedLanguage : null;
    } catch (e) { return null; }
  }
  async function resolveSource(sample) {
    if (S.source && S.source !== 'auto') return S.source;
    const d = await detectLang(sample);
    if (d) return d;
    const htmlLang = (document.documentElement.lang || '').slice(0, 2).toLowerCase();
    return htmlLang || 'en';
  }

  async function builtinState(src, tgt) {
    if (!('Translator' in self)) return 'missing';
    try { return await Translator.availability({ sourceLanguage: src, targetLanguage: tgt }); }
    catch (e) { return 'missing'; }
  }
  function getTranslator(src, tgt, monitor) {
    const key = src + '>' + tgt;
    if (!E.translators.has(key)) {
      const p = Translator.create({ sourceLanguage: src, targetLanguage: tgt, monitor });
      p.catch(() => E.translators.delete(key));
      E.translators.set(key, p);
    }
    return E.translators.get(key);
  }
  // חייב להיקרא מתוך לחיצה של המשתמש (דרישת כרום להורדת מודל)
  async function downloadModel(src, tgt, onProgress) {
    E.translators.delete(src + '>' + tgt);
    const t = await getTranslator(src, tgt, (m) => m.addEventListener('downloadprogress', (e) => onProgress && onProgress(e.loaded)));
    return t;
  }

  class NeedModel extends Error { constructor(src, tgt, state) { super('need-model'); this.src = src; this.tgt = tgt; this.state = state; } }

  async function pool(items, limit, fn) {
    const out = new Array(items.length);
    let i = 0;
    await Promise.all(Array.from({ length: Math.min(limit, items.length) }, async () => {
      while (i < items.length) { const k = i++; out[k] = await fn(items[k], k); }
    }));
    return out;
  }

  // מחזיר מערך תרגומים (null = נכשל). זורק NeedModel / Error עם הודעה למשתמש.
  // המתרגם המובנה מחזיר לפעמים עברית מנוקדת, וזה נראה רע בדף; מסירים ניקוד וטעמים
  const noNiqqud = (s) => (typeof s === 'string' ? s.replace(/[֑-ׇ]/g, '') : s);
  async function translateTexts(texts, src, tgt) {
    await settingsReady;
    const res = new Array(texts.length).fill(null);
    const todo = [];
    texts.forEach((t, i) => {
      const c = E.cache.get(src + '|' + t);
      if (c != null) res[i] = c; else todo.push(i);
    });
    if (!todo.length) return res;
    const state = await builtinState(src, tgt);
    const fb = allowFallback();
    if (state === 'available') {
      const tr = await getTranslator(src, tgt);
      const outs = await pool(todo, 4, async (i) => { try { return noNiqqud(await tr.translate(texts[i])); } catch (e) { return null; } });
      todo.forEach((i, k) => { res[i] = outs[k]; if (outs[k] != null) E.cache.set(src + '|' + texts[i], outs[k]); });
      return res;
    }
    if (!fb) {
      if (state === 'downloadable' || state === 'downloading') throw new NeedModel(src, tgt, state);
      throw new Error(state === 'unavailable' ? 'צמד השפות הזה לא נתמך בדפדפן' : 'הדפדפן הזה בלי מתרגם מובנה');
    }
    const r = await send({ type: 'fallback', texts: todo.map(i => texts[i]), source: src, target: tgt });
    if (!r || !r.ok) {
      const m = r && r.error;
      if (m === 'rate') throw new Error('גוגל חסמה זמנית (יותר מדי בקשות) — נסה בעוד כמה דקות');
      if (m === 'netfree') throw new Error('נטפרי חסם את בקשת התרגום');
      throw new Error('התרגום נכשל: ' + (m || 'שגיאה'));
    }
    todo.forEach((i, k) => { const t = noNiqqud(r.texts[k]); res[i] = t; if (t) E.cache.set(src + '|' + texts[i], t); });
    if (state === 'downloadable') res.needModelHint = true;
    return res;
  }

  // ---------- עזרי טקסט ----------
  const reLetter = /\p{L}/gu, reHeb = /[֐-׿]/g;
  function hebRatio(s) {
    const l = (s.match(reLetter) || []).length;
    if (!l) return 0;
    return (s.match(reHeb) || []).length / l;
  }
  function skipText(s) {
    if (!reLetter.test(s)) { reLetter.lastIndex = 0; return true; }
    reLetter.lastIndex = 0;
    if (S.target === 'he' && hebRatio(s) >= 0.5) return true;
    const t = s.trim();
    if (!/\s/.test(t) && (/[a-z][A-Z]/.test(t) || /[\d_@./\\:#]/.test(t))) return true; // שם מותג/קוד/כתובת
    return false;
  }

  // ---------- ממשק אפשרויות סטטוס (רק במסגרת העליונה) ----------
  let ui = null;
  const status = (text, state, extra) => { if (ui) ui.setStatus(text, state, extra); };

  // ---------- תרגום כל הדף ----------
  const SKIP_TAGS = new Set(['SCRIPT', 'STYLE', 'NOSCRIPT', 'CODE', 'PRE', 'TEXTAREA', 'INPUT', 'SELECT', 'OPTION', 'SVG', 'CANVAS', 'IFRAME', 'KBD', 'SAMP']);
  const fp = { on: false, src: 'en', pending: new Set(), done: new Map(), parents: new Map(), obs: null, busy: false, timer: 0, count: 0, retry: 0 };

  function nodeOk(n) {
    const el = n.parentElement;
    if (!el || SKIP_TAGS.has(el.tagName.toUpperCase())) return false;
    if (el.closest('[translate=no],.notranslate,[contenteditable=""],[contenteditable=true],#st-he-host')) return false;
    const v = n.nodeValue;
    if (!v || v.trim().length < 2) return false;
    return !skipText(v);
  }
  function collect(root) {
    if (!root) return;
    if (root.nodeType === 3) { if (!fp.done.has(root) && nodeOk(root)) fp.pending.add(root); return; }
    if (root.nodeType !== 1 || root.id === 'st-he-host') return;
    const w = document.createTreeWalker(root, NodeFilter.SHOW_TEXT, {
      acceptNode: (n) => (!fp.done.has(n) && nodeOk(n)) ? NodeFilter.FILTER_ACCEPT : NodeFilter.FILTER_REJECT
    });
    while (w.nextNode()) fp.pending.add(w.currentNode);
  }
  function near(n) {
    const el = n.parentElement;
    if (!el) return false;
    const r = el.getBoundingClientRect();
    if (r.width === 0 && r.height === 0) return false;
    return r.bottom > -800 && r.top < innerHeight + 800 && r.right > -200 && r.left < innerWidth + 200;
  }
  function schedule(ms = 120) {
    if (!fp.on || fp.timer) return;
    fp.timer = setTimeout(() => { fp.timer = 0; pump(); }, ms);
  }
  async function pump() {
    if (fp.busy || !fp.on) return;
    fp.busy = true;
    try {
      while (fp.on) {
        const batch = [];
        for (const n of fp.pending) {
          if (!n.isConnected) { fp.pending.delete(n); continue; }
          if (near(n)) { batch.push(n); if (batch.length >= 30) break; }
        }
        if (!batch.length) break;
        batch.forEach(n => fp.pending.delete(n));
        await translateNodes(batch);
        await new Promise(r => requestAnimationFrame(r));
      }
    } catch (e) {
      handleFpError(e);
    } finally { fp.busy = false; }
  }
  async function translateNodes(nodes) {
    const texts = [...new Set(nodes.map(n => n.nodeValue.trim()))];
    const out = await translateTexts(texts, fp.src, S.target);
    const map = new Map(texts.map((t, i) => [t, out[i]]));
    for (const n of nodes) {
      const orig = n.nodeValue;
      const tr = map.get(orig.trim());
      if (!tr || !n.isConnected) continue;
      const lead = orig.match(/^\s*/)[0], trail = orig.match(/\s*$/)[0];
      const val = lead + tr + trail;
      fp.done.set(n, { orig, tr: val, n: (fp.done.get(n)?.n || 0) + 1 });
      n.nodeValue = val;
      const el = n.parentElement;
      if (el && RTL_LANGS.includes(S.target) && !fp.parents.has(el)) {
        // פריט רשימה: גם הכיוון עצמו מתהפך, אחרת הנקודה נשארת בצד שמאל והטקסט בצד ימין
        fp.parents.set(el, { bidi: el.style.unicodeBidi, dir: el.style.direction });
        el.style.unicodeBidi = 'plaintext';
        if (getComputedStyle(el).display === 'list-item') el.style.direction = 'rtl';
      }
      fp.count++;
    }
    if (out.needModelHint) status('מתורגם דרך גוגל — להורדת המנוע המקומי: הגדרות', 'shown');
    else status(`תורגמו ${fp.count} קטעים`, 'shown');
  }
  function handleFpError(e) {
    if (e instanceof NeedModel) {
      fp.pending.clear();
      status('מודל התרגום לא הורד', 'error', { download: { src: e.src, tgt: e.tgt } });
      return;
    }
    status(e.message || 'שגיאה בתרגום', 'error');
    clearTimeout(fp.retry);
    fp.retry = setTimeout(() => schedule(0), 15000);
  }

  function fpMutations(list) {
    if (!fp.on) return;
    for (const m of list) {
      if (m.type === 'characterData') {
        const rec = fp.done.get(m.target);
        if (rec && m.target.nodeValue === rec.tr) continue;       // השינוי שלנו
        if (rec && rec.n >= 3) continue;                          // האתר נלחם בנו — מוותרים
        if (rec) fp.done.delete(m.target);
        collect(m.target);
      } else {
        m.addedNodes.forEach(n => collect(n));
      }
    }
    schedule(250);
  }

  async function fpStart(opts) {
    if (fp.on) return;
    await settingsReady;
    fp.on = true; fp.count = 0;
    status('מתרגם את הדף…', 'work');
    const sample = (document.body?.innerText || '').replace(/\s+/g, ' ').slice(0, 1500);
    fp.src = await resolveSource(sample);
    if (!fp.on) return;
    if (fp.src === S.target) { status('הדף כבר בשפת היעד', 'idle'); fp.on = false; ui && ui.fpEnded(); return; }
    collect(document.body);
    fp.obs = new MutationObserver(fpMutations);
    fp.obs.observe(document.documentElement, { childList: true, subtree: true, characterData: true });
    addEventListener('scroll', onFpScroll, { passive: true, capture: true });
    addEventListener('resize', onFpScroll, { passive: true });
    schedule(0);
  }
  const onFpScroll = () => schedule(200);
  function fpStop() {
    if (!fp.on && !fp.done.size) return;
    fp.on = false;
    clearTimeout(fp.timer); fp.timer = 0; clearTimeout(fp.retry);
    if (fp.obs) { fp.obs.disconnect(); fp.obs = null; }
    removeEventListener('scroll', onFpScroll, { capture: true });
    removeEventListener('resize', onFpScroll);
    for (const [n, rec] of fp.done) { if (n.nodeValue === rec.tr) n.nodeValue = rec.orig; }
    for (const [el, prev] of fp.parents) { el.style.unicodeBidi = prev.bidi; el.style.direction = prev.dir; }
    fp.done.clear(); fp.parents.clear(); fp.pending.clear(); fp.count = 0;
  }

  chrome.runtime.onMessage.addListener((msg) => {
    if (!msg || msg.type !== 'fp') return;
    if (msg.on) fpStart(msg.opts); else fpStop();
  });

  // ---------- הריבוע (רק במסגרת העליונה) ----------
  const CSS = `
:host { all: initial; }
.box { position: absolute; border: ${BORDER}px solid var(--c); box-sizing: border-box; pointer-events: none; font: 13px/1.2 "Segoe UI", Arial, sans-serif; direction: rtl; }
canvas { position: absolute; inset: 0; width: 100%; height: 100%; pointer-events: none; }
.bar { position: absolute; bottom: 100%; margin-bottom: ${BORDER - 0}px; left: -${BORDER}px; width: max(calc(100% + ${BORDER * 2}px), 400px); height: ${BAR_H}px; background: var(--c); color: #fff; display: flex; align-items: center; gap: 4px; padding: 0 6px; pointer-events: auto; cursor: move; box-sizing: border-box; user-select: none; }
.bar .st { flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; padding: 0 4px; }
.bar button { all: unset; cursor: pointer; padding: 2px 8px; border-radius: 4px; background: rgba(255,255,255,.18); color: #fff; font-size: 12px; white-space: nowrap; }
.bar button:hover { background: rgba(255,255,255,.34); }
.bar button[hidden] { display: none; }
.bar button.dl { background: #fff; color: #222; font-weight: 700; }
.box.fp { left: 0 !important; top: ${BAR_H + BORDER}px !important; width: 100% !important; height: calc(100% - ${BAR_H + BORDER}px) !important; }
.box.fp canvas, .box.fp .e, .box.fp .h { display: none; }
.e { position: absolute; pointer-events: auto; cursor: move; }
.e.n { top: -${BORDER + 4}px; left: 0; right: 0; height: 12px; } .e.s { bottom: -${BORDER + 4}px; left: 0; right: 0; height: 12px; }
.e.w { left: -${BORDER + 4}px; top: 0; bottom: 0; width: 12px; } .e.e { right: -${BORDER + 4}px; top: 0; bottom: 0; width: 12px; }
.h { position: absolute; width: 18px; height: 18px; pointer-events: auto; bottom: -${BORDER + 5}px; }
.h.se { right: -${BORDER + 5}px; cursor: nwse-resize; } .h.sw { left: -${BORDER + 5}px; cursor: nesw-resize; }
`;

  function createUI() {
    const host = document.createElement('div');
    host.id = 'st-he-host';
    host.style.cssText = 'all:initial;position:fixed;inset:0;z-index:2147483647;pointer-events:none;';
    const root = host.attachShadow({ mode: 'open' });
    root.innerHTML = `<style>${CSS}</style>
<div class="box" id="box">
  <canvas id="cv"></canvas>
  <div class="bar" id="bar">
    <span class="st" id="st">תרגום מסך</span>
    <button id="dl" class="dl" hidden>הורד מודל</button>
    <button id="refresh" title="צלם ותרגם מחדש">רענן</button>
    <button id="full" title="תרגום כל הדף">מסך מלא</button>
    <button id="pause" title="השהיה">השהה</button>
    <button id="opts" title="הגדרות">הגדרות</button>
    <button id="close" title="הסתר (Alt+Shift+T)">✕</button>
  </div>
  <div class="e n" data-d="move"></div><div class="e s" data-d="move"></div><div class="e w" data-d="move"></div><div class="e e" data-d="move"></div>
  <div class="h se" data-d="se"></div><div class="h sw" data-d="sw"></div>
</div>`;
    document.documentElement.appendChild(host);
    const $ = (id) => root.getElementById(id);
    const el = { box: $('box'), cv: $('cv'), bar: $('bar'), st: $('st'), dl: $('dl'), pause: $('pause'), full: $('full') };
    const u = { host, el, visible: false, paused: false, fullPage: false, runId: 0, geo: { x: 80, y: 120, w: 440, h: 280 }, timers: {}, shown: false };

    // --- מיקום ---
    function clampGeo() {
      const g2 = u.geo;
      g2.w = Math.max(160, Math.min(g2.w, innerWidth - 8));
      g2.h = Math.max(80, Math.min(g2.h, innerHeight - BAR_H - 12));
      g2.x = Math.max(0, Math.min(g2.x, innerWidth - g2.w));
      g2.y = Math.max(BAR_H + BORDER + 2, Math.min(g2.y, innerHeight - g2.h));
    }
    function applyGeo() {
      clampGeo();
      const g2 = u.geo;
      el.box.style.left = g2.x + 'px'; el.box.style.top = g2.y + 'px';
      el.box.style.width = g2.w + 'px'; el.box.style.height = g2.h + 'px';
    }
    const saveGeo = () => { try { chrome.storage.local.set({ box: u.geo }); } catch (e) { /* ignore */ } };
    function interior() {
      const g2 = u.geo;
      return { x: g2.x + BORDER, y: g2.y + BORDER, w: g2.w - BORDER * 2, h: g2.h - BORDER * 2 };
    }

    // --- מצב ---
    u.setStatus = (text, state, extra) => {
      el.st.textContent = text;
      const color = state === 'shown' ? GREEN : (u.paused ? GRAY : RED);
      el.box.style.setProperty('--c', color);
      u.shown = state === 'shown';
      el.dl.hidden = !(extra && extra.download);
      u.dlInfo = extra && extra.download;
      send({ type: 'badge', state: (u.shown || fp.on) ? 'on' : (state === 'error' ? 'err' : '') });
    };
    u.fpEnded = () => { u.fullPage = false; el.full.textContent = 'מסך מלא'; el.box.classList.remove('fp'); };
    const clearCanvas = () => { const c = el.cv; c.getContext('2d').clearRect(0, 0, c.width, c.height); };

    // --- גרירה ושינוי גודל ---
    let drag = null;
    function startDrag(ev, mode) {
      if (ev.button !== 0) return;
      if (ev.target.closest && ev.target.closest('button')) return;
      ev.preventDefault();
      drag = { mode, sx: ev.clientX, sy: ev.clientY, g: { ...u.geo } };
      ev.currentTarget.setPointerCapture(ev.pointerId);
      clearCanvas(); u.runId++;
    }
    function moveDrag(ev) {
      if (!drag) return;
      const dx = ev.clientX - drag.sx, dy = ev.clientY - drag.sy;
      const g0 = drag.g, g2 = u.geo;
      if (drag.mode === 'move') { g2.x = g0.x + dx; g2.y = g0.y + dy; }
      else if (drag.mode === 'se') { g2.w = g0.w + dx; g2.h = g0.h + dy; }
      else if (drag.mode === 'sw') { g2.x = g0.x + dx; g2.w = g0.w - dx; g2.h = g0.h + dy; }
      applyGeo();
    }
    function endDrag() {
      if (!drag) return;
      drag = null; saveGeo(); u.scheduleRun(450);
    }
    root.querySelectorAll('[data-d]').forEach(n => {
      n.addEventListener('pointerdown', (e) => startDrag(e, n.dataset.d));
      n.addEventListener('pointermove', moveDrag);
      n.addEventListener('pointerup', endDrag);
      n.addEventListener('pointercancel', endDrag);
    });
    el.bar.addEventListener('pointerdown', (e) => startDrag(e, 'move'));
    el.bar.addEventListener('pointermove', moveDrag);
    el.bar.addEventListener('pointerup', endDrag);

    // --- הרצה ---
    u.scheduleRun = (ms = 600) => {
      clearTimeout(u.timers.run);
      if (!u.visible || u.paused || u.fullPage) return;
      u.timers.run = setTimeout(() => u.run(), ms);
    };
    const raf2 = () => new Promise(r => requestAnimationFrame(() => requestAnimationFrame(r)));

    u.run = async function run() {
      if (!u.visible || u.paused || u.fullPage) return;
      await settingsReady;
      const id = ++u.runId;
      const stale = () => id !== u.runId || !u.visible || u.paused || u.fullPage;
      try {
        u.setStatus('מצלם…', 'work');
        el.cv.style.visibility = 'hidden';
        await raf2();
        const cap = await send({ type: 'capture' });
        if (stale()) return;
        if (!cap || !cap.ok) {
          el.cv.style.visibility = 'visible';
          u.setStatus('לא ניתן לצלם — לחץ על סמל התוסף שוב', 'error');
          return;
        }
        const bmp = await createImageBitmap(await (await fetch(cap.dataUrl)).blob());
        const scale = bmp.width / innerWidth;
        const r = interior();
        const sx = Math.max(0, Math.round(r.x * scale)), sy = Math.max(0, Math.round(r.y * scale));
        const sw = Math.min(bmp.width - sx, Math.round(r.w * scale)), sh = Math.min(bmp.height - sy, Math.round(r.h * scale));
        if (sw < 20 || sh < 20) { el.cv.style.visibility = 'visible'; u.setStatus('הריבוע קטן מדי', 'idle'); return; }
        const crop = document.createElement('canvas');
        crop.width = sw; crop.height = sh;
        const cx = crop.getContext('2d', { willReadFrequently: true });
        cx.drawImage(bmp, sx, sy, sw, sh, 0, 0, sw, sh);
        const img = cx.getImageData(0, 0, sw, sh);
        el.cv.style.visibility = 'visible';
        u.setStatus('מזהה טקסט…', 'work');
        const ocr = await send({ type: 'ocr', image: crop.toDataURL('image/png'), langs: S.ocrLangs, scale: sw < 800 ? 3 : sw < 1400 ? 2 : 1 });
        if (stale()) return;
        if (!ocr || !ocr.ok) { u.setStatus('זיהוי הטקסט נכשל: ' + ((ocr && ocr.error) || ''), 'error'); return; }
        const paras = splitParas(ocr.paragraphs.filter(p => p.conf >= 55 && /\p{L}{2}/u.test(p.text) && !(S.target === 'he' && hebRatio(p.text) >= 0.5)));
        if (!paras.length) { clearCanvas(); u.setStatus('לא זוהה טקסט לתרגום', 'idle'); return; }
        u.setStatus('מתרגם…', 'work');
        const src = await resolveSource(paras.map(p => p.text).join(' '));
        if (src === S.target) { clearCanvas(); u.setStatus('הטקסט כבר בשפת היעד', 'idle'); return; }
        const trs = await translateTexts(paras.map(p => p.text), src, S.target);
        if (stale()) return;
        draw(paras, trs, img);
        u.setStatus(trs.needModelHint ? 'מוצג (דרך גוגל — הגדרות: הורדת המנוע המקומי)' : `מוצג — ${trs.filter(Boolean).length} קטעים`, 'shown');
      } catch (e) {
        if (stale()) return;
        el.cv.style.visibility = 'visible';
        if (e instanceof NeedModel) u.setStatus('מודל התרגום לא הורד', 'error', { download: { src: e.src, tgt: e.tgt } });
        else u.setStatus(e.message || 'שגיאה', 'error');
      }
    };

    // --- ציור התרגום על הצילום ---
    function sampleBg(img, x0, y0, x1, y1) {
      const { width: W, height: H, data } = img;
      const buckets = new Map();
      const add = (x, y) => {
        if (x < 0 || y < 0 || x >= W || y >= H) return;
        const i = (y * W + x) * 4;
        const k = ((data[i] >> 3) << 10) | ((data[i + 1] >> 3) << 5) | (data[i + 2] >> 3);
        const b = buckets.get(k) || { n: 0, r: 0, g: 0, b: 0 };
        b.n++; b.r += data[i]; b.g += data[i + 1]; b.b += data[i + 2];
        buckets.set(k, b);
      };
      for (let ring = 1; ring <= 3; ring++) {
        for (let x = x0 - ring; x <= x1 + ring; x++) { add(x, y0 - ring); add(x, y1 + ring); }
        for (let y = y0 - ring; y <= y1 + ring; y++) { add(x0 - ring, y); add(x1 + ring, y); }
      }
      if (!buckets.size) for (let x = x0; x < x1; x += 2) { add(x, y0); add(x, y1); }
      let best = null;
      for (const b of buckets.values()) if (!best || b.n > best.n) best = b;
      return best ? [Math.round(best.r / best.n), Math.round(best.g / best.n), Math.round(best.b / best.n)] : [255, 255, 255];
    }
    function sampleFg(img, x0, y0, x1, y1, bg) {
      const { width: W, height: H, data } = img;
      let maxd = 0; const px = [];
      for (let y = Math.max(0, y0); y < Math.min(H, y1); y += 1) {
        for (let x = Math.max(0, x0); x < Math.min(W, x1); x += 1) {
          const i = (y * W + x) * 4;
          const d = Math.abs(data[i] - bg[0]) + Math.abs(data[i + 1] - bg[1]) + Math.abs(data[i + 2] - bg[2]);
          if (d > maxd) maxd = d;
          px.push([d, data[i], data[i + 1], data[i + 2]]);
        }
      }
      if (maxd < 90) { const lum = bg[0] * .3 + bg[1] * .59 + bg[2] * .11; return lum > 140 ? [20, 20, 20] : [240, 240, 240]; }
      let n = 0, r = 0, gg = 0, b = 0;
      for (const p of px) if (p[0] > maxd * 0.88) { n++; r += p[1]; gg += p[2]; b += p[3]; }
      return [Math.round(r / n), Math.round(gg / n), Math.round(b / n)];
    }
    // שיעור הפיקסלים ה"דיו" בתוך שורות הטקסט; אותיות מודגשות עבות יותר ולכן צפופות יותר
    const BOLD_INK = 0.26; // נמדד: כותרת מודגשת 0.35, פסקה רגילה 0.18
    function inkDensity(img, lines, bg, fg) {
      const { width: W, height: H, data } = img;
      const span = Math.abs(fg[0] - bg[0]) + Math.abs(fg[1] - bg[1]) + Math.abs(fg[2] - bg[2]);
      if (span < 90) return 0;
      let ink = 0, all = 0;
      for (const l of lines) {
        for (let y = Math.max(0, Math.floor(l.y0)); y < Math.min(H, Math.ceil(l.y1)); y++) {
          for (let x = Math.max(0, Math.floor(l.x0)); x < Math.min(W, Math.ceil(l.x1)); x++) {
            const i = (y * W + x) * 4;
            const d = Math.abs(data[i] - bg[0]) + Math.abs(data[i + 1] - bg[1]) + Math.abs(data[i + 2] - bg[2]);
            all++; if (d > span * 0.5) ink++;
          }
        }
      }
      const r = all ? ink / all : 0;
      return r;
    }
    const median = (a) => { const s = [...a].sort((x, y) => x - y); return s[s.length >> 1] || 12; };

    // טסראקט לפעמים מאחד כותרת וגוף טקסט: מפצלים לפי שינוי בגובה השורה או פער אנכי גדול
    function splitParas(paras) {
      const out = [];
      for (const p of paras) {
        let group = [p.lines[0]];
        const flush = () => {
          const ls = group;
          out.push({ text: ls.map(l => l.text).join(' '), conf: p.conf,
            x0: Math.min(...ls.map(l => l.x0)), y0: ls[0].y0, x1: Math.max(...ls.map(l => l.x1)), y1: ls[ls.length - 1].y1, lines: ls });
        };
        for (let i = 1; i < p.lines.length; i++) {
          const a = group[group.length - 1], b = p.lines[i];
          const ha = a.y1 - a.y0, hb = b.y1 - b.y0;
          const ratio = Math.max(ha, hb) / Math.max(1, Math.min(ha, hb));
          const gap = b.y0 - a.y1;
          if (ratio > 1.45 || gap > Math.max(ha, hb)) { flush(); group = [b]; } else group.push(b);
        }
        flush();
      }
      return out;
    }

    function draw(paras, trs, img) {
      const c = el.cv;
      c.width = img.width; c.height = img.height;
      const ctx = c.getContext('2d');
      ctx.clearRect(0, 0, c.width, c.height);
      const rtl = RTL_LANGS.includes(S.target);
      paras.forEach((p, i) => {
        const tr = trs[i];
        if (!tr) return;
        const pad = 2;
        const x0 = Math.max(0, Math.floor(p.x0) - pad), y0 = Math.max(0, Math.floor(p.y0) - pad);
        const x1 = Math.min(c.width, Math.ceil(p.x1) + pad), y1 = Math.min(c.height, Math.ceil(p.y1) + pad);
        const bg = sampleBg(img, x0, y0, x1, y1);
        const fg = sampleFg(img, x0, y0, x1, y1, bg);
        ctx.fillStyle = `rgb(${bg})`; ctx.fillRect(x0, y0, x1 - x0, y1 - y0);
        const W = x1 - x0 - 2, H = y1 - y0;
        // גודל האות: בשורה בודדת גובה התיבה תלוי באותיות עם זנב/גג, ובפסקה בולטת המרחק בין השורות
        const hs = p.lines.map(l => l.y1 - l.y0);
        let fs;
        if (p.lines.length >= 2) {
          const pitch = median(p.lines.slice(1).map((l, k) => l.y0 - p.lines[k].y0).filter(d => d > 0));
          fs = Math.max(9, Math.min(pitch / 1.25, Math.max(...hs) * 1.1));
        } else fs = Math.max(9, hs[0] / 0.85);
        const bold = inkDensity(img, p.lines, bg, fg) > BOLD_INK;
        const wt = bold ? '700 ' : '';
        const wrap = (size) => {
          ctx.font = `${wt}${size}px "Segoe UI", Arial, sans-serif`;
          const words = tr.split(/\s+/); const out = []; let cur = '';
          for (const w of words) {
            const t = cur ? cur + ' ' + w : w;
            if (ctx.measureText(t).width > W && cur) { out.push(cur); cur = w; } else cur = t;
          }
          if (cur) out.push(cur);
          return out;
        };
        let lines = wrap(fs);
        while (lines.length * fs * 1.2 > H * 1.15 && fs > 7) { fs *= 0.92; lines = wrap(fs); }
        // יישור לפי המקור: שורות ממורכזות נשארות ממורכזות, אחרת לפי כיוון השפה
        // (שורה בודדת תמיד "ממורכזת" ביחס לעצמה, ולכן שם אי אפשר לדעת)
        const centered = p.lines.length > 1 && p.lines.every(l => Math.abs((l.x0 + l.x1) / 2 - (x0 + x1) / 2) < (x1 - x0) * 0.03) && p.lines.some(l => Math.abs(l.x0 - p.lines[0].x0) > 4);
        ctx.fillStyle = `rgb(${fg})`;
        ctx.textBaseline = 'top';
        ctx.direction = rtl ? 'rtl' : 'ltr';
        ctx.textAlign = centered ? 'center' : (rtl ? 'right' : 'left');
        const total = lines.length * fs * 1.2;
        let y = y0 + Math.max(0, (H - total) / 2);
        const x = centered ? (x0 + x1) / 2 : (rtl ? x1 - 1 : x0 + 1);
        for (const ln of lines) { ctx.fillText(ln, x, y); y += fs * 1.2; }
      });
    }

    // --- כפתורים ---
    root.getElementById('refresh').onclick = () => u.run();
    el.pause.onclick = () => {
      u.paused = !u.paused;
      el.pause.textContent = u.paused ? 'המשך' : 'השהה';
      u.runId++;
      if (u.paused) { clearCanvas(); u.setStatus('מושהה', 'idle'); } else u.run();
    };
    root.getElementById('opts').onclick = () => send({ type: 'options' });
    root.getElementById('close').onclick = () => u.hide();
    el.full.onclick = async () => {
      u.fullPage = !u.fullPage;
      el.full.textContent = u.fullPage ? 'חזרה לריבוע' : 'מסך מלא';
      el.box.classList.toggle('fp', u.fullPage); // בתרגום כל הדף המסגרת מקיפה את כל הדף
      u.runId++;
      clearTimeout(u.timers.run);
      if (u.fullPage) {
        clearCanvas();
        el.box.style.visibility = 'visible';
        u.setStatus('מתרגם את הדף…', 'work');
        await send({ type: 'fullpage', on: true });
      } else {
        await send({ type: 'fullpage', on: false });
        fpStop();
        u.setStatus('תרגום מסך', 'idle');
        u.run();
      }
    };
    el.dl.onclick = async () => {
      const info = u.dlInfo;
      if (!info) return;
      el.dl.disabled = true;
      try {
        u.setStatus('מוריד מודל… 0%', 'work', { download: info });
        await downloadModel(info.src, info.tgt, (p) => u.setStatus(`מוריד מודל… ${Math.round(p * 100)}%`, 'work', { download: info }));
        u.setStatus('המודל הורד', 'idle');
        if (u.fullPage) { fpStop(); await fpStart(); } else u.run();
      } catch (e) {
        u.setStatus('ההורדה נכשלה: ' + (e.message || ''), 'error', { download: info });
      } finally { el.dl.disabled = false; }
    };

    // --- הצגה והסתרה ---
    u.show = async () => {
      u.visible = true;
      host.style.display = '';
      u.setStatus('תרגום מסך', 'idle');
      u.scheduleRun(300);
    };
    u.hide = () => {
      u.visible = false; u.runId++;
      clearTimeout(u.timers.run);
      host.style.display = 'none';
      if (u.fullPage) { u.fullPage = false; el.full.textContent = 'מסך מלא'; el.box.classList.remove('fp'); send({ type: 'fullpage', on: false }); fpStop(); }
      clearCanvas();
      send({ type: 'badge', state: '' });
    };

    // --- שינוי בדף מתחת לריבוע / גלילה / גודל חלון ---
    addEventListener('scroll', () => { if (u.visible && !u.paused && !u.fullPage) { u.runId++; u.scheduleRun(900); } }, { passive: true, capture: true });
    addEventListener('resize', () => { applyGeo(); u.scheduleRun(800); });
    new MutationObserver((list) => {
      if (!u.visible || u.paused || u.fullPage || !u.shown) return;
      if (list.every(m => m.target === host || host.contains(m.target))) return;
      u.scheduleRun(1800);
    }).observe(document.documentElement, { childList: true, subtree: true, characterData: true, attributes: false });

    // --- טעינת מיקום שמור ---
    u.init = async () => {
      try { const { box } = await chrome.storage.local.get('box'); if (box && box.w) Object.assign(u.geo, box); } catch (e) { /* ignore */ }
      u.geo.x = Math.min(u.geo.x, Math.max(0, innerWidth - 200));
      applyGeo();
    };
    return u;
  }

  async function toggleUI() {
    if (!IS_TOP) return;
    if (!ui) { ui = createUI(); await ui.init(); await ui.show(); return; }
    if (ui.visible) ui.hide(); else ui.show();
  }

  g.__stHe = { toggleUI };
  if (IS_TOP && !quiet) toggleUI();
})();
