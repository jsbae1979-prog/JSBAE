'use strict';
const selection = document.querySelector('[data-publish-target]');
if (selection) {
  function updateTargets() {
    const targets = selection.value === 'both' ? ['youtube', 'instagram'] : [selection.value];
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
      : '연결 필요 · 선택한 플랫폼의 계정을 설정에서 연결해 주세요. 연결 전 제목·설명은 저장되지 않습니다. MP4 저장은 가능합니다.';
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
