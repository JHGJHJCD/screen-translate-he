const puppeteer = require('puppeteer-core');
const path = require('path'), os = require('os'), fs = require('fs');
const sleep = ms => new Promise(r => setTimeout(r, ms));
(async () => {
  const browser = await puppeteer.launch({ executablePath: 'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe', headless: true, pipe: true, enableExtensions: [path.join(__dirname, 'ext-test')], userDataDir: fs.mkdtempSync(path.join(os.tmpdir(), 'edge-')), args: ['--mute-audio', '--no-first-run'] });
  const swT = await browser.waitForTarget(t => t.type() === 'service_worker' && t.url().endsWith('/background.js'), { timeout: 20000 });
  const id = new URL(swT.url()).host;
  console.log('Edge: extension loaded', id);
  const page = await browser.newPage();
  await page.goto(`chrome-extension://${id}/options.html`); await sleep(2000);
  console.log('Edge options state:', await page.$eval('#state', e => e.textContent));
  await browser.close(); process.exit(0);
})().catch(e => { console.log('FAIL', e.message.slice(0, 300)); process.exit(1); });
