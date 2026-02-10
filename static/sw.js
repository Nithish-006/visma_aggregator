const CACHE_NAME = 'visma-v3';

const PRECACHE_ASSETS = [
  '/static/logo.png',
  '/static/hub.css',
  '/static/hub.js',
  '/static/style.css',
  '/static/dashboard.js',
  '/static/edit_transactions.css',
  '/static/edit_transactions.js',
  '/static/charts.js',
  '/static/personal_tracker.css',
  '/static/personal_tracker.js',
  '/static/expense_form.css',
  '/static/expense_form.js',
  '/static/bill_processor.css',
  '/static/bill_processor.js',
  '/static/edit.js',
  '/static/upload.js'
];

// Install: pre-cache core static assets
self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(CACHE_NAME)
      .then((cache) => cache.addAll(PRECACHE_ASSETS))
      .then(() => self.skipWaiting())
  );
});

// Activate: clean old caches
self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys()
      .then((keys) => Promise.all(
        keys.filter((key) => key !== CACHE_NAME)
            .map((key) => caches.delete(key))
      ))
      .then(() => self.clients.claim())
  );
});

// Fetch: cache-first for static assets, network-first for everything else
self.addEventListener('fetch', (event) => {
  const url = new URL(event.request.url);

  // Cache-first for static assets
  if (url.pathname.startsWith('/static/')) {
    event.respondWith(
      caches.match(event.request).then((cached) => {
        return cached || fetch(event.request).then((response) => {
          const clone = response.clone();
          caches.open(CACHE_NAME).then((cache) => cache.put(event.request, clone));
          return response;
        });
      })
    );
    return;
  }

  // Network-first for API calls and HTML pages
  event.respondWith(
    fetch(event.request)
      .then((response) => {
        // Cache successful GET responses for offline fallback
        if (event.request.method === 'GET' && response.status === 200) {
          const clone = response.clone();
          caches.open(CACHE_NAME).then((cache) => cache.put(event.request, clone));
        }
        return response;
      })
      .catch(() => caches.match(event.request))
  );
});
