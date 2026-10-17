'use strict';
// User-triggered checks only. No polling, inference, credential collection or automatic login.
const connectionMessage = document.getElementById('claude-state');
const connectionTime = document.getElementById('claude-check-time');
function showCheckTime(value) {
  if (!connectionTime || !value) return;
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return;
  connectionTime.dateTime = value;
  connectionTime.textContent = date.toLocaleString('ko-KR', {timeZone:'Asia/Seoul'}) + ' KST 확인';
}
showCheckTime(connectionTime?.dateTime);
for (const form of document.querySelectorAll('form[data-claude-action]')) {
  form.addEventListener('submit', async (event) => {
    event.preventDefault();
    const target = new URL(form.action, window.location.href);
    if (target.origin !== window.location.origin) return;
    const controls = [...document.querySelectorAll('form[data-claude-action] button')];
    controls.forEach(button => { button.disabled = true; });
    connectionMessage.setAttribute('aria-busy', 'true');
    connectionMessage.textContent = form.dataset.claudeAction === 'status'
      ? '연결 확인 중… 추론을 실행하지 않습니다.' : '요청 처리 중…';
    const controller = new AbortController();
    const timer = window.setTimeout(() => controller.abort(), 25000);
    try {
      const response = await fetch(target.href, {method:'POST', mode:'cors', credentials:'same-origin',
        body:new URLSearchParams(new FormData(form)), signal:controller.signal});
      if (!response.ok) {
        connectionMessage.textContent = response.status === 403
          ? '보안 검증 실패 · 새로고침 후 다시 확인하세요.' : '요청 실패 · 필수 동의와 실행 상태를 확인하세요.';
        return;
      }
      const result = await response.json();
      if (form.dataset.claudeAction === 'cancel') {
        connectionMessage.textContent = result.cancel_requested
          ? '취소를 요청했습니다. 계정 사용량이 발생했을 수 있습니다.' : '현재 이 앱에서 실행 중인 Claude 요청이 없습니다.';
        return;
      }
      connectionMessage.textContent = result.message;
      connectionMessage.dataset.state = result.state;
      document.getElementById('claude-version').textContent = result.version ? 'CLI ' + result.version : 'CLI 버전 미확인';
      showCheckTime(result.checked_at);
    } catch (_) {
      connectionMessage.textContent = '서버 응답 확인 실패·시간 초과. 자동 재시도하지 않습니다. 로그인 창이 열렸다면 그 창에서 완료·취소한 뒤 연결을 다시 확인하세요.';
    } finally {
      window.clearTimeout(timer);
      controls.forEach(button => { button.disabled = false; });
      connectionMessage.removeAttribute('aria-busy');
    }
  });
}
for (const form of document.querySelectorAll('form[data-studio-models]')) {
  const models = JSON.parse(form.dataset.studioModels);
  const choices = JSON.parse(form.dataset.studioModelChoices || '{}');
  const provider = form.elements.namedItem('provider');
  const model = form.elements.namedItem('model');
  // form.elements includes controls outside the form associated by form="...".
  const picker = [...form.elements].find(element => element.hasAttribute('data-model-choice'));
  const custom = model.closest('[data-custom-model]');
  const customModes = {};
  const refreshPicker = () => {
    if (!picker) return; // Existing AI Studio forms keep their direct input.
    const available = choices[provider.value] || [];
    const known = available.some(choice => choice.value === model.value);
    const direct = customModes[provider.value] ?? !known;
    picker.replaceChildren(...available.map(choice => new Option(choice.label, choice.value)),
      new Option('다른 모델 직접 입력 · 검증 필요', '__custom__'));
    picker.value = direct ? '__custom__' : model.value;
    if (custom) custom.hidden = !direct;
    picker.hidden = false;
  };
  let previous = provider.value;
  provider.addEventListener('change', () => {
    models[previous] = model.value;
    model.value = models[provider.value] || '';
    previous = provider.value;
    refreshPicker();
    const label = form.querySelector('[data-studio-provider-label]');
    if (label) label.textContent = provider.selectedOptions[0].textContent;
    // Selection never starts a request or stores an execution consent.
  });
  picker?.addEventListener('change', () => {
    const direct = picker.value === '__custom__';
    customModes[provider.value] = direct;
    if (custom) custom.hidden = !direct;
    if (direct) {
      model.focus(); // Keep the user's saved value until they explicitly edit it.
      return;
    }
    model.value = picker.value;
    models[provider.value] = model.value;
    // The canonical field remains the only model submitted and watched for edits.
    model.dispatchEvent(new Event('input', {bubbles: true}));
    model.dispatchEvent(new Event('change', {bubbles: true}));
  });
  const restored = () => {
    previous = provider.value;
    models[previous] = model.value;
    delete customModes[previous];
    refreshPicker();
  };
  form.addEventListener('reset', () => window.setTimeout(restored, 0));
  if (form.id === 'production-preferences') {
    // production_settings restores saved fields after its provider change event.
    document.querySelector('[data-settings-reset]')?.addEventListener('click', () => window.setTimeout(restored, 0));
  }
  refreshPicker();
}
