// WC2026 service worker — minimal shell cache.
// Phase 1: install only. Phase 2 will add a push event handler if we ever
// move off Telegram and use Web Push.
//
// Caching strategy: network-first for HTML (so updates show up immediately),
// cache-first for static assets (icons, css, js, fonts).
//
// Versioning: bump CACHE_NAME any time we want to force users to re-download
// cached assets. Old caches are cleaned in the activate event.

const CACHE_NAME = 'wc2026-shell-v1';
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
