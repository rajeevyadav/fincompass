"use strict";
const SHELL = "fincompass-shell-v1";
const ASSETS = ["/", "/static/app.css", "/static/app.js", "/static/cloud_auth.css", "/static/cloud_auth.js"];
self.addEventListener("install", (event) => event.waitUntil(caches.open(SHELL).then((c) => c.addAll(ASSETS)).catch(() => {})));
self.addEventListener("activate", (event) => event.waitUntil(self.clients.claim()));
self.addEventListener("fetch", (event) => {
  const url = new URL(event.request.url);
  if (event.request.method !== "GET" || url.pathname.startsWith("/api/")) return;
  event.respondWith(fetch(event.request).catch(() => caches.match(event.request)));
});
