"use strict";
document.querySelectorAll("[data-youtube-client]").forEach((form) => {
  const input = form.querySelector("[data-youtube-file]");
  const field = form.querySelector("[data-youtube-json]");
  const error = form.querySelector("[data-youtube-error]");
  input.addEventListener("change", async () => {
    field.value = "";
    error.textContent = "";
    const file = input.files[0];
    if (!file || file.size > 16384) {
      error.textContent = "16KB 이하의 Google 데스크톱 앱 JSON을 선택하세요.";
      return;
    }
    try {
      const raw = await file.text();
      if (file !== input.files[0]) return;
      const parsed = JSON.parse(raw);
      if (!parsed.installed || !parsed.installed.client_id) throw new Error("invalid");
      field.value = raw;
    } catch {
      error.textContent = "Google 데스크톱 앱 JSON 형식을 확인하세요.";
    }
  });
  form.addEventListener("submit", (event) => {
    if (!field.value) {
      event.preventDefault();
      error.textContent = "Google 데스크톱 앱 JSON을 먼저 선택하세요.";
    }
  }, {capture: true});
});
