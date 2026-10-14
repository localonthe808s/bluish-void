/* BLUISH push service worker (2026-10-13). It does ONE thing: show the alerts the Kalshi worker pushes, and open the
   site when one is tapped. No fetch handler on purpose -- the site's loading and caching are untouched. */
self.addEventListener('install', function(){ self.skipWaiting(); });
self.addEventListener('activate', function(e){ e.waitUntil(self.clients.claim()); });

self.addEventListener('push', function(e){
  var m = {};
  try { m = e.data ? e.data.json() : {}; } catch (_){ m = { body: e.data ? e.data.text() : '' }; }
  e.waitUntil(self.registration.showNotification(m.title || 'BLUISH', {
    body: m.body || '',
    tag: m.tag || undefined,            /* the same alert updating replaces itself rather than stacking */
    icon: '/icons/icon-192.png',
    badge: '/icons/icon-192.png',
    data: { url: m.url || '/' },
    timestamp: Date.now()
  }));
});

self.addEventListener('notificationclick', function(e){
  e.notification.close();
  var url = (e.notification.data && e.notification.data.url) || '/';
  e.waitUntil(self.clients.matchAll({ type: 'window', includeUncontrolled: true }).then(function(list){
    for (var i = 0; i < list.length; i++){ if ('focus' in list[i]){ var go = (url.split('#go=')[1] || ''); try { list[i].postMessage({ bvGo: go }); } catch (_){} return list[i].focus(); } }   /* an open BLUISH comes forward and goes to the alert's view */
    return self.clients.openWindow(url);
  }));
});
