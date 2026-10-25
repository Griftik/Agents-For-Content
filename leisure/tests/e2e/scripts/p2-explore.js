const L=require('./lib.js');
(async()=>{
 const b=await L.chromium.launch(); const h=await L.mk(b,'light'); const p=h.p;
 await h.go('/'); console.log(await h.text());
 await h.tap('input[name=consent]'); await p.fill('input[name=name]','Аня'); await h.tap('button:has-text("Начать")');
 await p.waitForTimeout(800); console.log(p.url()); console.log((await h.text()).replace(/\n/g,' | '));
 console.log('checked',await p.$$eval('.pick input:checked',e=>e.length),'disabled',await p.$$eval('.pick input:disabled',e=>e.length),'total',await p.$$eval('.pick input',e=>e.length));
 await h.shot('p2-s1-step1');
 const vals=await p.$$eval('.pick input',e=>e.map(x=>x.value)); console.log(vals);
 for(const v of vals.slice(0,5)) await h.tap(`.pick label:has(input[value="${v}"])`);
 await p.waitForTimeout(1500); console.log(p.url()); console.log((await h.text()).replace(/\n/g,' | '));
 console.log(await p.evaluate(()=>document.querySelector('main, body').innerHTML.slice(0,3000)));
 await b.close();
})();
