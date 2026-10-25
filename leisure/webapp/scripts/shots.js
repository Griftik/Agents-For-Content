// Скриншоты экранов для проверки вёрстки: 390 × 844, обе темы, консоль и горизонтальный скролл. Нужен Playwright (require('playwright')).
// Запуск: MOCK_INVITES=1 SESSION_SECRET=dev npx next dev -p 3111, затем node scripts/shots.js
/* eslint-disable @typescript-eslint/no-require-imports */
const { chromium } = require('playwright');
const OUT = require('path').join(__dirname, '..', 'shots');
const BASE = 'http://localhost:3111';
const PAGES = [['feed', '/digest?dev_user=1001'], ['feed-week-biz', '/digest?day=week&seg=business&dev_user=1001'], ['plan', '/plan?dev_user=1001'], ['profile', '/profile?dev_user=1001'], ['onb-welcome', '/profile?onboarding=welcome&dev_user=7001'], ['onb-step1', '/profile?onboarding=1&dev_user=1002'], ['onb-step2', '/profile?onboarding=2&dev_user=1002'], ['invite', '/e/karmannyj-ongon?inv=MOCKOK01&dev_user=2002'], ['event', '/e/f-vecher-dzhaz?dev_user=1001']];
(async () => {
  const b = await chromium.launch();
  const report = [];
  for (const scheme of ['light', 'dark']) {
    const ctx = await b.newContext({ viewport: { width: 390, height: 844 }, deviceScaleFactor: 2, colorScheme: scheme, isMobile: true, hasTouch: true, locale: 'ru-RU' });
    const p = await ctx.newPage();
    const errs = [];
    p.on('console', (m) => { if (m.type() === 'error' || m.type() === 'warning') errs.push(m.text().slice(0, 160)); });
    p.on('pageerror', (e) => errs.push('PAGEERROR ' + e.message.slice(0, 160)));
    for (const [name, url] of PAGES) {
      errs.length = 0;
      await p.goto(BASE + url, { waitUntil: 'networkidle' });
      await p.waitForTimeout(700);
      const m = await p.evaluate(() => ({ scrollW: document.documentElement.scrollWidth, innerW: window.innerWidth }));
      report.push(`${scheme} ${name}: ${m.scrollW}/${m.innerW}${errs.length ? ' CONSOLE: ' + errs.join(' | ') : ''}`);
      await p.screenshot({ path: `${OUT}/${name}-${scheme}.png` });
      if (name === 'profile' || name === 'plan') await p.screenshot({ path: `${OUT}/${name}-${scheme}-full.png`, fullPage: true });
    }
    if (scheme === 'light') {
      await p.goto(BASE + '/digest?dev_user=1001', { waitUntil: 'networkidle' });
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
      await p.goto(BASE + '/plan?dev_user=1001', { waitUntil: 'networkidle' });
      await p.getByRole('button', { name: 'Сходил' }).first().click();
      await p.waitForTimeout(500);
      await p.getByRole('button', { name: '5 звёзд' }).click();
      await p.waitForTimeout(600);
      await p.screenshot({ path: `${OUT}/plan-rated-light.png` });
      await p.goto(BASE + '/profile?dev_user=1001', { waitUntil: 'networkidle' });
      await p.getByRole('button', { name: /Профиль:/ }).click();
      await p.waitForTimeout(400);
      await p.screenshot({ path: `${OUT}/profile-switcher-light.png` });
    }
    await ctx.close();
  }
  await b.close();
  console.log(report.join('\n'));
})().catch((e) => { console.error(e); process.exit(1); });
