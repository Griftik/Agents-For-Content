// Прогон 2: оффлайн-заглушка без внешних шрифтов, manifest, внешние запросы, прошедшее событие
const L=require('./lib.js'); const fs=require('fs');
const scheme=process.argv[2]||'light';
(async()=>{
 const b=await L.chromium.launch(); const h=await L.mk(b,scheme); const p=h.p;
 const hosts=new Set(); p.on('request',r=>hosts.add(new URL(r.url()).host));
 const uid=await L.guest(h); await L.onboard(uid,'Аня',['Исследования','Инновации/новизна','Красота/эстетика','Смысл','Свобода']);
 for(const u of ['/digest','/plan','/profile','/e/vakhtangov-faust-timoshenko','/policy']) { await h.go(u); await p.waitForTimeout(500); }
 console.log('хосты запросов:',[...hosts]);
 const fonts=await p.evaluate(()=>[...document.fonts].filter(f=>f.status==='loaded').map(f=>f.family+' '+f.weight));
 console.log('загружены шрифты:',[...new Set(fonts)].join(', '));
 const m=await (await h.ctx.request.get(L.BASE+'/manifest.webmanifest')).json(); console.log('manifest',JSON.stringify({name:m.name,short:m.short_name,display:m.display,start:m.start_url,theme:m.theme_color,bg:m.background_color,icons:m.icons.map(i=>i.sizes+' '+i.purpose)}));
 for(const i of m.icons){ const r=await h.ctx.request.get(L.BASE+i.src); console.log('  icon',i.src,r.status(),(await r.body()).length); }
 for(const u of ['/sw.js','/offline.html','/fonts/fonts.css']){ const r=await h.ctx.request.get(L.BASE+u); console.log(u,r.status()); }
 // SW
 await h.go('/digest'); await p.waitForTimeout(1500);
 const sw=await p.evaluate(async()=>{const r=await navigator.serviceWorker.getRegistration(); await navigator.serviceWorker.ready; return !!navigator.serviceWorker.controller||!!r;});
 console.log('SW зарегистрирован',sw); await p.reload(); await p.waitForTimeout(1200); console.log('SW управляет',await p.evaluate(()=>!!navigator.serviceWorker.controller));
 await h.ctx.setOffline(true);
 const reqs=[]; p.on('request',r=>reqs.push(r.url()));
 try{ await p.goto(L.BASE+'/plan',{waitUntil:'load',timeout:8000}); }catch(e){ console.log('goto err',e.message.slice(0,80)); }
 await p.waitForTimeout(1500);
 const ot=await h.text(); console.log('оффлайн:',ot.replace(/\n/g,' | ').slice(0,200)); await h.shot('p2-s9-offline');
 const ff=await p.evaluate(()=>{ const e=document.querySelector('h1,h2,p'); return getComputedStyle(e).fontFamily+' | '+[...document.fonts].filter(f=>f.status==='loaded').map(f=>f.family).join(',') });
 console.log('шрифт заглушки:',ff,'| внешние запросы оффлайн:',reqs.filter(u=>!u.startsWith(L.BASE)).slice(0,5));
 console.log('hscroll',JSON.stringify(await h.hscroll()));
 await h.ctx.setOffline(false);
 console.log('console',h.log.console);
 await L.api(`/api/profile/${uid}`,{method:'DELETE'}); await b.close();
})();
