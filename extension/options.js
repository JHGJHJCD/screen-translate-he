const DEFAULTS = { source: 'auto', target: 'he', ocrLangs: 'eng', fallback: 'safe', geminiKey: '' };
const $ = (id) => document.getElementById(id);
const fields = ['source', 'target', 'ocrLangs', 'fallback', 'geminiKey'];

async function load() {
  const v = await chrome.storage.local.get(DEFAULTS);
  fields.forEach(f => { $(f).value = v[f]; });
}
let savedTimer = 0;
async function save() {
  const v = {};
  fields.forEach(f => { v[f] = $(f).value.trim(); });
  await chrome.storage.local.set(v);
  $('saved').style.opacity = 1;
  clearTimeout(savedTimer);
  savedTimer = setTimeout(() => { $('saved').style.opacity = 0; }, 1200);
  refreshState();
}
fields.forEach(f => $(f).addEventListener('change', save));

// כרטיס הצמד: מקור "זיהוי אוטומטי" נבדק מול אנגלית
function pair() {
  const s = $('source').value;
  return { src: s === 'auto' ? 'en' : s, tgt: $('target').value };
}
async function refreshState() {
  const { src, tgt } = pair();
  const st = $('state');
  if (!('Translator' in self)) {
    st.textContent = 'הדפדפן הזה בלי מתרגם מובנה (צריך כרום 138 ומעלה / אדג\' 148 ומעלה)';
    st.className = 'bad'; $('download').hidden = true; return;
  }
  let a;
  try { a = await Translator.availability({ sourceLanguage: src, targetLanguage: tgt }); } catch (e) { a = 'unavailable'; }
  const map = {
    available: ['המנוע המקומי מוכן ' + `(${src} ← ${tgt})`, 'ok'],
    downloadable: ['המודל עוד לא הורד', 'bad'],
    downloading: ['המודל בהורדה…', 'bad'],
    unavailable: ['צמד השפות הזה לא נתמך בדפדפן', 'bad']
  };
  const [text, cls] = map[a] || [a, 'bad'];
  st.textContent = text; st.className = cls;
  $('download').hidden = !(a === 'downloadable' || a === 'downloading');
}

$('download').onclick = async () => {
  const { src, tgt } = pair();
  const btn = $('download');
  btn.disabled = true;
  $('bar').style.display = 'block';
  try {
    const monitor = (m) => m.addEventListener('downloadprogress', (e) => {
      $('fill').style.width = Math.round(e.loaded * 100) + '%';
      $('state').textContent = `מוריד מודל… ${Math.round(e.loaded * 100)}%`;
    });
    await Translator.create({ sourceLanguage: src, targetLanguage: tgt, monitor });
    if ('LanguageDetector' in self && (await LanguageDetector.availability()) !== 'available') {
      $('state').textContent = 'מוריד מודל לזיהוי שפה…';
      await LanguageDetector.create();
    }
  } catch (e) {
    $('state').textContent = 'ההורדה נכשלה: ' + (e.message || e.name);
    $('state').className = 'bad';
  } finally {
    btn.disabled = false;
    $('bar').style.display = 'none';
    refreshState();
  }
};

$('test').onclick = async () => {
  const { src, tgt } = pair();
  $('out').textContent = 'מתרגם…';
  try {
    const t = await Translator.create({ sourceLanguage: src, targetLanguage: tgt });
    $('out').textContent = await t.translate($('testin').value);
  } catch (e) {
    $('out').textContent = 'לא הצליח: ' + (e.message || e.name);
  }
};

load().then(refreshState);
