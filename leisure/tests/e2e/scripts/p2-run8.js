// Прогон 2, сценарий 8: профиль — «Что я о тебе узнал», «Удалить мои данные»; тексты экранов
const L=require('./lib.js'); const fs=require('fs');
const scheme=process.argv[2]||'light';
(async()=>{
 const b=await L.chromium.launch(); const h=await L.mk(b,scheme); const p=h.p;
 const uid=await L.guest(h); await L.onboard(uid,'Аня',['Исследования','Инновации/новизна','Красота/эстетика','Смысл','Свобода']);
 const f=(await L.api(`/api/feed?user_id=${uid}&date=today&segment=all&limit=100`)).body;
 // 6 «иду»/«не моё» для обучения
 for(const [i,it] of f.items.slice(0,8).entries()) await L.api('/api/decisions',{method:'POST',body:JSON.stringify({user_id:uid,event:it.event.slug,status:i%2?'не моё':'иду',day:it.day})});
 await h.go('/profile'); await h.shot('p2-s8-profile'); const tx=await h.text(); console.log('ПРОФИЛЬ:',tx.replace(/\n/g,' | ').slice(0,1500));
 console.log('hscroll',JSON.stringify(await h.hscroll()),await h.clip());
 const chips=await p.$$eval('.learned button',e=>e.map(x=>x.innerText)); console.log('«Что я о тебе узнал» чипов:',chips.length,chips.slice(0,8));
 if(chips.length){ const before=await p.$$eval('.learned button',e=>e.map(x=>x.innerText)); await h.tap('.learned button'); await h.shot('p2-s8-learned-sheet'); console.log('лист:',(await p.$eval('dialog[open]',e=>e.innerText)).replace(/\n/g,' | '));
   await h.tap('dialog[open] button:has-text("Больше")'); await p.waitForTimeout(900); await h.go('/profile'); const after=await p.$$eval('.learned button',e=>e.map(x=>x.innerText)); console.log('после «Больше»:',after.slice(0,4),'до:',before.slice(0,4));
   await h.tap('.learned button'); await h.tap('dialog[open] button:has-text("Сбросить")'); await p.waitForTimeout(900); await h.go('/profile'); console.log('после «Сбросить» чипов:',(await p.$$eval('.learned button',e=>e.length))); }
 // тексты по экранам: ищем объяснительное
 const screens={}; for(const u of ['/digest','/plan','/profile']){ await h.go(u); screens[u]=(await h.text()).replace(/\n/g,' | ').slice(0,400); }
 // удаление
 await h.go('/profile'); const t=h.log.taps; await h.tap('button:has-text("Удалить мои данные")'); await p.waitForTimeout(500); await h.shot('p2-s8-delete-ask');
 console.log('подтверждение:',(await p.$eval('[role=alertdialog],dialog[open],form:has(#del-q)',e=>e.innerText).catch(()=>'?')).replace(/\n/g,' | '));
 await h.tap('button:has-text("Удалить всё")'); await p.waitForTimeout(2000); console.log('после удаления url',p.url().replace(L.BASE,''),'taps',h.log.taps-t); await h.shot('p2-s8-after-delete');
 console.log((await h.text()).replace(/\n/g,' | ').slice(0,250));
 const chk=await L.api(`/api/profile/${uid}`); console.log('API профиль после удаления:',chk.status);
 await h.go('/digest'); console.log('/digest после удаления →',p.url().replace(L.BASE,''));
 console.log('console',h.log.console,'net',h.log.net.filter(x=>!/ABORTED/.test(x)));
 const uid2=await (async()=>{const c=(await h.ctx.cookies()).find(c=>c.name==='leisure_session'); return c?Number(decodeURIComponent(c.value).split('.')[0]):null;})(); if(uid2&&uid2!==uid) await L.api(`/api/profile/${uid2}`,{method:'DELETE'});
 await b.close();
})();
