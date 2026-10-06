const puppeteer = require('puppeteer-core');
const http = require('http'), fs = require('fs'), path = require('path');
const sleep = ms => new Promise(r => setTimeout(r, ms));
(async () => {
  const srv = http.createServer((q, s) => { s.setHeader('content-type', 'text/html; charset=utf-8'); s.end(fs.readFileSync(path.join(__dirname, 'site', 'test.html'))); }).listen(8777, '127.0.0.1');
  const browser = await puppeteer.launch({
    executablePath: 'C:/Program Files/Google/Chrome/Application/chrome.exe',
    headless: true, pipe: true, enableExtensions: [path.join(__dirname, 'ext-test')],
    userDataDir: path.join(__dirname, 'profile'), defaultViewport: { width: 1200, height: 700 },
    args: ['--mute-audio', '--no-first-run']
  });
  const swT = await browser.waitForTarget(t => t.type() === 'service_worker' && t.url().endsWith('/background.js'), { timeout: 20000 });
  const sw = await swT.worker();
  const page = await browser.newPage();
  page.on('console', m => { const t = m.text(); if (!t.includes('Built-In AI')) console.log('[page]', t); });
  page.on('pageerror', e => console.log('[pageerror]', e.message));
  await page.goto('http://127.0.0.1:8777/test.html');
  await sleep(2500);
  const st = () => page.evaluate(() => { const h = document.getElementById('st-he-host'); return h ? h.shadowRoot.getElementById('st').textContent : '(אין ריבוע)'; });
  // "לחיצה על הסמל"
  console.log('activate:', await sw.evaluate(async () => { const [tab] = await chrome.tabs.query({ url: 'http://127.0.0.1/*' }); await activate(tab); return 'sent'; }));
  for (let i = 0; i < 30; i++) { await sleep(1500); const s = await st(); console.log('box:', s); if (s.startsWith('מוצג') || s.includes('נכשל') || s.includes('לא ')) break; }
  await page.screenshot({ path: 'shot-box.png' });
  // תרגום כל הדף
  await page.evaluate(() => document.getElementById('st-he-host').shadowRoot.getElementById('full').click());
  await sleep(6000);
  console.log('after full:', await st());
  const txt = await page.evaluate(() => document.getElementById('rest').innerText);
  console.log('REST TEXT:\n' + txt);
  await page.screenshot({ path: 'shot-full.png' });
  // כיבוי = חזרה למקור
  await page.evaluate(() => document.getElementById('st-he-host').shadowRoot.getElementById('full').click());
  await sleep(1500);
  console.log('restored h2:', await page.$eval('#rest h2', e => e.textContent));
  await browser.close(); srv.close();
})().catch(e => { console.log('FAIL', e.message); process.exit(1); });
