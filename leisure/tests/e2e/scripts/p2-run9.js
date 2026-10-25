const L=require('./lib.js');
const scheme=process.argv[2]||'light';
(async()=>{
 const b=await L.chromium.launch(); const h=await L.mk(b,scheme); const p=h.p;
 const uid=await L.guest(h); await L.onboard(uid,'Аня',['Исследования','Инновации/новизна','Красота/эстетика','Смысл','Свобода']);
 const f=(await L.api(`/api/feed?user_id=${uid}&date=today&segment=all`)).body;
 const slug=f.items[0].event.slug;
 // приглашение на вчера (создаётся вручную через API)
 const inv=await L.api('/api/invites',{method:'POST',body:JSON.stringify({user_id:uid,event_slug:slug,day:'2026-10-24'})}); console.log('invite on past day',inv.status,JSON.stringify(inv.body).slice(0,160));
 const code=inv.body.code; const hf=await L.mk(b,scheme);
 if(code){ await hf.go(`/e/${slug}?inv=${code}`); console.log('прошедшее приглашение:',(await hf.text()).replace(/\n/g,' | ').slice(0,600)); await hf.shot('p2-s7-past-invite'); }
 // двойной сабмит «Начать» и «Иду вместе»
 const hd=await L.mk(b,scheme); const posts=[]; hd.p.on('request',r=>{ if(r.method()==='POST') posts.push(r.url().replace(L.BASE,'')+' '+(r.postData()||'').slice(0,30)); });
 await hd.go('/'); await hd.p.locator('input[name=consent]').tap(); await hd.p.waitForTimeout(300);
 const btn=hd.p.locator('button:has-text("Начать")').first(); const bx=await btn.boundingBox(); await hd.p.touchscreen.tap(bx.x+bx.width/2,bx.y+bx.height/2); await hd.p.waitForTimeout(60); await hd.p.touchscreen.tap(bx.x+bx.width/2,bx.y+bx.height/2); await hd.p.waitForTimeout(1500); console.log('двойной «Начать»: POST',posts.length,posts, 'disabled?',await hd.p.$eval('button[type=submit]',e=>e.disabled+'/'+e.getAttribute('aria-disabled')).catch(()=>'ушли с экрана'));
 // двойной «Иду вместе»
 const hj=await L.mk(b,scheme); const pj=[]; hj.p.on('request',r=>{ if(r.method()==='POST') pj.push(r.url().replace(L.BASE,'')); });
 const inv2=await L.api('/api/invites',{method:'POST',body:JSON.stringify({user_id:uid,event_slug:slug,day:f.items[0].day})});
 await hj.go(`/e/${slug}?inv=${inv2.body.code}`); await hj.p.fill('input[name=name]','Борис'); await hj.p.locator('input[type=checkbox]').tap(); const bt=hj.p.locator('button:has-text("Иду вместе")').first(); await bt.scrollIntoViewIfNeeded(); const bb=await bt.boundingBox(); await hj.p.touchscreen.tap(bb.x+bb.width/2,bb.y+bb.height/2); await hj.p.waitForTimeout(60); await hj.p.touchscreen.tap(bb.x+bb.width/2,bb.y+bb.height/2); await hj.p.waitForTimeout(1500);
 console.log('двойной «Иду вместе»: POST',pj.length,pj);
 // двойной «Иду» в ленте
 await h.go('/digest'); const pi=[]; p.on('request',r=>{ if(r.method()==='POST') pi.push(r.url().replace(L.BASE,'')); });
 const ib=p.locator('.actionbar button:has-text("Иду")').first(); const ibb=await ib.boundingBox(); await p.touchscreen.tap(ibb.x+ibb.width/2,ibb.y+ibb.height/2); await p.waitForTimeout(60); await p.touchscreen.tap(ibb.x+ibb.width/2,ibb.y+ibb.height/2); await p.waitForTimeout(1500); console.log('двойной «Иду»: POST',pi.length);
 const decs=(await L.api(`/api/decisions/${uid}`)).body; console.log('решений у Ани',decs.length);
 const ids=[uid]; for(const hh of [hd,hj]){ const c=(await hh.ctx.cookies()).find(c=>c.name==='leisure_session'); if(c) ids.push(Number(decodeURIComponent(c.value).split('.')[0])); }
 for(const u of ids) await L.api(`/api/profile/${u}`,{method:'DELETE'}); await b.close();
})();
