"use strict";
document.querySelectorAll("[data-rss-file]").forEach(input => {
  input.addEventListener("change", async () => {
    const form = input.closest("form"), target = form.querySelector("[data-rss-payload]");
    const status = form.querySelector("[data-rss-status]");
    target.value = "";
    try {
      const file = input.files[0];
      if (!file || file.size > 2 * 1024 * 1024) throw new Error();
      const text = await file.text();
      if (/<!DOCTYPE|<!ENTITY/i.test(text)) throw new Error();
      const doc = new DOMParser().parseFromString(text, "application/xml");
      if (doc.querySelector("parsererror") || doc.documentElement.tagName !== "rss") throw new Error();
      const items = Array.from(doc.querySelectorAll("channel > item"));
      if (!items.length) throw new Error();
      const output = document.implementation.createDocument(null, "rss");
      output.documentElement.setAttribute("version", "2.0");
      const channel = output.createElement("channel"); output.documentElement.append(channel);
      for (const item of items.slice(0, 5)) {
        const copy = output.createElement("item");
        for (const [name, limit] of [["title", 200], ["link", 2048], ["description", 250], ["source", 100], ["pubDate", 100]]) {
          const value = item.querySelector(name)?.textContent;
          if (value) {
            if ((name === "link" || name === "pubDate") && value.length > limit) throw new Error();
            const node = output.createElement(name); node.textContent = value.slice(0, limit); copy.append(node);
          }
        }
        channel.append(copy);
      }
      const xml = new XMLSerializer().serializeToString(output);
      if (new URLSearchParams({rss_xml: xml}).toString().length > 60000) throw new Error();
      target.value = xml;
      status.textContent = `${file.name} · 앞의 ${Math.min(5, items.length)}개 기사 준비 · 사용자 제공 자료`;
    } catch (_) { status.textContent = "안전한 RSS XML 파일(최대 2 MiB)을 선택해 주세요."; }
  });
});
document.querySelectorAll("[data-curation-form]").forEach(form => {
  form.addEventListener("submit", event => {
    if (form.querySelector("[data-rss-payload]") && !form.querySelector("[data-rss-payload]").value) {
      event.preventDefault(); window.alert("RSS 파일을 확인해 주세요."); return;
    }
    form.querySelectorAll('button[type="submit"]').forEach(button => {
      button.disabled = true;
      button.textContent = "처리 중 · 자동 재시도하지 않습니다";
    });
    form.setAttribute("aria-busy", "true");
  });
});
