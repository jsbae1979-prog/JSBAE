'use strict';
const selection = document.querySelector('[data-publish-target]');
if (selection) {
  function updateTargets() {
    const targets = selection.value === 'both' ? ['youtube', 'instagram'] : [selection.value];
    document.querySelectorAll('[data-publish-account]').forEach(section => {
      const active = targets.includes(section.dataset.publishAccount);
      section.hidden = !active;
      section.querySelectorAll('select').forEach(control => { control.disabled = !active; });
    });
  }
  selection.addEventListener('change', updateTargets);
  updateTargets();
}
