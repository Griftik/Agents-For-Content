const L=require('./lib.js');
const scheme=process.argv[2]||'light';
(async()=>{
 const b=await L.chromium.launch(); const h=await L.mk(b,scheme); const p=h.p;
 await h.go('/'); await h.tap('input[name=consent]'); await h.tap('button:has-text("Начать")'); await p.waitForTimeout(800);
 for(const v of ['Здоровье','Природа','Покой','Семья','Забота']) await h.tap(`.pick label:has(input[value="${v}"])`);
 await p.waitForTimeout(1200); await h.tap('button:has-text("Показать")'); await p.waitForTimeout(1500);
 console.log('чип без имени:',JSON.stringify(await p.$eval('.pswitch',e=>e.innerText)), await p.$eval('.pswitch',e=>e.innerHTML.replace(/<svg.*?<\/svg>/g,'').slice(0,300)));
 await h.shot('p2-s6-chip-noname'); await h.go('/profile'); console.log('профиль без имени:',(await h.text()).replace(/\n/g,' | ').slice(0,120)); await h.shot('p2-s6-profile-noname');
 await h.tap('.pswitch'); console.log('лист:',(await p.$eval('dialog[open]',e=>e.innerText)).replace(/\n/g,' | ')); await h.shot('p2-s6-switcher-noname');
 const c=(await h.ctx.cookies()).find(c=>c.name==='leisure_session'); const uid=Number(decodeURIComponent(c.value).split('.')[0]); await L.api(`/api/profile/${uid}`,{method:'DELETE'}); await b.close();
})();
