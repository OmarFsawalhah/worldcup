// WC2026 service worker — minimal shell cache.
// Phase 1: install only. Phase 2 will add a push event handler if we ever
// move off Telegram and use Web Push.
//
// Caching strategy: network-first for HTML (so updates show up immediately),
// cache-first for static assets (icons, css, js, fonts).
//
// Versioning: bump CACHE_NAME any time we want to force users to re-download
// cached assets. Old caches are cleaned in the activate event.

const CACHE_NAME = 'wc2026-shell-v2';
const STATIC_ASSETS = [
  '/static/app.css',
  '/static/countdown.js',
  '/static/icons/icon-192.png',
  '/static/icons/icon-512.png',
  '/static/icons/icon-maskable.png',
];

self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(CACHE_NAME).then((cache) => cache.addAll(STATIC_ASSETS)).catch(() => null)
  );
  self.skipWaiting();
});

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(keys.filter((k) => k !== CACHE_NAME).map((k) => caches.delete(k)))
    )
  );
  self.clients.claim();
});

// ============ Web Push ============
self.addEventListener('push', (event) => {
  let data = {};
  if (event.data) {
    try { data = event.data.json(); } catch (e) { data = { title: 'WC2026', body: event.data.text() }; }
  }
  const title = data.title || 'WC2026';
  const options = {
    body: data.body || '',
    icon: '/static/icons/icon-192.png',
    badge: '/static/icons/icon-192.png',
    vibrate: [120, 60, 120],
    data: { url: data.url || '/' },
    tag: data.tag || undefined,        // tag collapses duplicate notifications
    renotify: !!data.tag,
  };
  event.waitUntil(self.registration.showNotification(title, options));
});

self.addEventListener('notificationclick', (event) => {
  event.notification.close();
  const url = (event.notification.data && event.notification.data.url) || '/';
  event.waitUntil(
    self.clients.matchAll({ type: 'window', includeUncontrolled: true }).then((wins) => {
      // If the app is already open in any window, focus it and navigate
      for (const w of wins) {
        if ('focus' in w) {
          w.navigate ? w.navigate(url) : w.postMessage({ type: 'nav', url });
          return w.focus();
        }
      }
      // Otherwise open a new window
      return self.clients.openWindow(url);
    })
  );
});

self.addEventListener('fetch', (event) => {
  const req = event.request;
  // Only handle GET
  if (req.method !== 'GET') return;
  const url = new URL(req.url);
  // Never cache cross-origin (CDN) — let the browser handle them
  if (url.origin !== self.location.origin) return;

  // HTML pages: network first, fallback to cache (so users get fresh content
  // when online, still see something when offline)
  if (req.headers.get('accept') && req.headers.get('accept').includes('text/html')) {
    event.respondWith(
      fetch(req).catch(() => caches.match(req).then((r) => r || caches.match('/')))
    );
    return;
  }

  // Static assets: cache first, fall back to network
  if (url.pathname.startsWith('/static/')) {
    event.respondWith(
      caches.match(req).then((cached) => cached || fetch(req).then((res) => {
        if (res.ok) {
          const clone = res.clone();
          caches.open(CACHE_NAME).then((c) => c.put(req, clone));
        }
        return res;
      }))
    );
  }
});
