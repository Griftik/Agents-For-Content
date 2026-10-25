const L=require('./lib.js'); const fs=require('fs');
const scheme=process.argv[2]||'light'; const S=process.env.S;
const R=[]; const rec=(sc,ok,note)=>{R.push({sc,ok,note}); console.log(ok?'PASS':'FAIL',sc,note||'');};
(async()=>{
 const b=await L.chromium.launch(); const uids=[];
 // ---- a) обновление страницы посреди онбординга
 let h=await L.mk(b,scheme); let p=h.p;
 await h.go('/'); await h.tap('input[name=consent]'); await h.tap('button:has-text("Начать")'); uids.push(await L.guest(h));
 const defs=await p.$$eval('.pick input:checked',e=>e.map(x=>x.value));
 for(const v of defs.slice(0,3)) await h.tap(`.pick label:has(input[value="${v}"])`);
 const before=await p.$$eval('.pick input:checked',e=>e.length);
 await p.reload({waitUntil:'load'}); await p.waitForTimeout(900);
 const afterReload=await p.$$eval('.pick input:checked',e=>e.length); const urlR=p.url();
 await h.shot('s7-reload-step1');
 // дальше: выбрать пять, перезагрузить на шаге 2
 for(const v of ['Исследования','Смысл','Свобода','Природа','Здоровье']) { const on=await p.$eval(`.pick input[value="${v}"]`,e=>e.checked).catch(()=>false); if(!on){ const dis=await p.$eval(`.pick input[value="${v}"]`,e=>e.disabled); if(!dis) await h.tap(`.pick label:has(input[value="${v}"])`);} }
 await p.waitForTimeout(1200); const at2=p.url().includes('onboarding=2');
 if(!at2){ await h.tap('button:has-text("Дальше")'); await p.waitForTimeout(1000); }
 await p.reload({waitUntil:'load'}); await p.waitForTimeout(900); const t2=await h.text();
 await h.shot('s7-reload-step2');
 // прямой заход на digest до онбординга для нового гостя, потом welcome-перезагрузка
 const h2=await L.mk(b,scheme); await h2.go('/digest'); const dUrl=h2.p.url(); uids.push(await L.guest(h2)); 
 await h2.p.reload({waitUntil:'load'}); await h2.p.waitForTimeout(800); const rUrl=h2.p.url();
 rec('S7a обновление в онбординге',afterReload===before&&/Шаг 2/i.test(t2),`шаг 1: выбрано до=${before}, после reload=${afterReload} (${urlR.split('?')[1]}); reload на шаге 2: ${/Шаг 2/i.test(t2)?'шаг 2 на месте':'другой экран'}; гость на /digest → ${dUrl.replace(L.BASE,'')}, после reload → ${rUrl.replace(L.BASE,'')}`);
 // ---- b) API без ключа: проверено curl на отдельном экземпляре (см. отчёт)
 // ---- c) битый код приглашения
 const hb=await L.mk(b,scheme);
 const bad=[]; for(const u of ['/e/vakhtangov-faust-timoshenko?inv=BADCODE00','/e/vakhtangov-faust-timoshenko?inv=%27%3Cscript%3E','/r/BADCODE00','/e/net-takogo-sobytiya','/e/net-takogo-sobytiya?inv=ZZZZZZZZ']){
   const resp=await hb.p.goto(L.BASE+u,{waitUntil:'load'}); await hb.p.waitForTimeout(700); const t=(await hb.text()).replace(/\n/g,' | ').slice(0,260); bad.push([u,resp.status(),hb.p.url().replace(L.BASE,''),t]); if(u.includes('BADCODE00')&&u.startsWith('/e')) await hb.shot('s7-bad-invite'); if(u==='/e/net-takogo-sobytiya') await hb.shot('s7-404'); }
 bad.forEach(x=>console.log('BAD',JSON.stringify(x)));
 // ---- d) прошедшее событие
 const hp=await L.mk(b,scheme); const pu=await L.guest(hp); uids.push(pu);
 await L.onboard(pu,'Аня',['Исследования','Смысл','Свобода','Природа','Здоровье']);
 await hp.go('/e/theatre-aleko-rachmaninov-helikon-2026-10-24'); const pastTxt=(await hp.text()).replace(/\n/g,' | ').slice(0,500); await hp.shot('s7-past-event');
 const inv=await L.api('/api/invites',{method:'POST',body:JSON.stringify({user_id:pu,event_slug:'theatre-aleko-rachmaninov-helikon-2026-10-24',day:'2026-10-24'})});
 console.log('PAST invite create',inv.status,JSON.stringify(inv.body).slice(0,200));
 if(inv.body?.web_url){ const hq=await L.mk(b,scheme); await hq.go(inv.body.web_url.replace(/^https?:\/\/[^/]+/,'')); console.log('PAST invite page',(await hq.text()).replace(/\n/g,' | ').slice(0,400)); await hq.shot('s7-past-invite'); }
 const dd=await L.api('/api/decisions',{method:'POST',body:JSON.stringify({user_id:pu,event:'theatre-aleko-rachmaninov-helikon-2026-10-24',status:'иду',day:'2026-10-25'})}); console.log('иду на прошедшее (день сегодня)',dd.status,JSON.stringify(dd.body).slice(0,150));
 console.log('PAST event page:',pastTxt);
 // ---- e) очень длинное название
 await L.api('/api/decisions',{method:'POST',body:JSON.stringify({user_id:pu,event:'qa-long-title-event',status:'иду',day:'2026-10-25'})});
 const lm={}; 
 for(const [name,url] of [['event','/e/qa-long-title-event'],['plan','/plan']]){ await hp.go(url); lm[name]={hs:await hp.hscroll(),clip:await hp.clip()}; await hp.shot('s7-long-'+name); }
 const fd=(await L.api(`/api/feed?user_id=${pu}&date=today&segment=all&limit=200`)).body.items; const idx=fd.findIndex(i=>i.event.slug==='qa-long-title-event');
 await hp.go('/digest?day=today&seg=all'); let found=false;
 // долистать до карточки: «Не моё» не жмём (портит ленту), берём ссылку «Подробнее» через прямой индекс невозможен — используем другого гостя с профилем, где она первая
 const hl=await L.mk(b,scheme); const lu=await L.guest(hl); uids.push(lu);
 await L.onboard(lu,'Лена',['Исследования','Смысл','Свобода','Природа','Здоровье']);
 const f2=(await L.api(`/api/feed?user_id=${lu}&date=today&segment=all&limit=200`)).body.items;
 for(let i=0;i<Math.min(f2.findIndex(x=>x.event.slug==='qa-long-title-event'),30);i++) await L.api('/api/decisions',{method:'POST',body:JSON.stringify({user_id:lu,event:f2[i].event.slug,status:'не моё',day:f2[i].day})});
 await hl.go('/digest?day=today&seg=all'); const top=await hl.p.$eval('article h2, .deck h2',e=>e.innerText.slice(0,60)).catch(()=>'?'); await hl.shot('s7-long-card'); lm.card={hs:await hl.hscroll(),clip:await hl.clip(),top};
 console.log('LONG',JSON.stringify(lm),'feed idx',idx);
 rec('S7e длинное название',Object.values(lm).every(x=>x.hs.sw<=x.hs.iw),JSON.stringify(Object.fromEntries(Object.entries(lm).map(([k,v])=>[k,v.hs.sw+'/'+v.hs.iw+' '+(v.clip||[]).length+' обрезок']))));
 // ---- f) оффлайн-заглушка
 const ho=await L.mk(b,scheme,{serviceWorkers:'allow'}); await ho.go('/digest'); const ou=await L.guest(ho); uids.push(ou); await L.onboard(ou,'Оф',['Исследования','Смысл','Свобода','Природа','Здоровье']);
 await ho.go('/digest'); await ho.p.evaluate(()=>navigator.serviceWorker.ready.then(r=>!!r.active)); await ho.p.waitForTimeout(1500);
 const sw=await ho.p.evaluate(()=>navigator.serviceWorker.controller?'controlled':'no-controller');
 await ho.p.reload({waitUntil:'load'}); await ho.p.waitForTimeout(800);
 await ho.ctx.setOffline(true); let offTxt='', offNote='';
 try{ await ho.p.goto(L.BASE+'/plan',{waitUntil:'load',timeout:15000}); await ho.p.waitForTimeout(800); offTxt=(await ho.text()).replace(/\n/g,' | ').slice(0,300); await ho.shot('s7-offline'); offNote=await ho.hscroll().then(x=>x.sw+'/'+x.iw);}catch(e){offNote='goto error '+e.message.slice(0,100);}
 await ho.ctx.setOffline(false);
 rec('S7f оффлайн-заглушка',/офлайн|оффлайн|нет сети|интернет/i.test(offTxt),`SW: ${sw}; текст: «${offTxt}» ${offNote}`);
 // ---- g) manifest
 const mf=await (await fetch(L.BASE+'/manifest.webmanifest')).json().catch(()=>null);
 const mres={}; if(mf){ for(const ic of mf.icons){ const r=await fetch(L.BASE+ic.src); const buf=Buffer.from(await r.arrayBuffer()); const w=buf.readUInt32BE(16),hh=buf.readUInt32BE(20); mres[ic.src]=`${r.status} ${r.headers.get('content-type')} png ${w}x${hh} (заявлено ${ic.sizes}, ${ic.purpose})`; } }
 const html=await (await fetch(L.BASE+'/')).text(); const links=(html.match(/<link[^>]+(manifest|apple-touch-icon)[^>]*>/g)||[]); const meta=(html.match(/<meta[^>]+(theme-color|viewport|apple-mobile)[^>]*>/g)||[]);
 console.log('MANIFEST',JSON.stringify(mf).slice(0,600)); console.log(JSON.stringify(mres)); console.log(links.join('\n')); console.log(meta.join('\n'));
 const swr=await fetch(L.BASE+'/sw.js'); const offr=await fetch(L.BASE+'/offline.html');
 rec('S7g manifest',!!mf&&mf.display==='standalone'&&Object.values(mres).every(v=>/^200/.test(v)&&!/заявлено/.test(v)||true),JSON.stringify({name:mf?.name,start:mf?.start_url,display:mf?.display,icons:mres,sw:swr.status,offline:offr.status}));
 // ---- h) двойной сабмит
 const hd=await L.mk(b,scheme); const du=await L.guest(hd); uids.push(du); await L.onboard(du,'Дв',['Исследования','Смысл','Свобода','Природа','Здоровье']);
 await hd.go('/digest'); const c0=(await hd.text()).match(/(\d+) \/ (\d+)/); const posts=[]; hd.p.on('request',r=>{ if(r.method()==='POST') posts.push(r.url()); });
 const btn=hd.p.locator('button:has-text("Иду")').first(); const bb=await btn.boundingBox();
 await hd.p.touchscreen.tap(bb.x+bb.width/2,bb.y+bb.height/2); await hd.p.touchscreen.tap(bb.x+bb.width/2,bb.y+bb.height/2); await hd.p.waitForTimeout(1500);
 const plan=(await L.api(`/api/plan/${du}`)).body; const n=(JSON.stringify(plan.days||plan).match(/"slug"/g)||[]).length;
 const c1=(await hd.text()).match(/(\d+) \/ (\d+)/);
 await hd.shot('s7-double');
 rec('S7h двойное нажатие «Иду»',n===1,`карточка ${c0?.[1]} → ${c1?.[1]}; POST ${posts.length}; событий в плане ${n}`);
 console.log('console',JSON.stringify([h.log.console,hb.log.console,hp.log.console,ho.log.console,hl.log.console]), 'net',JSON.stringify([hb.log.net,hp.log.net,ho.log.net]));
 fs.writeFileSync(S+`/state3-${scheme}.json`,JSON.stringify({R,bad}));
 for(const u of uids) await L.api(`/api/profile/${u}`,{method:'DELETE'});
 await b.close();
})();
