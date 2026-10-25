const L=require('./lib.js');
(async()=>{
 const b=await L.chromium.launch(); const h=await L.mk(b,'light'); const p=h.p;
 const uid=await L.guest(h); await L.onboard(uid,'Дубль',['Исследования','Инновации/новизна','Красота/эстетика','Смысл','Свобода']);
 await h.go('/digest?day=week&seg=leisure'); const title=async()=>p.$eval('.deck h2, article h2',e=>e.innerText).catch(()=>'?');
 const t1=await title(); console.log('1-я карточка недели',t1);
 await h.tap('button:has-text("Иду")'); await h.tap('dialog[open] button:has-text("Дальше")');
 await h.go('/digest?day=week&seg=leisure'); console.log('после Иду, неделя, 1-я карточка:',await title());
 await h.go('/digest?day=today&seg=leisure'); console.log('сегодня, 1-я:',await title());
 const f=(await L.api(`/api/feed?user_id=${uid}&date=week&segment=leisure`)).body; console.log('API week items с decision:',f.items.filter(i=>i.decision).map(i=>i.event.title.slice(0,30)+' '+JSON.stringify(i.decision)), 'slug first',f.items[0].event.title.slice(0,30));
 const pl=(await L.api(`/api/plan/${uid}`)).body; console.log('plan days nonempty',Object.entries(pl.days).filter(([k,v])=>v.length).map(([k,v])=>k+':'+v.length));
 await L.api(`/api/profile/${uid}`,{method:'DELETE'}); await b.close();
})();
