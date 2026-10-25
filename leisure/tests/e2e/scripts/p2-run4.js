// Прогон 2, сценарий 5: профиль «Ребёнок»; чип профиля
const L=require('./lib.js'); const fs=require('fs');
const scheme=process.argv[2]||'light';
(async()=>{
 const b=await L.chromium.launch(); const h=await L.mk(b,scheme); const p=h.p;
 const uid=await L.guest(h); await L.onboard(uid,'Аня',['Исследования','Инновации/новизна','Красота/эстетика','Смысл','Свобода']);
 const F=async(u,d='today',s='leisure')=>(await L.api(`/api/feed?user_id=${u}&date=${d}&segment=${s}&limit=100`)).body;
 await h.go('/digest'); const t=h.log.taps;
 console.log('чип профиля:',await p.$eval('.pswitch',e=>e.innerText.replace(/\n/g,'|')));
 await h.tap('.pswitch'); await h.shot('p2-s5-switcher'); console.log('лист профилей:',(await p.$eval('dialog[open]',e=>e.innerText)).replace(/\n/g,' | '));
 await h.tap('dialog[open] button:has-text("Новый профиль")'); await p.fill('dialog[open] input[name=pname]','Сын'); await h.tap('dialog[open] label:has-text("Ребёнок")'); await h.shot('p2-s5-new');
 await h.tap('dialog[open] button:has-text("Дальше")'); await p.waitForTimeout(1200);
 console.log('шаг1 h1:',await p.$eval('h1',e=>e.innerText),'| выбрано',await p.$$eval('.pick input:checked',e=>e.length),'| текст:',(await h.text()).replace(/\n/g,' | ').slice(0,160));
 await h.shot('p2-s5-child-step1');
 for(const v of ['Веселье','Азарт','Природа','Семья','Удовольствие']) await h.tap(`.pick label:has(input[value="${v}"])`);
 await p.waitForTimeout(1200); console.log('шаг2:',(await h.text()).replace(/\n/g,' | ').slice(0,200)); await h.shot('p2-s5-child-step2');
 await h.tap('button:has-text("Показать")'); await p.waitForTimeout(1800);
 await h.shot('p2-s5-child-feed'); console.log('taps до ленты',h.log.taps-t,'чип:',await p.$eval('.pswitch',e=>e.innerText.replace(/\n/g,'|')));
 const cu=(await L.api(`/api/profiles?user_id=${uid}`)).body; const child=cu.profiles.find(x=>x.name==='Сын'); console.log('child',child.user_id,child.kind);
 const bad=/вин|wine|бурлеск|сатан|рейв|ночн|18\+|бар\b|коктейл|пив/i;
 for(const [d,s] of [['today','leisure'],['week','all'],['week','leisure']]){ const fc=await F(child.user_id,d,s); const fa=await F(uid,d,s);
   console.log(`--- ребёнок ${d}/${s}: ${fc.items.length} карточек (взрослый ${fa.items.length})`);
   const badItems=fc.items.filter(i=>bad.test(i.event.title+' '+i.event.category)); console.log('  подозрительные у ребёнка:',badItems.map(i=>i.event.title.slice(0,40)+' ['+i.event.category+']'));
   console.log('  top10:',fc.items.slice(0,10).map(i=>i.event.title.slice(0,32)+' ['+i.event.category+']'));
   console.log('  категории:',[...new Set(fc.items.map(i=>i.event.category))].join(', '));
   if(d==='week'&&s==='all'){ console.log('  у взрослого те же подозрительные:',fa.items.filter(i=>bad.test(i.event.title+' '+i.event.category)).length); const kids=fc.items.map((i,k)=>[k,i.event.title.slice(0,30),i.event.category]).filter(x=>/дет|семей|кукол|мульт|сказк|ребён|кукол/i.test(x[1]+x[2])); console.log('  детские/семейные позиции:',JSON.stringify(kids.slice(0,8))); } }
 // решения не смешиваются
 await h.tap('button:has-text("Иду")'); await h.tap('dialog[open] button:has-text("Дальше")');
 const pc=JSON.stringify((await L.api(`/api/plan/${child.user_id}`)).body.days), pa=JSON.stringify((await L.api(`/api/plan/${uid}`)).body.days);
 console.log('план ребёнка событий',(pc.match(/"slug"/g)||[]).length,'у Ани',(pa.match(/"slug"/g)||[]).length);
 await h.tap('.pswitch'); await h.shot('p2-s5-switcher2'); await h.tap('dialog[open] li button:has-text("Аня")'); await p.waitForTimeout(1200);
 console.log('после возврата чип:',await p.$eval('.pswitch',e=>e.innerText.replace(/\n/g,'|')), 'лента:',(await h.text()).match(/\d+ \/ \d+/)?.[0]); await h.shot('p2-s5-back');
 console.log('hscroll',JSON.stringify(await h.hscroll()),'console',h.log.console,'net',h.log.net.filter(x=>!/ABORTED/.test(x)));
 for(const u of [child.user_id,uid]) await L.api(`/api/profile/${u}`,{method:'DELETE'}); await b.close();
})();
