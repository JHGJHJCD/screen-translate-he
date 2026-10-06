const puppeteer = require('puppeteer-core');
const http = require('http'), fs = require('fs'), path = require('path');
const sleep = ms => new Promise(r => setTimeout(r, ms));
(async () => {
  const srv = http.createServer((q, s) => { s.setHeader('content-type', 'text/html; charset=utf-8'); s.end(fs.readFileSync(path.join(__dirname, 'site', 'test.html'))); }).listen(8777, '127.0.0.1');
  const browser = await puppeteer.launch({ executablePath: 'C:/Program Files/Google/Chrome/Application/chrome.exe', headless: true, pipe: true, enableExtensions: [path.join(__dirname, 'ext-test')], userDataDir: path.join(__dirname, 'profile'), defaultViewport: { width: 1200, height: 700 }, args: ['--mute-audio', '--no-first-run'] });
  const sw = await (await browser.waitForTarget(t => t.type() === 'service_worker' && t.url().endsWith('/background.js'))).worker();
  const page = await browser.newPage();
  page.on('pageerror', e => console.log('[pageerror]', e.message));
  await page.goto('http://127.0.0.1:8777/test.html'); await sleep(2000);
  const st = () => page.evaluate(() => { const h = document.getElementById('st-he-host'); return h ? (h.style.display === 'none' ? '(מוסתר)' : h.shadowRoot.getElementById('st').textContent) : '(אין ריבוע)'; });
  const click = (id) => page.evaluate((id) => document.getElementById('st-he-host').shadowRoot.getElementById(id).click(), id);
  const act = () => sw.evaluate(async () => { const [tab] = await chrome.tabs.query({ url: 'http://127.0.0.1/*' }); await activate(tab); });
  const waitShown = async (label) => { for (let i = 0; i < 25; i++) { await sleep(1200); const s = await st(); if (s.startsWith('מוצג') || s.includes('נכשל') || s.startsWith('לא ')) { console.log(label, '→', s); return s; } } console.log(label, '→ TIMEOUT', await st()); };
  await act(); await waitShown('first');
  await page.screenshot({ path: 'shot-box2.png' });
  // גרירה: אוחזים בפס ומזיזים 140 פיקסלים ימינה ו-60 למטה
  await page.mouse.move(400, 107); await page.mouse.down(); await page.mouse.move(480, 140, { steps: 5 }); await page.mouse.move(540, 167, { steps: 5 }); await page.mouse.up();
  console.log('after drag (immediately):', await st());
  await waitShown('after drag');
  const geo = await page.evaluate(() => { const b = document.getElementById('st-he-host').shadowRoot.getElementById('box'); return b.style.left + ',' + b.style.top; });
  console.log('box position:', geo);
  await page.screenshot({ path: 'shot-box3.png' });
  // השהיה
  await click('pause'); await sleep(500); console.log('paused:', await st());
  await click('pause'); await waitShown('resumed');
  // הסתרה / הצגה בקיצור (הזרקה חוזרת = החלפה)
  await act(); await sleep(500); console.log('toggle 1:', await st());
  await act(); await sleep(800); console.log('toggle 2:', await st());
  const saved = await sw.evaluate(async () => JSON.stringify(await chrome.storage.local.get('box')));
  console.log('saved geometry:', saved);
  await browser.close(); srv.close(); process.exit(0);
})().catch(e => { console.log('FAIL', e.message); process.exit(1); });
