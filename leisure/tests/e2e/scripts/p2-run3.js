// Прогон 2, сценарий 4 + «Отменить», «Убрать»
const L=require('./lib.js'); const fs=require('fs');
const scheme=process.argv[2]||'light';
(async()=>{
 const b=await L.chromium.launch(); const h=await L.mk(b,scheme); const p=h.p;
 const uid=await L.guest(h); await L.onboard(uid,'Аня',['Исследования','Инновации/новизна','Красота/эстетика','Смысл','Свобода']);
 const F=async(d='today',s='leisure',u=uid)=>(await L.api(`/api/feed?user_id=${u}&date=${d}&segment=${s}&limit=100`)).body;
 const f0=await F(); const today=f0.today; const yday=new Date(Date.parse(today)-86400e3).toISOString().slice(0,10);
 const pf=(await L.api(`/api/feed?user_id=${uid}&date=${yday}&today=${yday}&segment=all&limit=100`)).body;
 const cats=[...new Set(pf.items.map(i=>i.event.category))]; console.log('past cats',cats.length);
 const pick=[]; for(const c of cats){ const it=pf.items.find(i=>i.event.category===c); if(it) pick.push(it); if(pick.length==3) break; }
 for(const x of pick) await L.api('/api/decisions',{method:'POST',body:JSON.stringify({user_id:uid,event:x.event.slug,status:'иду',day:yday})});
 console.log('прошлые',pick.map(x=>x.event.category));
 const scores=(f)=>Object.fromEntries(f.items.map(i=>[i.event.slug,[i.score,i.event.category]]));
 const before=scores(await F('week'));
 await h.go('/plan'); await h.shot('p2-s4-plan-before'); const t=h.log.taps;
 const titles=()=>p.$$eval('.pastmark',els=>els.map(e=>{ const card=e.closest('li, article, section>div')||e.parentElement; return (card.innerText||'').split('\n')[0].slice(0,30); }));
 console.log('Прошли до:',await titles(), 'dot?',await p.$$eval('nav a[href="/plan"] *',e=>e.map(x=>x.className).filter(Boolean)));
 const orderBefore=await p.$$eval('.pastmark',els=>els.map(e=>e.closest('li,article')?.querySelector('h3,h2,a,strong')?.innerText?.slice(0,25)||'?'));
 const y0=await p.locator('.pastmark').first().evaluate(e=>Math.round(e.getBoundingClientRect().top+scrollY));
 await h.tap(p.locator('.pastmark').nth(0).locator('button:has-text("Сходил")').first());
 const orderAfter=await p.$$eval('.pastmark',els=>els.map(e=>e.closest('li,article')?.querySelector('h3,h2,a,strong')?.innerText?.slice(0,25)||'?'));
 const stars0=await p.$$eval('.pastmark',els=>els.map(e=>!!e.querySelector('.stars')));
 const y1=await p.locator('.pastmark').first().evaluate(e=>Math.round(e.getBoundingClientRect().top+scrollY));
 console.log('порядок до',orderBefore,'после',orderAfter,'звёзды у',stars0,'y',y0,y1); await h.shot('p2-s4-after-shodil');
 await h.tap(p.locator('.pastmark').nth(0).locator('.stars button:has-text("5 ★")').first());
 await h.shot('p2-s4-rated5');
 await h.tap(p.locator('.pastmark').nth(1).locator('button:has-text("Сходил")').first()); await h.tap(p.locator('.pastmark').nth(1).locator('.stars button:has-text("1 ★")').first());
 await h.tap(p.locator('.pastmark').nth(2).locator('button:has-text("Не сходил")').first());
 const note=await p.$$eval('.pastmark p',e=>e.map(x=>x.innerText));
 console.log('заметки',note, 'taps',h.log.taps-t, 'порядок конец',await p.$$eval('.pastmark',els=>els.map(e=>e.closest('li,article')?.querySelector('h3,h2,a,strong')?.innerText?.slice(0,25)||'?')));
 await h.shot('p2-s4-rated1');
 await h.go('/plan'); const txt=await h.text(); await h.shot('p2-s4-reopen'); console.log('после reload: 5★',/● 5 ★/.test(txt),'1★',/● 1 ★/.test(txt), txt.includes('Не сходил'));
 const after=scores(await F('week')); const diffs=Object.keys(after).filter(k=>before[k]&&before[k][0]!==after[k][0]).map(k=>[after[k][1],before[k][0],after[k][0]]);
 console.log('оценки изменились у',diffs.length,JSON.stringify(diffs.slice(0,6)));
 // будущий план: Иду на сегодня/ завтра -> Убрать
 await h.go('/digest?day=week&seg=all'); const sh=async()=>p.$eval('dialog[open] p',e=>e.innerText.slice(0,40)).catch(()=>'нет');
 const ct=async()=>p.evaluate(()=>[...document.querySelectorAll('.deck h2')].map(e=>e.innerText.slice(0,22)).filter(Boolean).join('|')); console.log('карточка',(await h.text()).match(/\d+ \/ \d+/)?.[0],await ct());
 await h.tap('button:has-text("Иду")'); console.log('лист1',await sh()); await h.tap('dialog[open] button:has-text("Дальше")');
  console.log('карточка',(await h.text()).match(/\d+ \/ \d+/)?.[0],await ct());
 await h.tap('button:has-text("Иду")'); console.log('лист2',await sh(),(await h.text()).match(/\d+ \/ \d+/)?.[0]); await p.waitForTimeout(400);
 const hit=await p.evaluate(()=>{const b=[...document.querySelectorAll('.toast button')][0]; if(!b) return 'нет'; const r=b.getBoundingClientRect(); const e=document.elementFromPoint(r.x+r.width/2,r.y+r.height/2); return 'под листом: '+(e===b?'нет':'да ('+e.tagName+')');}); console.log('Отменить доступна при открытом листе?',hit);
 // Отменить во втором
 console.log('toast:',await p.$eval('.toast',e=>e.innerText).catch(()=>'нет'));
 await h.shot('p2-s8-sheet-undo');
 await h.tap('dialog[open] button:has-text("Дальше")'); console.log('toast после Дальше:',await p.$eval('.toast',e=>e.innerText).catch(()=>'нет')); await h.shot('p2-s8-toast-after-close'); await h.tap('.toast button:has-text("Отменить")'); await p.waitForTimeout(800);
 const dec1=(await L.api(`/api/decisions/${uid}`)).body.filter(d=>d.status==='иду'&&d.day>=today).length;
 console.log('«Отменить» → иду на будущее осталось',dec1,'(ожидается 1); после отмены карточка вернулась:',(await h.text()).match(/\d+ \/ \d+/)?.[0]);
 await h.shot('p2-s8-after-undo');
 await h.go('/plan'); const ptxt=await h.text(); console.log('план:',ptxt.replace(/\n/g,' | ').slice(0,700)); await h.shot('p2-s8-plan');
 const tb=h.log.taps; await h.tap('button:has-text("Убрать")'); await p.waitForTimeout(900);
 const dec2=(await L.api(`/api/decisions/${uid}`)).body.filter(d=>d.status==='иду'&&d.day>=today).length;
 console.log('«Убрать»: иду осталось',dec2,'; hscroll',JSON.stringify(await h.hscroll()),'console',h.log.console,'net',h.log.net.filter(x=>!/ABORTED/.test(x)));
 await h.shot('p2-s8-after-remove');
 fs.writeFileSync((process.env.S||'/tmp')+`/uid3-${scheme}`,String(uid));
 await L.api(`/api/profile/${uid}`,{method:'DELETE'}); await b.close();
})();
