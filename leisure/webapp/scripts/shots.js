// Скриншоты экранов для проверки вёрстки: 390 × 844, обе темы, консоль и горизонтальный скролл. Нужен Playwright (require('playwright')).
// Данные: мок (MOCK_INVITES=1 MOCK_FORCE=1 у сервера веба) или настоящий API (E2E_API=http://localhost:8000: скрипт сам создаёт профили и приглашение через API).
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
const API = process.env.E2E_API || '';
const api = async (path, init = {}) => {
  const r = await fetch(API + path, { ...init, headers: { 'Content-Type': 'application/json', ...(process.env.API_KEY ? { 'X-API-Key': process.env.API_KEY } : {}) } });
  return r.json().catch(() => null);
};
/** Настоящий API: готовый профиль с «иду» и вчерашним событием, черновик для шагов 1/2, новый гость, приглашение. */
async function setup() {
  if (!API) return { main: 1001, draft: 1002, fresh: 7001, guest: 2002, invite: '/e/karmannyj-ongon?inv=MOCKOK01', event: '/e/f-vecher-dzhaz', cleanup: async () => {} };
  const newUid = async () => (await api('/api/session', { method: 'POST' })).user_id;
  const main = await newUid(), draft = await newUid(), fresh = await newUid(), guest = await newUid();
  const top = (names) => Object.fromEntries(['Творчество', 'Наставничество', 'Забота', 'Единство/Дружба', 'Развитие', 'Красота/эстетика', 'Инновации/новизна', 'Свобода', 'Семья', 'Исследования', 'Здоровье', 'Сохранение традиций', 'Природа', 'Удовольствие', 'Веселье', 'Азарт', 'Покой', 'Близость', 'Смысл'].map((v) => [v, names.includes(v) ? 5 : 2]));
  await api(`/api/profile/${main}`, { method: 'PUT', body: JSON.stringify({ consent: true, name: 'Мария', values: top(['Творчество', 'Красота/эстетика', 'Инновации/новизна', 'Исследования', 'Смысл']), interests: { 'Театр': 3, 'Джаз': 3, 'Современное искусство': 3, 'Кино': 2 }, params: { budget: 2500, travel_minutes: 40 }, onboarded: true }) });
  await api(`/api/profile/${draft}`, { method: 'PUT', body: JSON.stringify({ consent: true, name: 'Игорь', values: top(['Природа', 'Здоровье', 'Семья', 'Покой', 'Сохранение традиций']) }) });
  const feed = await api(`/api/feed?user_id=${main}&date=today&segment=leisure`);
  const first = feed.items[0];
  await api('/api/decisions', { method: 'POST', body: JSON.stringify({ user_id: main, event: first.event.slug, status: 'иду', day: first.day }) });
  const yday = new Date(Date.parse(feed.today) - 86400_000).toISOString().slice(0, 10);
  // прошедшее для «Сходил»: не то же событие, что «иду» сегодня, и не идущее сегодня (одно решение на событие)
  const past = (await api(`/api/feed?user_id=${main}&date=${yday}&today=${yday}&segment=all`)).items?.find((i) => i.event.slug !== first.event.slug && !i.event.dates.includes(feed.today));
  if (past) await api('/api/decisions', { method: 'POST', body: JSON.stringify({ user_id: main, event: past.event.slug, status: 'иду', day: yday }) });
  const planCheck = await api(`/api/plan/${main}`);
  console.log('setup: main', main, 'first', first.event.slug, 'past', past?.event?.slug, 'plan.past', planCheck?.past?.length);
  const inv = await api('/api/invites', { method: 'POST', body: JSON.stringify({ user_id: main, event_slug: first.event.slug, day: first.day }) });
  const invite = inv.web_url.replace(/^https?:\/\/[^/]+/, '');
  return { main, draft, fresh, guest, invite, event: `/e/${first.event.slug}`, cleanup: async () => { for (const u of [main, draft, fresh, guest]) await api(`/api/profile/${u}`, { method: 'DELETE' }); } };
}
const PAGES_OF = (u) => [['feed', '/digest', u.main], ['feed-week-biz', '/digest?day=week&seg=business', u.main], ['plan', '/plan', u.main], ['profile', '/profile', u.main], ['onb-welcome', '/profile?onboarding=welcome', u.fresh], ['onb-step1', '/profile?onboarding=1', u.draft], ['onb-step2', '/profile?onboarding=2', u.draft], ['invite', u.invite, u.guest], ['event', u.event, u.main]];
const login = (ctx, uid) => ctx.addCookies([{ name: 'leisure_session', value: session(uid), url: BASE }]);
(async () => {
  const u = await setup();
  const PAGES = PAGES_OF(u);
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
      await login(ctx, u.main);
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
  await u.cleanup();
  console.log(report.join('\n'));
})().catch((e) => { console.error(e); process.exit(1); });
