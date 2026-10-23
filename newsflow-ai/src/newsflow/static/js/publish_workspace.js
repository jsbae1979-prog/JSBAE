'use strict';
const selection = document.querySelector('[data-publish-target]');
if (selection) {
  function updateTargets() {
    const targets = selection.value === 'all' ? ['youtube', 'instagram', 'tiktok', 'facebook'] : selection.value === 'both' ? ['youtube', 'instagram'] : [selection.value];
    let connected = true;
    document.querySelectorAll('[data-publish-account]').forEach(section => {
      const active = targets.includes(section.dataset.publishAccount);
      section.hidden = !active;
      section.querySelectorAll('select').forEach(control => { control.disabled = !active; });
      if (active && !section.querySelector('select option')) connected = false;
    });
    const save = document.querySelector('[data-publish-save]');
    if (save) save.disabled = !connected;
    const status = document.querySelector('[data-publish-readiness]');
    if (status) status.textContent = connected
      ? '대상 계정이 연결되어 있습니다. 내용·출처·권리를 검토한 뒤 저장하세요. 게시 승인은 다음 단계에서 따로 받습니다.'
      : '계정 연결 필요 · 로컬 초안은 지금 저장할 수 있습니다. 검토 기록은 연결 후 남겨 주세요.';
  }
  selection.addEventListener('change', updateTargets);
  updateTargets();
}
const reviewForm = document.querySelector('[data-publish-review]');
if (reviewForm) {
  let changed = false;
  reviewForm.addEventListener('input', () => {
    changed = true;
    reviewForm.querySelector('[data-publish-unsaved]').hidden = false;
  });
  document.addEventListener('settings:form-saved', event => {
    if (event.detail.form === reviewForm) changed = false;
  });
  window.addEventListener('beforeunload', event => {
    if (changed) { event.preventDefault(); event.returnValue = ''; }
  });
}
