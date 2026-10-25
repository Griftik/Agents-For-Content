// Скриншоты экранов для проверки вёрстки: 390 × 844, обе темы, консоль и горизонтальный скролл. Нужен Playwright (require('playwright')).
// Запуск на production-сборке (так видит владелец, без индикатора Next dev):
//   npm run build && MOCK_INVITES=1 MOCK_FORCE=1 SESSION_SECRET=dev-secret PORT=3111 npm run start, затем SESSION_SECRET=dev-secret node scripts/shots.js
// Сессии подписываются тем же SESSION_SECRET (dev_user в production выключен).
/* eslint-disable @typescript-eslint/no-require-imports */
const { chromium } = require('playwright');
const { createHmac } = require('crypto');
const SECRET = process.env.SESSION_SECRET || 'dev-secret';
const session = (uid) => { const exp = Math.floor(Date.now() / 1000) + 3600; const body = `${uid}.${exp}`; return `${body}.${createHmac('sha256', SECRET).update(body).digest('base64url')}`; };
const OUT = require('path').join(__dirname, '..', 'shots');
const BASE = 'http://localhost:3111';
const PAGES = [['feed', '/digest', 1001], ['feed-week-biz', '/digest?day=week&seg=business', 1001], ['plan', '/plan', 1001], ['profile', '/profile', 1001], ['onb-welcome', '/profile?onboarding=welcome', 7001], ['onb-step1', '/profile?onboarding=1', 1002], ['onb-step2', '/profile?onboarding=2', 1002], ['invite', '/e/karmannyj-ongon?inv=MOCKOK01', 2002], ['event', '/e/f-vecher-dzhaz', 1001]];
const login = (ctx, uid) => ctx.addCookies([{ name: 'leisure_session', value: session(uid), url: BASE }]);
(async () => {
  const b = await chromium.launch();
  const report = [];
  for (const scheme of ['light', 'dark']) {
    const ctx = await b.newContext({ viewport: { width: 390, height: 844 }, deviceScaleFactor: 2, colorScheme: scheme, isMobile: true, hasTouch: true, locale: 'ru-RU' });
    const p = await ctx.newPage();
    const errs = [];
    p.on('console', (m) => { if (m.type() === 'error' || m.type() === 'warning') errs.push(m.text().slice(0, 160)); });
    p.on('pageerror', (e) => errs.push('PAGEERROR ' + e.message.slice(0, 160)));
    for (const [name, url, uid] of PAGES) {
      errs.length = 0;
      await login(ctx, uid);
      await p.goto(BASE + url, { waitUntil: 'networkidle' });
      await p.waitForTimeout(700);
      const m = await p.evaluate(() => ({ scrollW: document.documentElement.scrollWidth, innerW: window.innerWidth, devBadge: !!document.querySelector('nextjs-portal, [data-nextjs-dev-tools-button], #__next-build-watcher') }));
      report.push(`${scheme} ${name}: ${m.scrollW}/${m.innerW}${m.devBadge ? ' DEV-BADGE' : ''}${errs.length ? ' CONSOLE: ' + errs.join(' | ') : ''}`);
      await p.screenshot({ path: `${OUT}/${name}-${scheme}.png` });
      if (name === 'profile' || name === 'plan') await p.screenshot({ path: `${OUT}/${name}-${scheme}-full.png`, fullPage: true });
    }
    if (scheme === 'light') {
      await login(ctx, 1001);
      await p.goto(BASE + '/digest', { waitUntil: 'networkidle' });
      await p.waitForTimeout(400);
      // свайп-стамп: тянем карточку вправо и снимаем в середине жеста
      const card = await p.locator('.fcard:not(.behind)').boundingBox();
      await p.mouse.move(card.x + card.width / 2, card.y + card.height / 2);
      await p.mouse.down();
      await p.mouse.move(card.x + card.width / 2 + 60, card.y + card.height / 2, { steps: 6 });
      await p.screenshot({ path: `${OUT}/feed-drag-light.png` });
      await p.mouse.move(card.x + card.width / 2, card.y + card.height / 2, { steps: 4 });
      await p.mouse.up();
      await p.waitForTimeout(300);
      await p.getByRole('button', { name: 'Иду' }).first().click();
      await p.waitForTimeout(700);
      await p.screenshot({ path: `${OUT}/feed-inplan-light.png` });
      await p.keyboard.press('Escape');
      await p.waitForTimeout(300);
      await p.screenshot({ path: `${OUT}/feed-toast-light.png` });
      await p.goto(BASE + '/plan', { waitUntil: 'networkidle' });
      await p.getByRole('button', { name: 'Сходил' }).first().click();
      await p.waitForTimeout(500);
      await p.getByRole('button', { name: '5 звёзд' }).click();
      await p.waitForTimeout(600);
      await p.screenshot({ path: `${OUT}/plan-rated-light.png` });
      await p.goto(BASE + '/profile', { waitUntil: 'networkidle' });
      await p.getByRole('button', { name: /Профиль:/ }).click();
      await p.waitForTimeout(400);
      await p.screenshot({ path: `${OUT}/profile-switcher-light.png` });
    }
    await ctx.close();
  }
  await b.close();
  console.log(report.join('\n'));
})().catch((e) => { console.error(e); process.exit(1); });
