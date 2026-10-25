const { chromium } = require('playwright');
const fs=require('fs');
const OUT='/home/user/Agents-For-Content/leisure/tests/e2e/shots';
const BASE='http://localhost:3111', API='http://localhost:8000';
exports.BASE=BASE; exports.API=API; exports.OUT=OUT;
exports.mk = async (browser, scheme, opts={}) => {
  const ctx=await browser.newContext({viewport:{width:390,height:844},deviceScaleFactor:3,isMobile:true,hasTouch:true,colorScheme:scheme,locale:'ru-RU',...opts});
  const p=await ctx.newPage();
  const log={console:[],net:[],taps:0};
  p.on('console',m=>{ if(['error','warning'].includes(m.type())) log.console.push(m.type()+': '+m.text().slice(0,200)); });
  p.on('pageerror',e=>log.console.push('PAGEERROR '+e.message.slice(0,200)));
  p.on('response',r=>{ if(r.status()>=400 && !r.url().includes('fonts.g')) log.net.push(r.status()+' '+r.request().method()+' '+r.url()); });
  p.on('requestfailed',r=>{ const u=r.url(); if(!u.includes('_rsc')&&!u.includes('fonts.g')) log.net.push('FAIL '+u+' '+r.failure()?.errorText); });
  const h={ctx,p,log};
  h.go=async(path)=>{ await p.goto(path.startsWith('http')?path:BASE+path,{waitUntil:'load'}); await p.waitForTimeout(900); };
  h.tap=async(sel,label)=>{ const loc=typeof sel==='string'?p.locator(sel).first():sel; await loc.scrollIntoViewIfNeeded().catch(()=>{}); await loc.tap(); log.taps++; await p.waitForTimeout(700); };
  h.text=()=>p.evaluate(()=>document.body.innerText);
  h.shot=async(name,full=false)=>{ await p.screenshot({path:`${OUT}/${name}-${scheme}.png`,fullPage:full}); };
  h.hscroll=()=>p.evaluate(()=>({sw:document.documentElement.scrollWidth,iw:window.innerWidth,bw:document.body.scrollWidth}));
  h.clip=()=>p.evaluate(()=>{ // элементы, вылезающие за правый край или с обрезанным текстом
    const out=[]; for(const e of document.querySelectorAll('body *')){ const r=e.getBoundingClientRect(); if(r.width===0) continue; const cs=getComputedStyle(e);
      if(r.right>window.innerWidth+1 && cs.position!=='fixed') out.push('OVERFLOW-R '+e.tagName+'.'+(e.className||'').toString().slice(0,40)+' '+Math.round(r.right));
      if((cs.overflow==='hidden'||cs.textOverflow==='ellipsis') && e.scrollWidth>e.clientWidth+1 && e.children.length===0 && e.innerText) out.push('CLIPPED '+e.tagName+' "'+e.innerText.slice(0,50)+'"'); }
    return out.slice(0,10); });
  return h;
};
exports.api=async(path,init={})=>{ const r=await fetch(API+path,{...init,headers:{'Content-Type':'application/json',...(init.headers||{})}}); return {status:r.status,body:await r.json().catch(()=>null)}; };
exports.chromium=chromium;
exports.guest=async(h)=>{ const r=await h.ctx.request.post(BASE+'/api/session'); const c=(await h.ctx.cookies()).find(c=>c.name==='leisure_session'); const uid=Number(decodeURIComponent(c.value).split('.')[0]); return uid; };
const top=(names)=>Object.fromEntries(['Творчество','Наставничество','Забота','Единство/Дружба','Развитие','Красота/эстетика','Инновации/новизна','Свобода','Семья','Исследования','Здоровье','Сохранение традиций','Природа','Удовольствие','Веселье','Азарт','Покой','Близость','Смысл'].map(v=>[v,names.includes(v)?5:2]));
exports.top=top;
exports.onboard=async(uid,name,vals,extra={})=>exports.api(`/api/profile/${uid}`,{method:'PUT',body:JSON.stringify({consent:true,name,values:top(vals),params:{budget:2500,travel_minutes:40},onboarded:true,...extra})});
