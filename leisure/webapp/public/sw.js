// Service worker приложения Catch: только офлайн-заглушка (push и уведомления из MVP сняты, docs/PIVOT-PWA.md, версия 2).
// Данные пользователя здесь не кэшируются: подборка и план всегда с сервера.
const CACHE = "leisure-shell-v2";
const OFFLINE_URL = "/offline.html";
const ICON = "/icons/icon-192.png";

self.addEventListener("install", (event) => {
  // шрифты кэшируются вместе с заглушкой: офлайн-экран набран теми же шрифтами, что приложение
  const FONTS = ["/fonts/fonts.css", "Piazzolla-800-cyrillic", "Piazzolla-800-latin", "GolosText-400-cyrillic", "GolosText-400-latin", "GolosText-500-cyrillic", "GolosText-500-latin", "GolosText-600-cyrillic", "GolosText-600-latin", "IBMPlexMono-500-cyrillic", "IBMPlexMono-500-latin"]
    .map((f) => (f.startsWith("/") ? f : `/fonts/${f}.woff2`));
  event.waitUntil(caches.open(CACHE).then((c) => c.addAll([OFFLINE_URL, ICON, ...FONTS])).then(() => self.skipWaiting()));
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys().then((keys) => Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k)))).then(() => self.clients.claim()),
  );
});

// Переходы по страницам: сеть; если её нет — заглушка. Остальное (API, картинки, скрипты) браузер берёт сам.
self.addEventListener("fetch", (event) => {
  const req = event.request;
  const url = new URL(req.url);
  if (url.origin === self.location.origin && url.pathname.startsWith("/fonts/")) {
    event.respondWith(caches.match(req).then((hit) => hit ?? fetch(req)));
    return;
  }
  if (req.mode !== "navigate") return;
  event.respondWith(fetch(req).catch(() => caches.match(OFFLINE_URL)));
});
