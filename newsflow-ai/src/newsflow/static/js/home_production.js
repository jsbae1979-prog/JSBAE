"use strict";
// Presentation only. The server revalidates the saved engines and all existing gates.
const newsChoice = document.getElementById("quick-source");
const actualAi = document.querySelector("[data-home-ai]");
const trialNotice = document.querySelector("[data-trial-notice]");
if (newsChoice && actualAi && trialNotice) {
  newsChoice.addEventListener("change", () => {
    const trial = newsChoice.value === "sample";
    actualAi.textContent = trial ? "Offline · 체험용" : actualAi.dataset.selectedAi;
    trialNotice.hidden = !trial;
    document.querySelectorAll("[data-source-mode]").forEach(node => {
      node.hidden = node.dataset.sourceMode !== newsChoice.value;
    });
  });
}
