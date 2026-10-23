(() => {
  document.querySelectorAll("[data-generate-image], [data-generate-card]").forEach((generationForm) => {
  generationForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    const button = generationForm.querySelector('button[type="submit"]');
    const status = generationForm.querySelector("[data-generation-status]");
    if (button.disabled || !generationForm.reportValidity()) return;
    const card = document.querySelector("[data-image-form]");
    const codex = generationForm.hasAttribute("data-codex-image");
    if (!codex && card?.dataset.edited === "true") {
      status.textContent = "문구가 수정되었습니다. 아래 카드를 먼저 저장한 뒤 배경을 생성하세요.";
      return;
    }
    const data = new FormData(generationForm);
    if (codex) {
      data.set("title", document.querySelector("#image-title")?.value || "");
      data.set("body", document.querySelector("#image-body")?.value || "");
      if (!data.get("title").trim() || !data.get("body").trim() ||
          data.get("title").trim().length > 60 || data.get("body").trim().length > 200) {
        status.textContent = "아래 문구를 제목 60자·본문 200자 이내로 정리하세요.";
        return;
      }
    }
    button.disabled = true;
    status.textContent = codex ? "Codex 이미지 요청 중 · 최대 5분 · 다시 요청하지 마세요." :
      "요청을 처리하고 있습니다. 최대 180초가 걸릴 수 있습니다. 다시 요청하지 마세요.";
    try {
      const response = await fetch(generationForm.action, {
        method: "POST", body: new URLSearchParams(data), credentials: "same-origin"
      });
      if (response.ok && response.redirected) {
        window.location.assign(response.url);
        return;
      }
      const result = await response.json().catch(() => null);
      status.textContent = typeof result?.detail === "string" ? result.detail :
        "처리 결과를 확인하지 못했습니다. 페이지를 새로고침해 생성 기록을 확인하세요.";
    } catch {
      status.textContent = "응답 연결이 끊겼습니다. 다시 요청하지 말고 새로고침해 생성 기록을 확인하세요.";
    }
    // No client retry, even when the browser did not receive the result.
  });
  });
  const form = document.querySelector("[data-image-form]");
  if (form) {
    form.addEventListener("input", () => { form.dataset.edited = "true"; });
    const fileInput = form.querySelector("[data-image-file]");
    const output = form.querySelector("[data-image-base64]");
    const error = form.querySelector("[data-image-error]");
    const submit = form.querySelector('button[type="submit"]');
    let version = 0;
    fileInput.addEventListener("change", () => {
      const generation = ++version;
      output.value = "";
      error.textContent = "";
      const file = fileInput.files[0];
      if (!file) { submit.disabled = false; return; }
      if (file.size > 4 * 1024 * 1024 || !["image/jpeg","image/png","image/webp"].includes(file.type)) {
        error.textContent = "4MB 이하 JPEG·PNG·WebP 사진을 선택하세요.";
        submit.disabled = true; return;
      }
      submit.disabled = true;
      const reader = new FileReader();
      reader.onload = () => {
        if (generation !== version) return;
        output.value = String(reader.result).split(",")[1] || "";
        submit.disabled = !output.value;
      };
      reader.onerror = () => {
        if (generation === version) error.textContent = "사진을 읽지 못했습니다. 다시 선택하세요.";
      };
      reader.readAsDataURL(file);
    });
    form.addEventListener("submit", async (event) => {
      event.preventDefault();
      if (submit.disabled || !form.reportValidity()) return;
      submit.disabled = true;
      error.textContent = "";
      try {
        const response = await fetch(form.action, {
          method: "POST", body: new URLSearchParams(new FormData(form)),
          credentials: "same-origin"
        });
        if (response.ok && response.redirected) {
          window.location.assign(response.url);
          return;
        }
        const value = await response.json().catch(() => null);
        error.textContent = typeof value?.detail === "string" ? value.detail :
          "입력 내용과 이미지 크기를 확인해 주세요.";
        submit.disabled = false;
      } catch {
        error.textContent = "저장 결과를 확인하지 못했습니다. 다시 만들기 전에 저장한 이미지 목록을 확인하세요.";
      }
    });
  }
  document.querySelector("[data-copy-caption]")?.addEventListener("click", async () => {
    const field = document.querySelector("#image-caption");
    const status = document.querySelector("[data-copy-status]");
    try {
      await navigator.clipboard.writeText(field.value);
      status.textContent = "본문과 출처를 복사했습니다.";
    } catch {
      field.focus(); field.select();
      status.textContent = "본문을 선택했습니다. Ctrl+C로 복사하세요.";
    }
  });
})();
