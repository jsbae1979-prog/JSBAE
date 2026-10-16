'use strict';
// Same-origin fetch preserves Origin under the existing no-referrer policy.
// Each mutation is submitted once. An uncertain response is never auto-retried.
function wireEasyForms() {
for (const form of document.querySelectorAll('form[data-easy-form]')) {
  if (form.dataset.easyWired) continue;
  form.dataset.easyWired = 'true';
  let pending = false;
  form.addEventListener('submit', async (event) => {
    event.preventDefault();
    if (pending) return;
    const target = new URL(form.getAttribute('action'), window.location.href);
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
        if (form.closest('.schedule-page, .operations-page')) {
          const error = await response.json().catch(() => null);
          if (typeof error?.detail === 'string' && error.detail.length <= 300) {
            if (alert) alert.textContent = error.detail;
            return;
          }
        }
        const messages = {
          403: '보안 확인을 위해 화면을 새로고침한 뒤 다시 시도해 주세요.',
          404: '이 작업을 찾을 수 없습니다. 나의 제작 작업에서 다시 확인해 주세요.',
          409: '진행 중인 작업이나 변경된 결과가 있습니다. 나의 제작 작업을 확인해 주세요.',
          422: '선택한 값과 현재 작업 상태를 다시 확인해 주세요.'
        };
        if (alert) alert.textContent = messages[response.status] || '요청 결과를 확인하지 못했습니다. 나의 제작 작업에서 먼저 결과를 확인해 주세요.';
        return;
      }
      const next = new URL(response.url);
      if (next.origin !== window.location.origin) throw new Error('Unexpected redirect');
      // Fetch may omit a redirect fragment. Keep a workspace mutation at its saved review panel.
      if (next.pathname === '/' && next.searchParams.has('task') &&
          form.querySelector('input[name="workspace"][value="true"]')) {
        next.hash = 'workspace-detail';
      }
      window.location.assign(next.href);
    } catch (_) {
      if (alert) alert.textContent = '서버 연결이 끊겨 결과를 확인하지 못했습니다. 다시 누르기 전에 나의 제작 작업에서 진행 상황을 확인해 주세요.';
    } finally {
      pending = false;
      if (submit) { submit.disabled = false; submit.textContent = label; }
    }
  });
}

}
wireEasyForms();
document.addEventListener('newsflow:updated', wireEasyForms);

const taskPage = document.querySelector('[data-autopilot-job]');
if (taskPage && ['queued', 'running'].includes(taskPage.dataset.jobStatus)) {
  const initialStage = taskPage.dataset.jobStage;
  const warn = taskPage.querySelector('[data-poll-warning]');
  async function pollAutopilot() {
    try {
      const response = await fetch(`/api/autopilot/jobs/${taskPage.dataset.autopilotJob}`, {
        cache: 'no-store', credentials: 'same-origin'
      });
      if (!response.ok) throw new Error('Status unavailable');
      const data = await response.json();
      if (data.status !== taskPage.dataset.jobStatus || data.current_stage !== initialStage) {
        window.location.reload();
        return;
      }
      taskPage.dataset.jobRevision = String(data.revision);
      for (const field of taskPage.querySelectorAll('input[name="revision"]')) field.value = String(data.revision);
      const progress = document.getElementById('autopilot-progress');
      progress.value = data.progress;
      taskPage.querySelector('[data-progress-label]').textContent = `${data.progress}%`;
      taskPage.querySelector('[data-job-message]').textContent = data.message;
      taskPage.querySelector('[data-stage-label]').textContent = data.stage_label;
      if (warn) warn.textContent = '';
    } catch (_) {
      if (warn) warn.textContent = '진행 상황을 확인하지 못했습니다. 작업이 끝났다는 뜻은 아닙니다. 연결이 돌아오면 다시 확인할게요.';
    }
    window.setTimeout(pollAutopilot, 1500);
  }
  window.setTimeout(pollAutopilot, 500);
}
