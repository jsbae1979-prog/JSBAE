"use strict";
document.querySelectorAll("[data-youtube-link-controls]").forEach((controls) => {
  const message = controls.querySelector("[data-youtube-link-message]");
  const fallback = controls.querySelector("[data-youtube-link-fallback]");
  const field = controls.querySelector("[data-youtube-link-value]");
  const buttons = controls.querySelectorAll("[data-youtube-link-action]");
  let clearTimer;
  const clearLink = () => {
    clearTimeout(clearTimer);
    field.value = "";
    fallback.hidden = true;
  };
  window.addEventListener("pagehide", clearLink);
  controls.closest("section").querySelectorAll("form").forEach((form) => {
    form.addEventListener("submit", clearLink);
  });
  buttons.forEach((button) => button.addEventListener("click", async () => {
    buttons.forEach((item) => { item.disabled = true; });
    clearLink();
    message.textContent = "처리 중…";
    try {
      const action = button.dataset.youtubeLinkAction;
      const response = await fetch(`/youtube/connect/${controls.dataset.accountId}/${action}`, {
        method: "POST", credentials: "same-origin", cache: "no-store",
        body: new URLSearchParams({csrf_token: controls.querySelector('[name="csrf_token"]').value})
      });
      if (!response.ok) {
        message.textContent = response.status === 403
          ? "보안 확인이 필요합니다. 화면을 새로고침하세요."
          : "인증 창을 열 수 없거나 링크가 만료되었습니다. 연결 상태를 새로고침하고, 대기 중이면 링크 복사를 이용하세요.";
        return;
      }
      const result = await response.json();
      if (action === "reopen") {
        message.textContent = "진행 중인 Google 인증 창을 다시 열었습니다.";
        return;
      }
      const url = new URL(result.url);
      if (url.origin !== "https://accounts.google.com" || url.pathname !== "/o/oauth2/v2/auth"
          || !Number.isFinite(result.expires_in) || result.expires_in <= 0) throw new Error("invalid");
      clearTimer = setTimeout(() => {
        clearLink();
        message.textContent = "인증 링크가 만료되었습니다. 연결 상태를 새로고침하세요.";
      }, Math.min(result.expires_in, 300) * 1000);
      try {
        await navigator.clipboard.writeText(result.url);
        message.textContent = "복사했습니다. 이 PC의 브라우저 주소창에 붙여넣으세요. 사용 후 클립보드 내용을 지워 주세요.";
      } catch {
        field.value = result.url;
        fallback.hidden = false;
        field.focus();
        field.select();
        message.textContent = "자동 복사가 차단되었습니다. 선택된 링크를 Ctrl+C로 복사하세요.";
      }
    } catch {
      clearLink();
      message.textContent = "요청 결과를 확인하지 못했습니다. 연결 상태를 새로고침하세요. 자동 재시도하지 않습니다.";
    } finally {
      buttons.forEach((item) => { item.disabled = false; });
    }
  }));
});

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
