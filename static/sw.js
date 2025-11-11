// Simple service worker: precache core assets and provide cache-first responses.

const CACHE_NAME = 'webstore-v1';
const PRECACHE_URLS = [
  '/',
  '/products',
  '/static/css/styles.css',
  '/static/images/logo.png',
  '/static/images/logo-192.png',
  '/static/images/logo-512.png',
  '/static/manifest.json'
];

self.addEventListener('install', event => {
  self.skipWaiting();
  event.waitUntil(
    caches.open(CACHE_NAME).then(cache => cache.addAll(PRECACHE_URLS))
  );
});

self.addEventListener('activate', event => {
  event.waitUntil(
    caches.keys().then(keys =>
      Promise.all(keys.filter(k => k !== CACHE_NAME).map(k => caches.delete(k)))
    )
  );
  self.clients.claim();
});

self.addEventListener('fetch', event => {
  const req = event.request;

  // Always try network first for POST / API requests
  if (req.method !== 'GET') {
    return;
  }

  // For navigation requests (page loads) try network first then fallback to cache
  if (req.mode === 'navigate') {
    event.respondWith(
      fetch(req).then(res => {
        caches.open(CACHE_NAME).then(cache => cache.put(req, res.clone()));
        return res;
      }).catch(() => caches.match('/'))
    );
    return;
  }

  // For other GET requests (static assets) use cache-first
  event.respondWith(
    caches.match(req).then(cached => {
      if (cached) return cached;
      return fetch(req).then(fetchRes => {
        // cache fetched response for future
        caches.open(CACHE_NAME).then(cache => {
          // ignore opaque responses from cross-origin (e.g. CDN)
          if (fetchRes && fetchRes.type === 'basic') {
            cache.put(req, fetchRes.clone());
          }
        });
        return fetchRes;
      }).catch(() => {
        // optional fallback for images
        if (req.destination === 'image') {
          return caches.match('/static/images/logo-192.png');
        }
        return new Response('Offline', { status: 503, statusText: 'Offline' });
      });
    })
  );
});