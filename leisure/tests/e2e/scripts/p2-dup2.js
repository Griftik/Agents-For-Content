const L=require('./lib.js');
const scheme=process.argv[2];
(async()=>{
 const b=await L.chromium.launch(); const h=await L.mk(b,scheme); const p=h.p;
 const uid=await L.guest(h); await L.onboard(uid,'Дубль',['Исследования','Инновации/новизна','Красота/эстетика','Смысл','Свобода']);
 await h.go('/digest?day=today&seg=leisure'); const first=(await h.text()).split('\n').filter(x=>x.trim()).slice(13,18).join(' | ');
 await h.tap('button:has-text("Иду")'); await h.tap('dialog[open] button:has-text("Дальше")');
 // листаем «Не моё» до конца, чтобы перезагрузить
 await h.go('/digest?day=today&seg=leisure'); const tx=await h.text(); console.log(scheme,'после Иду, сегодня:', (tx.match(/\d+ \/ \d+/)||[])[0], tx.split('\n').filter(x=>x.trim()).slice(11,20).join(' | '));
 await h.shot('p2-dup-card');
 // найдём карточку Фауста в ленте
 for(let i=0;i<25;i++){ const t=await h.text(); if(/Фауст/.test(t)){ console.log('Фауст снова в ленте на карточке',i+1,'; метка «в плане»?',/В плане|ты идёшь|Ты идёшь/.test(t)); await h.shot('p2-dup-faust'); break;} const bt=p.locator('button:has-text("Не моё")').first(); if(!(await bt.count())) break; await bt.tap(); await p.waitForTimeout(400); }
 await L.api(`/api/profile/${uid}`,{method:'DELETE'}); await b.close();
})();
