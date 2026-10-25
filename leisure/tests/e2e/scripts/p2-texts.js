const L=require('./lib.js');
(async()=>{
 const b=await L.chromium.launch(); const h=await L.mk(b,'light'); const p=h.p;
 const uid=await L.guest(h); await L.onboard(uid,'Аня',['Исследования','Инновации/новизна','Красота/эстетика','Смысл','Свобода']);
 for(const u of ['/plan','/profile','/digest?day=tomorrow&seg=business','/e/vakhtangov-faust-timoshenko','/policy?x=1']){ await h.go(u); const t=await p.evaluate(()=>[...document.querySelectorAll('main p, main small, main .muted, main .hint')].map(e=>e.innerText.trim()).filter(x=>x.length>25)); console.log(u,'→',JSON.stringify(t.slice(0,6)).slice(0,500)); }
 await L.api(`/api/profile/${uid}`,{method:'DELETE'}); await b.close();
})();
