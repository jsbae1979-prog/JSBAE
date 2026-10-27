"use strict";
// The browser requests only the same-origin, policy-checked raster endpoint.
document.addEventListener("error", event => {
  if (event.target.matches?.("img[data-news-thumbnail]")) event.target.hidden = true;
}, true);
// A cached failure can precede this deferred script's error listener.
document.querySelectorAll("img[data-news-thumbnail]").forEach(image => {
  if (image.complete && image.naturalWidth === 0) image.hidden = true;
});
