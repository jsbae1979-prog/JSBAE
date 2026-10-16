'use strict';
// Explicit user actions only: opening this page never starts a CLI check or inference.
(() => {
  const message = document.getElementById('codex-state');
  const checked = document.getElementById('codex-check-time');
  const web = document.getElementById('codex-web-state');
  const showTime = (value) => {
    if (!checked || !value) return;
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return;
    checked.dateTime = value;
    checked.textContent = date.toLocaleString('ko-KR', {timeZone:'Asia/Seoul'}) + ' KST 확인';
  };
  showTime(checked?.dateTime);
  for (const form of document.querySelectorAll('form[data-codex-action]')) {
    form.addEventListener('submit', async (event) => {
      event.preventDefault();
      const target = new URL(form.action, window.location.href);
      if (target.origin !== window.location.origin) return;
      const controls = [...document.querySelectorAll('form[data-codex-action] button')];
      controls.forEach(button => { button.disabled = true; });
      message.setAttribute('aria-busy', 'true');
      message.textContent = '확인 중… 이 작업은 추론을 시작하지 않습니다.';
      const controller = new AbortController();
      const timer = window.setTimeout(() => controller.abort(), 25000);
      try {
        const response = await fetch(target.href, {method:'POST', mode:'cors', credentials:'same-origin',
          body:new URLSearchParams(new FormData(form)), signal:controller.signal});
        if (!response.ok) {
          message.textContent = response.status === 403
            ? '보안 검증 실패 · 새로고침 후 다시 확인하세요.' : '요청을 처리하지 못했습니다. 실행 상태를 확인하세요.';
          return;
        }
        const result = await response.json();
        if (form.dataset.codexAction === 'cancel') {
          message.textContent = result.cancel_requested
            ? '취소를 요청했습니다. 이미 계정 사용량이 발생했을 수 있습니다.' : '현재 이 앱에서 실행 중인 Codex 요청이 없습니다.';
          return;
        }
        message.textContent = result.message;
        message.dataset.state = result.state;
        document.getElementById('codex-version').textContent = result.version ? 'CLI ' + result.version : 'CLI 버전 미확인';
        web.textContent = '웹 검색: BLOCKED · 개발 중단. RSS 자료 분석·대본 생성만 지원합니다.';
        showTime(result.checked_at);
      } catch (_) {
        message.textContent = '서버 응답 확인 실패·시간 초과. 자동 재시도하지 않습니다. 실행 상태를 확인하세요.';
      } finally {
        window.clearTimeout(timer);
        controls.forEach(button => { button.disabled = false; });
        message.removeAttribute('aria-busy');
      }
    });
  }
})();
