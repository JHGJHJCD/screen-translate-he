const puppeteer = require('puppeteer-core');
const path = require('path');
(async () => {
  const ext = path.join(__dirname, 'ext-test');
  const browser = await puppeteer.launch({
    executablePath: 'C:/Program Files/Google/Chrome/Application/chrome.exe',
    headless: true, pipe: true, enableExtensions: [ext],
    userDataDir: path.join(__dirname, 'profile'),
    args: ['--mute-audio', '--no-first-run']
  });
  const sw = await browser.waitForTarget(t => t.type() === 'service_worker' && t.url().endsWith('/background.js'), { timeout: 20000 });
  const id = new URL(sw.url()).host;
  console.log('ext id', id);
  const page = await browser.newPage();
  page.on('console', m => console.log('[page]', m.text()));
  page.on('pageerror', e => console.log('[pageerror]', e.message));
  await page.goto(`chrome-extension://${id}/options.html`);
  await new Promise(r => setTimeout(r, 1500));
  console.log('state:', await page.$eval('#state', e => e.textContent));
  if (await page.$eval('#download', e => !e.hidden)) {
    await page.click('#download');
    const t0 = Date.now();
    while (Date.now() - t0 < 420000) {
      await new Promise(r => setTimeout(r, 10000));
      const s = await page.$eval('#state', e => e.textContent);
      console.log(Math.round((Date.now() - t0) / 1000) + 's', s);
      if (s.includes('מוכן')) break;
    }
  }
  await page.click('#test');
  await new Promise(r => setTimeout(r, 3000));
  console.log('test out:', await page.$eval('#out', e => e.textContent));
  await browser.close();
})().catch(e => { console.log('FAIL', e.message); process.exit(1); });
