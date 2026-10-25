// Колода пропускает карточки? Сравниваем показанные и оставшиеся после перезагрузки
const L=require('./lib.js'); const scheme=process.argv[2]||'light';
(async()=>{
 const b=await L.chromium.launch(); const h=await L.mk(b,scheme); const p=h.p;
 const uid=await L.guest(h); await L.onboard(uid,'Аня',['Исследования','Инновации/новизна','Красота/эстетика','Смысл','Свобода']);
 await h.go('/digest'); const title=()=>p.evaluate(()=>{const a=[...document.querySelectorAll('.deck .fc-title, .deck h2')].map(e=>e.innerText).filter(x=>x&&x!=='В плане'); return a[0]||'';});
 const seen=[]; const log=[];
 for(let n=0;n<60;n++){ const bt=p.locator('.actionbar button:has-text("Не моё")').first(); if(!(await bt.count())) break; const t=await title(); const c=(await h.text()).match(/\d+ \/ \d+/)?.[0]; seen.push(t); log.push(c); await bt.tap(); await p.waitForTimeout(900); }
 console.log('показано',seen.length,'счётчики',log.join(' '));
 console.log('конец:', /На сегодня всё/.test(await h.text()));
 await h.shot('p2-s3-skip-end');
 const d=(await L.api(`/api/decisions/${uid}`)).body; console.log('решений',d.length);
 await h.go('/digest'); const after=[]; for(let n=0;n<60;n++){ const bt=p.locator('.actionbar button:has-text("Не моё")').first(); if(!(await bt.count())) break; after.push(await title()); await bt.tap(); await p.waitForTimeout(900); }
 const uniqNew=after.filter(t=>!seen.includes(t)); console.log('после перезагрузки карточек',after.length,'из них ни разу не показанных',uniqNew.length, uniqNew.slice(0,5));
 await L.api(`/api/profile/${uid}`,{method:'DELETE'}); await b.close();
})();
