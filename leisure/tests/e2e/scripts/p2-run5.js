// Прогон 2, сценарий 6 (приглашение) + битые коды
const L=require('./lib.js'); const fs=require('fs');
const scheme=process.argv[2]||'light';
(async()=>{
 const b=await L.chromium.launch(); const h=await L.mk(b,scheme,{permissions:['clipboard-read','clipboard-write']}); const p=h.p; const uids=[];
 const uid=await L.guest(h); uids.push(uid); await L.onboard(uid,'Аня',['Исследования','Инновации/новизна','Красота/эстетика','Смысл','Свобода']);
 await h.go('/digest'); const t=h.log.taps;
 await h.tap('button:has-text("Иду")'); await h.tap('dialog[open] button:has-text("Позвать друга")'); await p.waitForTimeout(800);
 await h.shot('p2-s6-invite-sheet');
 console.log('лист:',(await p.$eval('dialog[open]',e=>e.innerText)).replace(/\n/g,' | '));
 await h.tap('dialog[open] button:has-text("Скопировать")'); await p.waitForTimeout(500);
 const clip=await p.evaluate(()=>navigator.clipboard.readText()); console.log('буфер:',clip.replace(/\n/g,' ⏎ '));
 const link=(clip.match(/https?:\/\/\S+/)||[])[0]; console.log('ссылка',link);
 const hf=await L.mk(b,scheme); const pf=hf.p; await hf.go(link); await hf.shot('p2-s6-friend-landing');
 const lt=await hf.text(); console.log('друг видит:',lt.replace(/\n/g,' | ').slice(0,500));
 await pf.fill('input[name=name]','Борис'); await hf.tap('input[type=checkbox]'); await hf.shot('p2-s6-friend-consent');
 const posts=[]; pf.on('request',r=>{ if(r.method()==='POST') posts.push(r.url()); });
 await hf.tap('button:has-text("Иду вместе")'); await pf.waitForTimeout(1200);
 const ft=await hf.text(); await hf.shot('p2-s6-friend-done'); console.log('друг после:',ft.replace(/\n/g,' | ').slice(0,400),'POST',posts.length);
 console.log('нажатий друга',hf.log.taps,'(+1 переход по ссылке)');
 await h.go('/plan'); const pt=await h.text(); await h.shot('p2-s6-inviter-plan'); console.log('у пригласившего «вдвоём с Борис»:',/вдвоём с борис/i.test(pt), pt.match(/[Вв]двоём[^\n]*/)?.[0]);
 const bid=await (async()=>{const c=(await hf.ctx.cookies()).find(c=>c.name==='leisure_session'); return c?Number(decodeURIComponent(c.value).split('.')[0]):null;})(); if(bid) uids.push(bid);
 // повторное открытие ссылки в новом контексте
 const hr=await L.mk(b,scheme); await hr.go(link); console.log('повтор по ссылке (новый контекст):',(await hr.text()).replace(/\n/g,' | ').slice(0,200));
 // Битые коды
 const slug=link.match(/\/e\/([^?]+)/)[1];
 const hb=await L.mk(b,scheme);
 for(const [name,url] of [['inv-bad',`/e/${slug}?inv=BADCODE00`],['inv-bad-unknown-event',`/e/net-takogo-sobytiya?inv=BADCODE00`],['r-bad','/r/BADCODE00'],['e-404','/e/net-takogo-sobytiya']]){
   const resp=await hb.p.goto(L.BASE+url,{waitUntil:'load'}); await hb.p.waitForTimeout(900);
   const tx=await hb.text(); console.log(`[${name}] ${url} → ${resp.status()} ${hb.p.url().replace(L.BASE,'')} :: ${tx.replace(/\n/g,' | ').slice(0,260)}`); await hb.shot('p2-s7-'+name);
   console.log('   hscroll',JSON.stringify(await hb.hscroll())); }
 console.log('consoles:',h.log.console,hf.log.console,hb.log.console,'net друг',hf.log.net.filter(x=>!/ABORTED/.test(x)),'net bad',hb.log.net);
 for(const u of uids) await L.api(`/api/profile/${u}`,{method:'DELETE'}); await b.close();
})();
