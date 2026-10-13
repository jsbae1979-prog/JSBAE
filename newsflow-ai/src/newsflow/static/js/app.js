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
const collectionForm = button && button.closest('form');
if (collectionForm) collectionForm.addEventListener('submit', () => { button.disabled = true; button.textContent = '수집 요청 중…'; });
