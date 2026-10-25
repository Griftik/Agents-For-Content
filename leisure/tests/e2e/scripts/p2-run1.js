// Прогон 2, сценарий 1: первый вход. Запуск: NODE_PATH=$(npm root -g) S=<dir> node p2-run1.js light|dark
const L=require('./lib.js'); const fs=require('fs');
const scheme=process.argv[2]||'light';
(async()=>{
 const b=await L.chromium.launch(); const h=await L.mk(b,scheme); const p=h.p;
 await h.go('/'); await h.shot('p2-s1-welcome'); const t0=h.log.taps;
 await h.tap('input[name=consent]'); await p.fill('input[name=name]','Аня'); await h.tap('button:has-text("Начать")');
 await p.waitForTimeout(800);
 const pre=await p.$$eval('.pick input:checked',e=>e.length), dis=await p.$$eval('.pick input:disabled',e=>e.length), tot=await p.$$eval('.pick input',e=>e.length);
 console.log('step1: checked',pre,'disabled',dis,'total',tot, (await h.text()).includes('0 / 5'));
 await h.shot('p2-s1-step1');
 // обновление посреди шага 1 после двух выборов: черновик
 for(const v of ['Исследования','Инновации/новизна']) await h.tap(`.pick label:has(input[value="${v}"])`);
 await p.reload({waitUntil:'load'}); await p.waitForTimeout(800);
 const kept=await p.$$eval('.pick input:checked',e=>e.map(x=>x.value)); console.log('после reload выбрано',kept);
 await h.shot('p2-s1-step1-reload');
 // дальше — три ценности (кликнуть не выбранные)
 for(const v of ['Красота/эстетика','Смысл','Свобода']) await h.tap(`.pick label:has(input[value="${v}"])`);
 await p.waitForTimeout(1500); const onS2=p.url().includes('onboarding=2'); console.log('авто-переход на 2:',onS2);
 await h.shot('p2-s1-step2');
 console.log((await h.text()).replace(/\n/g,' | '));
 console.log(await p.$$eval('main input, main button, main select',e=>e.map(x=>x.tagName+':'+(x.name||x.innerText)+':'+(x.type||'')+':'+(x.value||'').slice(0,12)).join('  ')));
 await h.tap('.seg label:has-text("2 500")');
 await h.tap('button:has-text("Показать")'); await p.waitForTimeout(1800);
 const txt=await h.text(); console.log('url',p.url(),(txt.match(/\d+ \/ \d+/)||[])[0]);
 await h.shot('p2-s1-digest');
 // нажатия: считаем без «reload-теста» (2 выбора до перезагрузки считаются: они нужны для 5)
 console.log('ТАПОВ всего',h.log.taps-t0,'(из них бюджет 1; консоль',JSON.stringify(h.log.console),'net',JSON.stringify(h.log.net),')');
 console.log('hscroll',JSON.stringify(await h.hscroll()),'clip',await h.clip());
 console.log(txt.slice(0,700).replace(/\n/g,' | '));
 await b.close();
})();
