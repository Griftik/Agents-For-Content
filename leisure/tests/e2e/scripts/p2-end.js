const L=require('./lib.js'); const scheme=process.argv[2]||'light';
(async()=>{
 const b=await L.chromium.launch(); const h=await L.mk(b,scheme); const p=h.p;
 const uid=await L.guest(h); await L.onboard(uid,'Аня',['Исследования','Инновации/новизна','Красота/эстетика','Смысл','Свобода']);
 const f=(await L.api(`/api/feed?user_id=${uid}&date=today&segment=leisure&limit=20`)).body; console.log('API total',f.total,'next_offset',f.next_offset,'items',f.items.length);
 await h.go('/digest'); let n=0; for(;n<60;n++){ const bt=p.locator('.actionbar button:has-text("Не моё")').first(); if(!(await bt.count())) break; await bt.tap(); await p.waitForTimeout(250); }
 console.log('пролистано карточек',n); console.log('конец ленты:',(await h.text()).replace(/\n/g,' | ').slice(-200)); await h.shot('p2-s3-feed-end');
 await h.go('/digest'); console.log('после перезагрузки:',(await h.text()).match(/\d+ \/ \d+/)?.[0], (await h.text()).replace(/\n/g,' | ').slice(-160));
 const f2=(await L.api(`/api/feed?user_id=${uid}&date=today&segment=leisure&limit=20`)).body; console.log('API после 20 «не моё»: total',f2.total,'items',f2.items.length);
 await L.api(`/api/profile/${uid}`,{method:'DELETE'}); await b.close();
})();
