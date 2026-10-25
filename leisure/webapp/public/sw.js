// Service worker приложения «Досуг»: только офлайн-заглушка (push и уведомления из MVP сняты, docs/PIVOT-PWA.md, версия 2).
// Данные пользователя здесь не кэшируются: подборка и план всегда с сервера.
const CACHE = "leisure-shell-v1";
const OFFLINE_URL = "/offline.html";
const ICON = "/icons/icon-192.png";

self.addEventListener("install", (event) => {
  event.waitUntil(caches.open(CACHE).then((c) => c.addAll([OFFLINE_URL, ICON])).then(() => self.skipWaiting()));
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys().then((keys) => Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k)))).then(() => self.clients.claim()),
  );
});

// Переходы по страницам: сеть; если её нет — заглушка. Остальное (API, картинки, скрипты) браузер берёт сам.
self.addEventListener("fetch", (event) => {
  const req = event.request;
  if (req.mode !== "navigate") return;
  event.respondWith(fetch(req).catch(() => caches.match(OFFLINE_URL)));
});
