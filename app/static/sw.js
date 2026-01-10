self.addEventListener("install", (event) => {
  event.waitUntil(self.skipWaiting());
});

self.addEventListener("activate", (event) => {
  event.waitUntil(self.clients.claim());
});

self.addEventListener("push", (event) => {
  let payload = {};
  if (event.data) {
    try {
      payload = event.data.json();
    } catch (err) {
      payload = { message: event.data.text() };
    }
  }
  const title = payload.title || "KittyLog";
  const options = {
    body: payload.message || "",
    data: { url: payload.url || "/" },
    icon: "/static/favicon.svg",
    badge: "/static/favicon.svg",
  };
  event.waitUntil(self.registration.showNotification(title, options));
});

self.addEventListener("notificationclick", (event) => {
  const targetUrl = (event.notification.data && event.notification.data.url) || "/";
  event.notification.close();
  event.waitUntil(
    self.clients.matchAll({ type: "window", includeUncontrolled: true }).then((clientsArr) => {
      for (const client of clientsArr) {
        if (client.url.includes(targetUrl)) {
          return client.focus();
        }
      }
      return self.clients.openWindow(targetUrl);
    })
  );
});
