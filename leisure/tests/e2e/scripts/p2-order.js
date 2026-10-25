const L=require('./lib.js');
(async()=>{
 const b=await L.chromium.launch(); const h=await L.mk(b,'light'); const p=h.p;
 const uid=await L.guest(h); await L.onboard(uid,'Аня',['Исследования','Инновации/новизна','Красота/эстетика','Смысл','Свобода']);
 const f0=(await L.api(`/api/feed?user_id=${uid}&date=today&segment=all`)).body; const yday=new Date(Date.parse(f0.today)-86400e3).toISOString().slice(0,10);
 const pf=(await L.api(`/api/feed?user_id=${uid}&date=${yday}&today=${yday}&segment=all&limit=100`)).body;
 for(const x of pf.items.slice(0,4)) await L.api('/api/decisions',{method:'POST',body:JSON.stringify({user_id:uid,event:x.event.slug,status:'иду',day:yday})});
 const order=()=>p.$$eval('.pastmark',els=>els.map(e=>{let n=e; while(n&&!n.querySelector('a, h3, strong')) n=n.parentElement; const li=e.parentElement; return (li.innerText||'').split('\n').filter(x=>x.trim()).slice(0,2).join(' / ').slice(0,60);}));
 await h.go('/plan'); const o0=await order(); console.log('до',o0);
 await h.tap(p.locator('.pastmark').nth(0).locator('button:has-text("Сходил")').first()); const o1=await order(); console.log('после Сходил на 1-й',o1);
 await h.tap(p.locator('.pastmark').nth(0).locator('.stars button:has-text("4 ★")').first()); const o2=await order(); console.log('после 4★',o2);
 await h.tap(p.locator('.pastmark').nth(1).locator('button:has-text("Не сходил")').first()); const o3=await order(); console.log('после Не сходил на 2-й',o3);
 console.log('стабильно:',JSON.stringify(o0)===JSON.stringify(o1)&&JSON.stringify(o1)===JSON.stringify(o2)&&JSON.stringify(o2)===JSON.stringify(o3));
 await h.shot('p2-s4-order-stable');
 await L.api(`/api/profile/${uid}`,{method:'DELETE'}); await b.close();
})();
