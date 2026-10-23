"use strict";
// The browser requests only the same-origin, policy-checked raster endpoint.
document.addEventListener("error", event => {
  if (event.target.matches?.("img[data-news-thumbnail]")) event.target.hidden = true;
}, true);
