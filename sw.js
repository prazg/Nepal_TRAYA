/**
 * Nepal TRĀYA (त्राय) — Offline-First Same-Origin Service Worker (TRAYA-008)
 *
 * Security & Caching Guarantees:
 * - Strictly intercepts ONLY same-origin GET requests (NEVER intercepts
 *   cross-origin map tiles, NASA GIBS WMTS, USGS, Open-Meteo, STAC, or GDACS).
 * - Pre-caches the static PWA shell for instant offline launch.
 * - Uses stale-while-revalidate for ./data/* and ./schemas/* payloads.
 * - Uses cache-first for static shell assets with offline navigation fallback.
 * - Cleans up obsolete cache versions atomically on activate.
 */

const CACHE_NAME = 'traya-v2-shell-1';
const DATA_CACHE = 'traya-v2-data-1';
const ACTIVE_CACHES = new Set([CACHE_NAME, DATA_CACHE]);

const SHELL_ASSETS = [
  './',
  './index.html',
  './manifest.webmanifest',
  './assets/style.css',
  './assets/app.js',
  './assets/i18n.js',
  './assets/pwa_reports.js',
  './assets/icon-traya.svg',
  './vendor/leaflet/leaflet.css',
  './vendor/leaflet/leaflet.js',
];

function getScopeRelativePath(url) {
  try {
    const scopePath = new URL(self.registration.scope).pathname;
    if (url.pathname.startsWith(scopePath)) {
      return url.pathname.slice(scopePath.length);
    }
  } catch {
    // Fallback below if scope URL is unavailable
  }
  return url.pathname.replace(/^\/+/, '');
}

function isCacheableBasicResponse(resp) {
  return Boolean(resp && resp.ok && resp.type === 'basic');
}

self.addEventListener('install', event => {
  event.waitUntil(
    (async () => {
      const cache = await caches.open(CACHE_NAME);
      try {
        await cache.addAll(SHELL_ASSETS);
      } catch {
        // Resilient per-asset caching so a single transient error never aborts install
        await Promise.all(
          SHELL_ASSETS.map(async asset => {
            try {
              await cache.add(asset);
            } catch {
              // Ignore individual pre-cache failure; asset will populate on demand
            }
          })
        );
      }
      await self.skipWaiting();
    })()
  );
});

self.addEventListener('activate', event => {
  event.waitUntil(
    (async () => {
      const keys = await caches.keys();
      await Promise.all(
        keys
          .filter(key => !ACTIVE_CACHES.has(key))
          .map(key => caches.delete(key))
      );
      await self.clients.claim();
    })()
  );
});

self.addEventListener('message', event => {
  if (event.data && event.data.type === 'SKIP_WAITING') {
    self.skipWaiting();
  }
});

async function staleWhileRevalidate(request, event) {
  const cache = await caches.open(DATA_CACHE);
  const cached = await cache.match(request);

  const networkUpdate = fetch(request)
    .then(async response => {
      if (isCacheableBasicResponse(response)) {
        try {
          await cache.put(request, response.clone());
        } catch {
          // Ignore quota errors
        }
      }
      return response;
    })
    .catch(() => null);

  if (cached) {
    event.waitUntil(networkUpdate);
    return cached;
  }

  const fresh = await networkUpdate;
  if (fresh) return fresh;

  return new Response(
    JSON.stringify({
      offline: true,
      error: 'Requested dataset is not cached for offline use yet.',
    }),
    {
      status: 503,
      statusText: 'Service Unavailable',
      headers: { 'Content-Type': 'application/json; charset=utf-8' },
    }
  );
}

async function cacheFirstShell(request) {
  const cache = await caches.open(CACHE_NAME);
  const cached = await cache.match(request);
  if (cached) return cached;

  try {
    const response = await fetch(request);
    if (isCacheableBasicResponse(response)) {
      try {
        await cache.put(request, response.clone());
      } catch {
        // Ignore quota errors
      }
    }
    return response;
  } catch {
    if (request.mode === 'navigate') {
      const fallback = (await cache.match('./index.html')) || (await cache.match('./'));
      if (fallback) return fallback;
    }
    return new Response('Offline — cached shell asset unavailable.', {
      status: 503,
      statusText: 'Service Unavailable',
      headers: { 'Content-Type': 'text/plain; charset=utf-8' },
    });
  }
}

self.addEventListener('fetch', event => {
  const { request } = event;
  if (request.method !== 'GET') return;

  let url;
  try {
    url = new URL(request.url);
  } catch {
    return;
  }

  // Strictly intercept ONLY same-origin HTTP(S) GET requests.
  // Never touch cross-origin map tiles, NASA GIBS, USGS, Open-Meteo, STAC, or GDACS.
  if (url.protocol !== 'http:' && url.protocol !== 'https:') return;
  if (url.origin !== self.location.origin) return;

  const relPath = getScopeRelativePath(url);
  if (relPath.startsWith('data/') || relPath.startsWith('schemas/')) {
    event.respondWith(staleWhileRevalidate(request, event));
    return;
  }

  event.respondWith(cacheFirstShell(request));
});
