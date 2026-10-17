'use strict';
document.querySelectorAll('[data-scene-up]').forEach(control => {
  control.addEventListener('click', () => {
    const scene = control.closest('fieldset');
    const previous = scene.previousElementSibling;
    if (previous?.matches('[data-topic-scene]')) previous.before(scene);
    scene.parentElement.querySelectorAll('[data-topic-scene] legend').forEach((legend, index) => {
      legend.textContent = `장면 ${index + 1}`;
    });
  });
});
document.querySelectorAll('[data-short-caption]').forEach(control => {
  control.addEventListener('click', () => {
    const caption = control.closest('fieldset').querySelector('[name="caption"]');
    // Keep the on-screen uncertainty notice; the server independently checks it.
    if (!caption.value.includes('개별 기사 미확인')) caption.value = control.dataset.shortCaption;
  });
});
document.querySelectorAll('[data-topic-narration-short]').forEach(control => {
  control.addEventListener('click', () => {
    const narration = control.closest('fieldset').querySelector('[name="narration"]');
    narration.value = narration.value === control.dataset.topicNarrationShort
      ? control.dataset.topicNarrationFull : control.dataset.topicNarrationShort;
    control.textContent = narration.value === control.dataset.topicNarrationShort
      ? '이 장면을 자세히' : '이 장면을 짧게';
  });
});
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
for (const form of document.querySelectorAll('form[method="post"]:not([data-easy-form]):not([data-ai-form]):not([data-claude-action]):not([data-codex-action])')) {
  form.addEventListener('submit', async (event) => {
    if (event.defaultPrevented) return;
    event.preventDefault();
    const target = new URL(event.submitter?.getAttribute('formaction') || form.action, window.location.href);
    if (target.origin !== window.location.origin) return;
    const submit = event.submitter || form.querySelector('button[type="submit"], button:not([type])');
    const label = submit ? submit.textContent : '';
    if (submit) { submit.disabled = true; submit.textContent = '처리 중…'; }
    let alert = form.id === 'production-preferences'
      ? document.getElementById('settings-save-error') : form.querySelector('[data-submit-error]');
    if (!alert) {
      alert = document.createElement('p');
      alert.dataset.submitError = 'true';
      alert.setAttribute('role', 'alert');
      alert.tabIndex = -1;
      form.append(alert);
    }
    alert.textContent = '';
    try {
      const response = await fetch(target.href, {
        method: 'POST', mode: 'cors', credentials: 'same-origin',
        body: new URLSearchParams(new FormData(form))
      });
      if (!response.ok) {
        if (response.status === 422 && (form.hasAttribute('data-ai-studio') || form.hasAttribute('data-settings-form')
            || form.hasAttribute('data-topic-editor-form') || form.hasAttribute('data-youtube-form'))) {
          const failure = await response.json();
          alert.textContent = typeof failure.detail === 'string' && failure.detail.length <= 300
            ? failure.detail : '제공자·모델과 실행 동의 항목을 확인해 주세요.';
          return;
        }
        if (response.status === 422 && form.hasAttribute('data-setup-form')) {
          const documentCopy = new DOMParser().parseFromString(await response.text(), 'text/html');
          const explanation = documentCopy.getElementById('setup-error');
          alert.textContent = explanation ? explanation.textContent : '선택한 설정과 이전 단계를 확인해 주세요.';
          return;
        }
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
      if (form.hasAttribute('data-youtube-form')) {
        next.hash = next.pathname === '/simple-settings' ? 'youtube' : 'youtube-publish';
      }
      document.dispatchEvent(new CustomEvent('settings:form-saved', {detail: {form}}));
      window.location.assign(next.href);
    } catch (_) {
      alert.textContent = '서버에 연결하지 못했습니다. 실행 상태를 확인하세요.';
    } finally {
      if (alert.textContent && form.closest('.settings-workspace')) alert.focus();
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
