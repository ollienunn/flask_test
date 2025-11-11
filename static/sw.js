// Simple SW: precache core assets and provide runtime caching + offline fallback
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

self.addEventListener('install', (event) => {
  self.skipWaiting();
  event.waitUntil(
    caches.open(CACHE_NAME).then(cache => cache.addAll(PRECACHE_URLS))
  );
});

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys().then(keys =>
      Promise.all(keys.filter(k => k !== CACHE_NAME).map(k => caches.delete(k)))
    )
  );
  self.clients.claim();
});

self.addEventListener('fetch', (event) => {
  const req = event.request;

  // Don't cache non-GET requests
  if (req.method !== 'GET') return;

  // Navigation: try network then fallback to cache (so fresh pages online)
  if (req.mode === 'navigate') {
    event.respondWith(
      fetch(req).then(res => {
        caches.open(CACHE_NAME).then(cache => cache.put(req, res.clone()));
        return res;
      }).catch(() => caches.match('/'))
    );
    return;
  }

  // For other GET requests use cache-first then network
  event.respondWith(
    caches.match(req).then(cached => {
      if (cached) return cached;
      return fetch(req).then(networkRes => {
        // cache same-origin basic responses
        if (networkRes && networkRes.type === 'basic') {
          caches.open(CACHE_NAME).then(cache => cache.put(req, networkRes.clone()));
        }
        return networkRes;
      }).catch(() => {
        // image fallback
        if (req.destination === 'image') {
          return caches.match('/static/images/logo-192.png');
        }
        return new Response('Offline', { status: 503, statusText: 'Offline' });
      });
    })
  );
});