'use strict';
const state = document.getElementById('collection-status');
const button = document.getElementById('collect-button');
const labels = {idle:'대기',running:'수집 중',success:'성공',partial:'부분 실패',failed:'실패',empty:'활성 출처 없음',interrupted:'중단'};
if (state) {
  let last = state.dataset.status;
  let runId = null;
  async function poll() {
    try {
      const response = await fetch('/api/collection', {cache:'no-store'});
      if (!response.ok) throw new Error();
      const data = await response.json();
      if ((last === 'running' && data.status !== 'running') || (runId !== null && runId !== data.run_id && data.status !== 'running')) {
        window.location.reload(); return;
      }
      state.textContent = `${labels[data.status] || data.status} · 신규 ${data.added} · 성공 ${data.succeeded} · 실패 ${data.failed}`;
      if (button) button.disabled = data.status === 'running';
      last = data.status; runId = data.run_id;
    } catch (_) { state.textContent = '실행 상태를 확인하지 못했습니다. 새로고침해 주세요.'; }
    window.setTimeout(poll, 2000);
  }
  poll();
}
// no-referrer preserves external privacy but makes native navigation POST Origin:null.
// Fetch in cors mode sends the browser's real Origin; server CSRF/Origin checks stay intact.
for (const form of document.querySelectorAll('form[method="post"]')) {
  form.addEventListener('submit', async (event) => {
    event.preventDefault();
    const target = new URL(form.action, window.location.href);
    if (target.origin !== window.location.origin) return;
    const submit = form.querySelector('button[type="submit"], button:not([type])');
    const label = submit ? submit.textContent : '';
    if (submit) { submit.disabled = true; submit.textContent = '처리 중…'; }
    let alert = form.querySelector('[data-submit-error]');
    if (!alert) {
      alert = document.createElement('p');
      alert.dataset.submitError = 'true';
      alert.setAttribute('role', 'alert');
      form.append(alert);
    }
    alert.textContent = '';
    try {
      const response = await fetch(target.href, {
        method: 'POST', mode: 'cors', credentials: 'same-origin',
        body: new URLSearchParams(new FormData(form))
      });
      if (!response.ok) {
        const messages = {
          403: '보안 검증에 실패했습니다. 새로고침 후 다시 시도하세요.',
          409: '이미 실행 중이거나 중복된 요청입니다. 현재 상태를 확인하세요.',
          422: '입력값과 필수 확인 항목을 확인하세요.'
        };
        alert.textContent = messages[response.status] || '요청을 처리하지 못했습니다. 실행 로그를 확인하세요.';
        return;
      }
      const next = new URL(response.url);
      if (next.origin !== window.location.origin) throw new Error('Unexpected redirect');
      window.location.assign(next.href);
    } catch (_) {
      alert.textContent = '서버에 연결하지 못했습니다. 실행 상태를 확인하세요.';
    } finally {
      if (submit) { submit.disabled = false; submit.textContent = label; }
    }
  });
}
const renderState = document.getElementById('render-status');
if (renderState && renderState.dataset.status === 'running') {
  async function pollRender() {
    try {
      const response = await fetch(`/api/video/jobs/${renderState.dataset.jobId}`, {cache:'no-store'});
      if (!response.ok) throw new Error();
      const data = await response.json();
      renderState.textContent = `${data.progress}% · ${data.message}`;
      document.getElementById('render-progress').value = data.progress;
      if (data.status !== 'running') { window.location.reload(); return; }
    } catch (_) { renderState.textContent = '영상 상태를 확인하지 못했습니다. 작업 이력을 확인하세요.'; }
    window.setTimeout(pollRender, 2000);
  }
  pollRender();
}
