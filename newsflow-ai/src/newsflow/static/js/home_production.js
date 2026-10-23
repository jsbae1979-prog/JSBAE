"use strict";
// Presentation only. The server revalidates the saved engines and all existing gates.
const newsChoice = document.getElementById("quick-source");
const actualAi = document.querySelector("[data-home-ai]");
const trialNotice = document.querySelector("[data-trial-notice]");
const acquisitionChoice = document.querySelector('[name="acquisition_policy"]');
const acquisitionLabel = document.querySelector("[data-home-acquisition]");
const policyWarning = document.querySelector("[data-home-policy-warning]");
const policyStatesNode = document.querySelector("[data-home-policy-states]");
const policyStates = policyStatesNode ? JSON.parse(policyStatesNode.dataset.homePolicyStates) : {};
function refreshPolicyReadiness() {
  const state = acquisitionChoice && policyStates[acquisitionChoice.value];
  if (!state) return;
  for (const key of ["title", "detail", "notice"]) {
    const node = document.querySelector(`[data-home-policy-${key}]`);
    if (node) node.textContent = state[key];
  }
  const dot = document.querySelector("[data-home-policy-dot]");
  if (dot) {
    const checked = state.supported && state.auth_checked === true;
    dot.classList.toggle("ready", checked);
    dot.classList.toggle("pending", !checked);
  }
}
function refreshPolicyWarning() {
  if (policyWarning && acquisitionChoice && newsChoice) {
    policyWarning.hidden = newsChoice.value === "sample" || acquisitionChoice.value === "rss" || policyStates[acquisitionChoice.value]?.supported === true;
  }
}
if (acquisitionChoice && acquisitionLabel) {
  acquisitionChoice.addEventListener("change", () => {
    acquisitionLabel.textContent = acquisitionChoice.options[acquisitionChoice.selectedIndex].text;
    refreshPolicyWarning();
    refreshPolicyReadiness();
  });
}
if (newsChoice && actualAi && trialNotice) {
  newsChoice.addEventListener("change", () => {
    const trial = newsChoice.value === "sample";
    actualAi.textContent = trial ? "Offline · 체험용" : actualAi.dataset.selectedAi;
    trialNotice.hidden = !trial;
    document.querySelectorAll("[data-source-mode]").forEach(node => {
      node.hidden = node.dataset.sourceMode !== newsChoice.value;
    });
    refreshPolicyWarning();
    refreshPolicyReadiness();
  });
}

// A selection only reveals the existing approval requirements; it grants no consent.
for (const [id, target, external] of [
  ["quick-voice-method", "[data-external-voice-note]", "elevenlabs"],
  ["quick-video-method", "[data-external-video-note]", "higgsfield"]
]) {
  const select = document.getElementById(id);
  const note = document.querySelector(target);
  if (select && note) {
    const update = () => { note.hidden = select.value !== external; };
    select.addEventListener("change", update);
    update();
  }
}
