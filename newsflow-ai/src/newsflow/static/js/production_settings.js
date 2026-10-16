"use strict";
// Presentation only. Saving, checks, login and generation remain explicit actions.
(() => {
  const form = document.getElementById('production-preferences');
  if (!form) return;
  const provider = form.elements.namedItem('provider');
  const voice = form.elements.namedItem('voice');
  const video = form.elements.namedItem('video_provider');
  const watched = [...document.querySelectorAll('form[data-settings-watch]')];
  const fields = target => [...target.elements].filter(el => el.name && el.name !== 'csrf_token');
  const value = el => ['checkbox', 'radio'].includes(el.type) ? el.checked : el.value;
  const originals = new Map(watched.map(target => [target, fields(target).map(el => [el, value(el)])]));
  const dirty = target => originals.get(target)?.some(([el, initial]) => value(el) !== initial);
  const reveal = () => {
    for (const el of document.querySelectorAll('[data-ai-provider]')) el.hidden = el.dataset.aiProvider !== provider.value;
    for (const el of document.querySelectorAll('[data-voice-provider]')) el.hidden = el.dataset.voiceProvider !== voice.selectedOptions[0].dataset.engine;
    for (const el of document.querySelectorAll('[data-video-provider]')) el.hidden = el.dataset.videoProvider !== video.value;
  };
  const refresh = () => {
    document.getElementById('production-unsaved').hidden = !dirty(form);
    document.querySelector('[data-settings-saved-label]').hidden = dirty(form);
    document.querySelector('[data-settings-reset]').hidden = !dirty(form);
    for (const target of watched.filter(target => target !== form)) {
      let note = target.querySelector('.settings-dirty-note');
      if (!note) {
        note = document.createElement('p'); note.className = 'settings-dirty-note';
        note.setAttribute('role', 'status'); note.textContent = '이 항목의 변경사항을 아직 저장하지 않았습니다.';
        target.append(note);
      }
      note.hidden = !dirty(target);
    }
    reveal();
  };
  for (const target of watched) {
    for (const el of fields(target)) {
      el.addEventListener('input', refresh);
      el.addEventListener('change', refresh);
    }
  }
  document.querySelector('[data-settings-reset]').addEventListener('click', () => {
    const restore = () => { for (const [el, initial] of originals.get(form)) el.value = initial; };
    // Let the existing model selector remember the outgoing provider's own model
    // before restoring the saved fields; otherwise it caches the wrong model.
    provider.value = originals.get(form).find(([el]) => el === provider)[1];
    provider.dispatchEvent(new Event('change')); restore(); refresh();
  });
  window.addEventListener('beforeunload', event => {
    if (watched.some(dirty)) { event.preventDefault(); event.returnValue = ''; }
  });
  document.addEventListener('settings:form-saved', event => {
    if (originals.has(event.detail.form)) {
      originals.set(event.detail.form, fields(event.detail.form).map(el => [el, value(el)]));
      refresh();
    }
  });
  const openers = new WeakMap();
  const open = (dialog, opener) => {
    if (!dialog || dialog.open) return;
    openers.set(dialog, opener || document.activeElement); dialog.showModal();
  };
  document.addEventListener('click', event => {
    const opener = event.target.closest('[data-settings-open]');
    if (opener) open(document.getElementById(opener.dataset.settingsOpen), opener);
    const closer = event.target.closest('[data-settings-close]');
    if (closer) closer.closest('dialog').close();
    if (event.target.closest('[data-settings-diagnostic-link]')) event.target.closest('dialog').close();
  });
  for (const dialog of document.querySelectorAll('dialog.settings-dialog')) {
    dialog.addEventListener('close', () => openers.get(dialog)?.focus());
  }
  const showAnchor = () => {
    const target = document.getElementById(window.location.hash.slice(1));
    if (!target) return;
    open(target.closest('dialog'), null);
    for (let parent = target.parentElement; parent; parent = parent.parentElement) {
      if (parent.tagName === 'DETAILS') parent.open = true;
    }
  };
  window.addEventListener('hashchange', showAnchor);
  document.addEventListener('invalid', event => {
    for (let parent = event.target.parentElement; parent; parent = parent.parentElement) {
      if (parent.tagName === 'DETAILS') parent.open = true;
    }
  }, true);
  refresh(); showAnchor();
})();
