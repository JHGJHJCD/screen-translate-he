#!/bin/bash
# עותק בדיקה של התוסף עם הרשאת <all_urls> (מדמה את "activeTab" שמתקבל בלחיצה אמיתית על הסמל)
cd "$(dirname "$0")"
rm -rf ext-test && cp -r ../../extension ext-test
node -e "const fs=require('fs');const m=JSON.parse(fs.readFileSync('ext-test/manifest.json','utf8'));m.host_permissions.push('<all_urls>');fs.writeFileSync('ext-test/manifest.json',JSON.stringify(m,null,1));console.log('prep ok')"
