# בדיקות התוסף

כרום 154 ואדג' 154 מתעלמים מ-`--load-extension`, לכן הבדיקות טוענות את התוסף דרך puppeteer-core
(`enableExtensions`, צינור פנימי). דרישות: Node, כרום מותקן.

```
cd tests/ext
npm install
./prep.sh            # עותק בדיקה עם הרשאת <all_urls> (במקום activeTab של לחיצה אמיתית)
node model.js        # הורדת מודל עברית ובדיקת תרגום בעמוד ההגדרות (פרופיל קבוע בתיקיית profile)
node page.js         # ריבוע + תרגום כל הדף על דף בדיקה; צילומי מסך shot-*.png
node box.js          # גרירה, השהיה, הצגה/הסתרה
node edge.js         # אדג'
```
`ext-test`, `profile`, `node_modules` ו-`shot-*.png` הם תוצרי בדיקה (לא נשמרים ב-git).
מה שלא נבדק כאן: לחיצה אמיתית על סמל התוסף וקיצור המקלדת (דורשים מחוות משתמש).
