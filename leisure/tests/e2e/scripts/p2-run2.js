// Прогон 2, сценарии 2-3: вечер, дни, направления, «Неделя»
const L=require('./lib.js'); const fs=require('fs');
const scheme=process.argv[2]||'light';
(async()=>{
 const b=await L.chromium.launch(); const h=await L.mk(b,scheme); const p=h.p;
 const uid=await L.guest(h); await L.onboard(uid,'Аня',['Исследования','Инновации/новизна','Красота/эстетика','Смысл','Свобода']);
 fs.writeFileSync(process.env.S+`/uid2-${scheme}`,String(uid));
 await h.go('/digest'); let t=h.log.taps;
 const badge=/УСПЕВАЕШЬ/i.test(await h.text());
 await h.tap('button:has-text("Иду")'); await p.waitForTimeout(600);
 const link=await p.$eval('dialog[open] a:has-text("К билетам")',a=>a.href).catch(()=>null);
 console.log('S2 badge',badge,'link',link,'taps',h.log.taps-t); await h.shot('p2-s2-sheet');
 console.log('sheet:',(await p.$eval('dialog[open]',e=>e.innerText).catch(()=>'')).replace(/\n/g,' | '));
 await h.tap('dialog[open] button:has-text("Дальше")');
 // S3
 const sig=async()=>{ const tx=await h.text(); const c=tx.match(/(\d+) \/ (\d+)/); const hd=await p.$eval('h1',e=>e.innerText).catch(()=>''); const day=(tx.match(/(СЕГОДНЯ|ЗАВТРА|ПОСЛЕЗАВТРА)? ?·? ?(ПН|ВТ|СР|ЧТ|ПТ|СБ|ВС) \d+ [А-Я]+/)||[''])[0]; return `h1="${hd}" ${c?c[0]:'нет карточек'} day="${day}"`; };
 await h.go('/digest'); t=h.log.taps;
 for(const [lab] of [['Завтра'],['Послезавтра'],['Неделя']]){ await h.tap(`a.chip.day:has-text("${lab}")`); console.log(lab,p.url().split('?')[1],await sig()); await h.shot('p2-s3-'+lab); 
   const sel=await p.$eval('a.chip.day[aria-current], a.chip.day.on, a.chip.day[aria-selected=true]',e=>{const r=e.getBoundingClientRect(); return e.innerText+' '+Math.round(r.left)+'-'+Math.round(r.right)}).catch(()=>'sel?'); console.log('  выбранный чип:',sel); }
 // неделя: пролистать карточки, собрать дни
 const days=[]; 
 for(let i=0;i<20;i++){ const tx=await h.text(); const m=tx.match(/(ПН|ВТ|СР|ЧТ|ПТ|СБ|ВС) \d+ [А-Я]+/); const c=tx.match(/(\d+) \/ (\d+)/); days.push((m?m[0]:'?')+'#'+(c?c[1]+'/'+c[2]:'')); if(i==0||i==6||i==12) await h.shot('p2-s3-week-card'+i); const btn=p.locator('button:has-text("Не моё")').first(); if(!(await btn.count())) break; await btn.tap(); await p.waitForTimeout(500); }
 console.log('неделя, карточки:',days.join(', '));
 console.log('week html chip classes', await p.$$eval('a.chip.day',e=>e.map(x=>x.className+'|'+x.getAttribute('aria-current')+'|'+x.innerText)));
 // Дело
 await h.go('/digest?day=week&seg=leisure'); await h.tap('.segment a:has-text("Дело")'); console.log('Дело/неделя',p.url().split('?')[1],await sig()); await h.shot('p2-s3-week-business');
 const bd=[]; for(let i=0;i<14;i++){ const tx=await h.text(); const m=tx.match(/(ПН|ВТ|СР|ЧТ|ПТ|СБ|ВС) \d+ [А-Я]+/); const title=await p.$eval('article h2, .card h2, h2',e=>e.innerText).catch(()=>''); bd.push((m?m[0]:'?')+' '+title.slice(0,40)); const btn=p.locator('button:has-text("Не моё")').first(); if(!(await btn.count())) break; await btn.tap(); await p.waitForTimeout(450); }
 console.log('Дело:',bd.join('\n   ')); await h.shot('p2-s3-business-end');
 await h.go('/digest?day=today&seg=business'); console.log('Дело/сегодня',await sig(), (await h.text()).replace(/\n/g,' | ').slice(-200)); await h.shot('p2-s3-today-business');
 await h.go('/digest?day=tomorrow&seg=business'); console.log('Дело/завтра',await sig()); 
 await h.go('/digest?day=week&seg=all'); console.log('Всё/неделя',await sig());
 // календарь
 const dateIn=await p.$('input[type=date]'); const cd=new Date(Date.now()+4*86400e3).toISOString().slice(0,10);
 if(dateIn){ await dateIn.fill(cd); await p.waitForTimeout(1500); console.log('календарь',cd,p.url().split('?')[1],await sig()); }
 await h.shot('p2-s3-calendar'); console.log('chips',await p.$$eval('a.chip.day',e=>e.map(x=>x.innerText+'@'+Math.round(x.getBoundingClientRect().left)+'-'+Math.round(x.getBoundingClientRect().right))));
 console.log('hscroll',JSON.stringify(await h.hscroll()),'console',h.log.console,'net',h.log.net.filter(x=>!/ERR_ABORTED/.test(x)));
 await b.close();
})();
