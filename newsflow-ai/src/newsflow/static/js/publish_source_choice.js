'use strict';
// This is an editor control, not a publishing approval. Persist the visible text
// through the existing review form; no new request, provider call or hidden flag.
(() => {
  document.querySelectorAll('[data-source-links-toggle]').forEach(toggle => {
    if (toggle.dataset.bound) return;
    toggle.dataset.bound = 'true';
    const description = toggle.closest('form')?.querySelector('[name="description"]');
    const block = toggle.dataset.sourceBlock;
    if (!description || !block) return;
    const sync = () => { toggle.checked = description.value.includes(block); };
    toggle.disabled = false;
    sync();
    description.addEventListener('input', sync);
    toggle.addEventListener('change', () => {
      if (toggle.checked) {
        if (!description.value.includes(block)) {
          const next = description.value + (description.value ? '\n\n' : '') + block;
          if (description.maxLength > 0 && next.length > description.maxLength) {
            toggle.checked = false;
            description.setCustomValidity('출처 링크를 넣으려면 설명을 줄여 주세요.');
            description.reportValidity();
            return;
          }
          description.value = next;
        }
      } else {
        description.value = description.value.split('\n\n' + block).join('').split(block).join('');
      }
      description.setCustomValidity('');
      description.dispatchEvent(new Event('input', {bubbles: true}));
    });
    description.addEventListener('input', () => description.setCustomValidity(''));
  });
})();
