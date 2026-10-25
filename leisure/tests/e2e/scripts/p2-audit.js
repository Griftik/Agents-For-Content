const L=require('./lib.js'); const fs=require('fs');
const contrast=()=>{
  const parse=(c)=>{const m=c.match(/rgba?\(([^)]+)\)/); if(!m) return null; const a=m[1].split(/[ ,\/]+/).map(Number); return {r:a[0],g:a[1],b:a[2],a:a.length>3?a[3]:1};};
  const lum=({r,g,b})=>{const f=v=>{v/=255;return v<=0.03928?v/12.92:Math.pow((v+0.055)/1.055,2.4)}; return .2126*f(r)+.7152*f(g)+.0722*f(b)};
  const bgOf=(el)=>{let layers=[]; for(let e=el;e;e=e.parentElement){const c=parse(getComputedStyle(e).backgroundColor); if(c&&c.a>0){layers.push(c); if(c.a>=1)break;}} let base={r:255,g:255,b:255}; if(!layers.length||layers[layers.length-1].a<1){const b=parse(getComputedStyle(document.body).backgroundColor)||base; layers.push(b.a?b:base);} let out=layers[layers.length-1]; out={r:out.r,g:out.g,b:out.b}; for(let i=layers.length-2;i>=0;i--){const l=layers[i]; out={r:l.r*l.a+out.r*(1-l.a),g:l.g*l.a+out.g*(1-l.a),b:l.b*l.a+out.b*(1-l.a)};} return out;};
  const res=new Map();
  const w=document.createTreeWalker(document.body,NodeFilter.SHOW_TEXT);
  while(w.nextNode()){const n=w.currentNode; if(!n.textContent.trim()) continue; const el=n.parentElement; const cs=getComputedStyle(el); if(cs.visibility==='hidden'||cs.display==='none') continue; const r=el.getBoundingClientRect(); if(r.width===0||r.height===0) continue; if(el.closest('dialog:not([open])')) continue;
    let fg=parse(cs.color); const op=parseFloat(cs.opacity); const bg=bgOf(el); if(!fg) continue; const a=fg.a*(isNaN(op)?1:op); fg={r:fg.r*a+bg.r*(1-a),g:fg.g*a+bg.g*(1-a),b:fg.b*a+bg.b*(1-a)};
    const l1=lum(fg),l2=lum(bg); const ratio=(Math.max(l1,l2)+.05)/(Math.min(l1,l2)+.05); const size=parseFloat(cs.fontSize); const bold=parseInt(cs.fontWeight)>=700; const large=size>=24||(size>=18.66&&bold); const need=large?3:4.5;
    if(ratio<need){const k=n.textContent.trim().slice(0,30)+'|'+ratio.toFixed(2); res.set(k,{t:n.textContent.trim().slice(0,40),ratio:+ratio.toFixed(2),need,size,disabled:!!el.closest('input:disabled,label:has(input:disabled)')});}}
  return [...res.values()];
};
(async()=>{
 const b=await L.chromium.launch(); const out={};
 for(const scheme of ['light','dark']){
  const h=await L.mk(b,scheme); const p=h.p; const u=await L.guest(h);
  await L.onboard(u,'Аня',['Исследования','Смысл','Свобода','Природа','Здоровье']);
  const f=(await L.api(`/api/feed?user_id=${u}&date=today&segment=leisure`)).body; const sl=f.items[2].event.slug;
  await L.api('/api/decisions',{method:'POST',body:JSON.stringify({user_id:u,event:f.items[0].event.slug,status:'иду',day:f.today})});
  const pf=(await L.api(`/api/feed?user_id=${u}&date=2026-10-24&today=2026-10-24&segment=all`)).body; await L.api('/api/decisions',{method:'POST',body:JSON.stringify({user_id:u,event:pf.items[0].event.slug,status:'иду',day:'2026-10-24'})});
  const pages=[['digest','/digest'],['plan','/plan'],['profile','/profile'],['event','/e/'+sl],['policy','/policy'],['tomorrow','/digest?day=tomorrow&seg=all'],['empty-biz','/digest?day=week&seg=business']];
  for(const [n,url] of pages){ await h.go(url); const c=await p.evaluate(contrast); const hs=await h.hscroll(); const cl=await h.clip(); out[scheme+' '+n]={hs:hs.sw+'/'+hs.iw,low:c.slice(0,8),clip:cl}; if(n==='profile'||n==='plan'||n==='policy'){await h.shot('p2a-'+n,true);} else await h.shot('p2a-'+n); }
  // welcome и шаги
  const g=await L.mk(b,scheme); await g.go('/'); out[scheme+' welcome']={low:await g.p.evaluate(contrast),hs:JSON.stringify(await g.hscroll())};
  await g.tap('input[name=consent]'); await g.tap('button:has-text("Начать")'); out[scheme+' step1']={low:await g.p.evaluate(contrast)};
  const du=await L.guest(g);
  await L.api(`/api/profile/${u}`,{method:'DELETE'}); await L.api(`/api/profile/${du}`,{method:'DELETE'});
  out[scheme+' console']=[h.log.console,g.log.console];
 }
 console.log(JSON.stringify(out,null,1)); await b.close();
})();
