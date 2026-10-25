const L=require('./lib.js');
(async()=>{
 const b=await L.chromium.launch(); const h=await L.mk(b,'light'); const p=h.p;
 const uid=await L.guest(h); await L.onboard(uid,'Аня',['Исследования','Инновации/новизна','Красота/эстетика','Смысл','Свобода']);
 const F=async()=>(await L.api(`/api/feed?user_id=${uid}&date=today&segment=leisure&limit=100`)).body;
 const f0=await F(); console.log('total limit100',f0.total,f0.items.length);
 await h.go('/digest'); const seen=[]; let n=0;
 for(;n<60;n++){ const t=await h.text(); const c=t.match(/(\d+) \/ (\d+)/); const ti=await p.evaluate(()=>[...document.querySelectorAll('.deck h2')].map(e=>e.innerText).filter(Boolean)[0]||''); seen.push((c?c[0]:'-')+' '+ti.slice(0,20)); const bt=p.locator('.actionbar button:has-text("Не моё")').first(); if(!(await bt.count())) break; await bt.tap(); await p.waitForTimeout(700); }
 console.log('шагов',n,'карточки:',seen.join(' ; '));
 const d=(await L.api(`/api/decisions/${uid}`)).body; console.log('решений записано',d.length);
 await L.api(`/api/profile/${uid}`,{method:'DELETE'}); await b.close();
})();
