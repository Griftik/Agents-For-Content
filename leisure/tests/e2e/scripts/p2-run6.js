// Прогон 2, сценарий 7: длинные слова, прошедшее, оффлайн, manifest, /api без ключа
const L=require('./lib.js'); const fs=require('fs');
const scheme=process.argv[2]||'light'; const SLUG='qa-long-title-event';
(async()=>{
 const b=await L.chromium.launch(); const h=await L.mk(b,scheme,{permissions:['clipboard-read','clipboard-write']}); const p=h.p;
 const uid=await L.guest(h); await L.onboard(uid,'Аня',['Исследования','Инновации/новизна','Красота/эстетика','Смысл','Свобода']);
 await L.api('/api/decisions',{method:'POST',body:JSON.stringify({user_id:uid,event:SLUG,status:'иду',day:'2026-10-25'})});
 await h.go('/e/'+SLUG); console.log('страница события hscroll',JSON.stringify(await h.hscroll()),await h.clip()); await h.shot('p2-s7-long-event');
 await h.go('/plan'); console.log('план hscroll',JSON.stringify(await h.hscroll()),await h.clip()); await h.shot('p2-s7-long-plan');
 // лента: найти карточку
 await h.go('/digest?day=today&seg=all'); let found=false;
 for(let i=0;i<46;i++){ const t=await h.text(); if(/Сверхдлинное/.test(t)){ found=true; console.log('карточка в ленте №',i+1,'hscroll',JSON.stringify(await h.hscroll()),await h.clip()); await h.shot('p2-s7-long-card'); break;} const bt=p.locator('button:has-text("Не моё")').first(); if(!(await bt.count())) break; await bt.tap(); await p.waitForTimeout(350); }
 console.log('карточка найдена',found);
 // шеринг события с длинным названием
 await L.api('/api/decisions',{method:'POST',body:JSON.stringify({user_id:uid,event:SLUG,status:'иду',day:'2026-10-25'})});
 await h.go('/plan'); const inv=p.locator('button:has-text("Позвать друга")').first(); if(await inv.count()){ await h.tap(inv); await p.waitForTimeout(700); await h.shot('p2-s7-long-invite'); console.log('hscroll при листе',JSON.stringify(await h.hscroll()),await h.clip()); console.log((await p.$eval('dialog[open]',e=>e.innerText).catch(()=>'')).replace(/\n/g,' | ').slice(0,500)); }
 // прошедшее: приглашение на вчера
 const pastInv=await L.api('/api/invites',{method:'POST',body:JSON.stringify({user_id:uid,event:'vakhtangov-faust-timoshenko',day:'2026-10-25'})});
 console.log('console',h.log.console,'net',h.log.net.filter(x=>!/ABORTED/.test(x)));
 await L.api(`/api/profile/${uid}`,{method:'DELETE'});
 await b.close();
})();
