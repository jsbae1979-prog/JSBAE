'use strict';
// AI 고품질 제작 forms: same-origin POST once; a refusal shows the server's fixed Korean sentence
// (JSON "detail") as plain text. An uncertain response is never retried automatically.
for (const form of document.querySelectorAll('form[data-ai-form]')) {
  let pending = false;
  form.addEventListener('submit', async (event) => {
    event.preventDefault();
    if (pending) return;
    const target = new URL(form.action, window.location.href);
    if (target.origin !== window.location.origin) return;
    const submit = form.querySelector('button[type="submit"]');
    const alert = form.querySelector('[data-submit-error]');
    const label = submit ? submit.textContent : '';
    pending = true;
    if (submit) { submit.disabled = true; submit.textContent = '잠시만 기다려 주세요…'; }
    if (alert) alert.textContent = '';
    try {
      const response = await fetch(target.href, {
        method: 'POST', mode: 'cors', credentials: 'same-origin',
        body: new URLSearchParams(new FormData(form))
      });
      if (!response.ok) {
        let detail = '';
        try {
          const data = await response.json();
          if (data && typeof data.detail === 'string') detail = data.detail;
        } catch (_) { detail = ''; }
        const fallback = {
          403: '보안 확인을 위해 화면을 새로고침한 뒤 다시 시도해 주세요.',
          404: '계획이나 장면을 찾지 못했습니다. 목록에서 다시 확인해 주세요.',
          409: '다른 화면에서 바뀌었거나 진행 중인 작업이 있습니다. 새로고침 후 확인해 주세요.',
          422: '입력값과 확인 항목을 다시 확인해 주세요.'
        };
        if (alert) alert.textContent = detail || fallback[response.status] || '요청 결과를 확인하지 못했습니다. 새로고침 후 상태를 확인해 주세요.';
        return;
      }
      const next = new URL(response.url);
      if (next.origin !== window.location.origin) throw new Error('Unexpected redirect');
      window.location.assign(next.href);
    } catch (_) {
      if (alert) alert.textContent = '서버 연결이 끊겨 결과를 확인하지 못했습니다. 다시 누르기 전에 새로고침해 상태를 확인해 주세요.';
    } finally {
      pending = false;
      if (submit) { submit.disabled = false; submit.textContent = label; }
    }
  });
}

// While scenes are being generated, check status every 3 s and reload when anything changes.
const planPage = document.querySelector('[data-ai-plan]');
if (planPage) {
  const active = new Set(['waiting', 'submitting', 'queued', 'in_progress', 'downloading']);
  const initial = Array.from(document.querySelectorAll('[data-scene-status]')).map((el) => el.dataset.sceneStatus);
  if (initial.some((status) => active.has(status)) || planPage.dataset.planStatus === 'composing') {
    const poll = async () => {
      try {
        const response = await fetch(`/api/video/ai/plans/${planPage.dataset.aiPlan}`, { cache: 'no-store', credentials: 'same-origin' });
        if (!response.ok) throw new Error('status');
        const data = await response.json();
        const now = data.scenes.map((scene) => scene.status);
        if (data.status !== planPage.dataset.planStatus || now.join() !== initial.join()) {
          window.location.reload();
          return;
        }
      } catch (_) { /* keep the current page; the next check tries again */ }
      window.setTimeout(poll, 3000);
    };
    window.setTimeout(poll, 3000);
  }
}
