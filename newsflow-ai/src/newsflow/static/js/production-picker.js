"use strict";
// Native form submission is handled by the existing CSRF/Origin-safe app.js handler.
document.querySelectorAll('[data-production-picker]').forEach(picker => {
  const options = [...picker.querySelectorAll('.production-picker-option')];
  options.forEach(option => option.addEventListener('toggle', () => {
    if (option.open) options.filter(other => other !== option).forEach(other => { other.open = false; });
  }));
  options.forEach(option => {
    const field = option.querySelector('select');
    const saved = field.value;
    field.addEventListener('change', () => {
      const changed = field.value !== saved;
      option.querySelector('[data-selection-status]').hidden = changed;
      option.querySelector('[data-selection-pending]').hidden = !changed;
    });
  });
  picker.addEventListener('keydown', event => {
    if (event.key === 'Escape') {
      const opened = options.find(option => option.open);
      if (opened) { opened.open = false; opened.querySelector('summary').focus(); }
    }
  });
  document.addEventListener('click', event => {
    if (!picker.contains(event.target)) options.forEach(option => { option.open = false; });
  });
});
