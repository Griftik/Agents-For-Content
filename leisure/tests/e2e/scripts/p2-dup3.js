const L=require('./lib.js');
(async()=>{
 const b=await L.chromium.launch(); const h=await L.mk(b,'light'); const p=h.p;
 const uid=await L.guest(h); await L.onboard(uid,'Дубль',['Исследования','Инновации/новизна','Красота/эстетика','Смысл','Свобода']);
 await h.go('/digest?day=week&seg=all');
 const cur=async()=>{const t=await p.evaluate(()=>{const c=document.querySelector('.deck-stage article, .deck-stage > *:last-child'); return document.body.innerText.match(/\d+ \/ \d+/)?.[0]+' '+[...document.querySelectorAll('.deck h2')].map(e=>e.innerText.slice(0,28)).join(' || ');}); return t;};
 for(let i=0;i<3;i++){ console.log('карточка',await cur()); await h.tap('button:has-text("Иду")'); console.log('  лист:',await p.$eval('dialog[open] p',e=>e.innerText.slice(0,40)).catch(()=>'нет')); await h.tap('dialog[open] button:has-text("Дальше")'); }
 console.log('plan',JSON.stringify((await L.api(`/api/plan/${uid}`)).body.days).slice(0,300));
 console.log('decisions',(await L.api(`/api/decisions/${uid}`)).body.map(d=>d.event_slug.slice(0,25)+' '+d.status));
 await L.api(`/api/profile/${uid}`,{method:'DELETE'}); await b.close();
})();
