const L=require('./lib.js'); const fs=require('fs');
const scheme=process.argv[2]||'light';
const R=[]; const rec=(sc,ok,taps,note)=>{R.push({sc,ok,taps,note}); console.log(ok?'PASS':'FAIL',sc,'taps='+taps,note||'');};
const uidOf=async(h)=>{ const c=(await h.ctx.cookies()).find(c=>c.name==='leisure_session'); return c?Number(decodeURIComponent(c.value).split('.')[0]):null; };
const firstTitle=(t)=>{ const m=t.match(/\d+ \/ \d+/); return m?m[0]:'-'; };
(async()=>{
 const b=await L.chromium.launch(); const h=await L.mk(b,scheme); const p=h.p;
 const fb=[]; const uids=[];
 // ---- S1
 await h.go('/'); const t0=h.log.taps;
 await h.tap('input[name=consent]'); await p.fill('input[name=name]','Аня'); await h.tap('button:has-text("Начать")');
 await h.shot('s1-step1');
 const defaults=await p.$$eval('.pick input:checked',els=>els.map(e=>e.value));
 for(const v of defaults) await h.tap(`.pick label:has(input[value="${v}"])`);
 const own=['Исследования','Инновации/новизна','Красота/эстетика','Смысл','Свобода'];
 for(const v of own) await h.tap(`.pick label:has(input[value="${v}"])`);
 await p.waitForTimeout(1200);
 const onS2=p.url().includes('onboarding=2');
 await h.shot('s1-step2');
 await h.tap('.seg label:has-text("2 500")');
 await h.tap('button:has-text("Показать")'); await p.waitForTimeout(1500);
 const uid=await uidOf(h); uids.push(uid);
 const txt=await h.text(); const cnt=firstTitle(txt);
 await h.shot('s1-digest');
 const hs=await h.hscroll();
 rec('S1 первый вход (свои 5 ценностей)', onS2 && p.url().includes('/digest') && /\/ \d+/.test(txt), h.log.taps-t0, `defaults=${defaults.length}, step2 авто=${onS2}, лента ${cnt}, hscroll ${hs.sw}/${hs.iw}`);
 const feedMain=(await L.api(`/api/feed?user_id=${uid}&date=today&segment=leisure`)).body;
 // ---- S2
 await h.go('/digest'); const s2=h.log.taps;
 const badge=/УСПЕВАЕШЬ/i.test(await h.text());
 await h.tap('button:has-text("Иду")'); await p.waitForTimeout(600);
 const link=await p.$eval('dialog[open] a:has-text("К билетам")',a=>a.href).catch(()=>null);
 await h.shot('s2-idu-sheet');
 rec('S2 «освободился вечер»', badge && !!link, h.log.taps-s2, `бейдж=${badge}, ссылка=${link}`);
 await h.tap('dialog[open] button:has-text("Дальше")');
 // ---- S3
 const combos=[['today','leisure'],['tomorrow','leisure'],['day2','leisure'],['week','leisure'],['week','business'],['week','all'],['today','business'],['today','all']];
 const res={}; const s3=h.log.taps; 
 for(const [d,s] of combos){ await h.go(`/digest?day=${d}&seg=${s}`); const t=await h.text(); const c=t.match(/(\d+) \/ (\d+)/); const title=(await p.$eval('.deck h2, article h2, h2',e=>e.innerText).catch(()=>'')).slice(0,40); res[d+'/'+s]=(c?c[2]:'0')+' | '+(c?title:(t.split('\n').filter(x=>x.trim()).slice(-4).join(' / ').slice(0,80))); await h.shot(`s3-${d}-${s}`); }
 console.log(res);
 // через UI: тапы по чипам
 await h.go('/digest'); const s3t=h.log.taps;
 await h.tap('a.chip.day:has-text("Завтра")'); const u1=p.url();
 await h.tap('a.chip.day:has-text("Неделя")'); const u2=p.url();
 await h.tap('.segment a:has-text("Дело")'); const u3=p.url(); const tb=(await h.text());
 await h.shot('s3-week-biz-ui');
 await h.tap('.segment a:has-text("Всё")'); const u4=p.url();
 // календарь
 const dateIn=await p.$('input[type=date]'); let calNote='нет input date';
 if(dateIn){ const cd=new Date(Date.now()+4*86400e3).toISOString().slice(0,10); await dateIn.fill(cd).catch(e=>calNote='fill err '+e.message.slice(0,60)); await p.waitForTimeout(1500); calNote=p.url()+' / '+(await h.text()).split('\n').filter(x=>x.trim())[1]; }
 await h.shot('s3-calendar');
 const distinct=new Set(Object.values(res).map(v=>v.split(' | ')[0])).size;
 rec('S3 дни и направления', u1.includes('tomorrow')&&u2.includes('week')&&u3.includes('business')&&u4.includes('all')&&distinct>1, h.log.taps-s3t, `URL: ${[u1,u2,u3,u4].map(u=>u.split('?')[1]).join(' → ')}; календарь: ${calNote}; размеры: ${JSON.stringify(res)}`);
 console.log('console',h.log.console,'net',h.log.net);
 fs.writeFileSync(process.env.S+`/state-${scheme}.json`,JSON.stringify({uid,R,res}));
 await b.close();
})();
