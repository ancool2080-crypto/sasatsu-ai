/* 査察AI — Service Worker
   自サイトの資材は Stale While Revalidate、フォントはキャッシュ優先、
   Claude API はネットワークのみ（キャッシュしない）。
   法令JSONは初回アクセス時にキャッシュされ、以後オフラインで閲覧できる。 */

// data/ 配下を更新したらこの値を上げること（上げないと古いJSONが1回表示される）
const VERSION    = 'v6';
const CACHE_APP  = 'sasatsu-app-' + VERSION;
const CACHE_FONT = 'sasatsu-font-' + VERSION;

const CORE = [
  './',
  'index.html',
  'offline.html',
  'manifest.json',
  'data/laws_index.json',
  'data/yoto.json',
  'data/findings_map.json',
  'data/ordinances.json',
  'data/fdma.json',
  'data/boka_kanri.json',
  'data/enforcement.json',
  'data/setsubi.json'
];

self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(CACHE_APP)
      // 個別に失敗しても install 全体を落とさない
      .then((cache) => Promise.all(CORE.map((url) => cache.add(url).catch(() => null))))
      .then(() => self.skipWaiting())
  );
});

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys()
      .then((keys) => Promise.all(
        keys.filter((k) => k !== CACHE_APP && k !== CACHE_FONT).map((k) => caches.delete(k))
      ))
      .then(() => self.clients.claim())
  );
});

self.addEventListener('fetch', (event) => {
  const req = event.request;
  if (req.method !== 'GET') return;

  const url = new URL(req.url);

  // Claude API：キャッシュせず、オフライン時は分かるように返す
  if (url.hostname === 'api.anthropic.com') {
    event.respondWith(
      fetch(req).catch(() => new Response(
        JSON.stringify({ error: { message: 'オフラインのためAI解説は利用できません。検索と条文表示はそのまま使えます。' } }),
        { status: 503, headers: { 'Content-Type': 'application/json' } }
      ))
    );
    return;
  }

  // Google Fonts：キャッシュ優先
  if (url.hostname === 'fonts.googleapis.com' || url.hostname === 'fonts.gstatic.com') {
    event.respondWith(
      caches.open(CACHE_FONT).then((cache) =>
        cache.match(req).then((hit) => hit || fetch(req).then((res) => {
          if (res.ok) cache.put(req, res.clone());
          return res;
        }).catch(() => hit))
      )
    );
    return;
  }

  // Firebase SDK など他のオリジンは素通し
  if (url.origin !== self.location.origin) return;

  // アプリ本体（ナビゲーション）はネットワーク優先。
  // キャッシュ優先にすると更新後も一度は古い版が表示されてしまうため。
  if (req.mode === 'navigate') {
    event.respondWith(
      fetch(req)
        .then((res) => {
          if (res.ok) {
            const copy = res.clone();
            event.waitUntil(caches.open(CACHE_APP).then((c) => c.put(req, copy)));
          }
          return res;
        })
        .catch(() => caches.match(req).then((hit) => hit || caches.match('offline.html')))
    );
    return;
  }

  // その他の自サイト資材：Stale While Revalidate
  event.respondWith(
    caches.open(CACHE_APP).then((cache) =>
      cache.match(req).then((hit) => {
        const net = fetch(req).then((res) => {
          if (res.ok) cache.put(req, res.clone());
          return res;
        }).catch(() => null);

        if (hit) { event.waitUntil(net); return hit; }

        return net.then((res) => {
          if (res) return res;
          if (req.mode === 'navigate') return cache.match('offline.html');
          return new Response('', { status: 504, statusText: 'offline' });
        });
      })
    )
  );
});
