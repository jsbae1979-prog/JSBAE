"use strict";
// Presentation only: no fetch, inference, autosave, connection checks or media creation.
(() => {
  const root = document.querySelector('.script-simple');
  if (!root) return;
  const selection = root.querySelector('[data-script-selection]');
  if (selection) {
    const choices = [...selection.querySelectorAll('[data-script-article]')];
    const search = selection.querySelector('[data-script-search]');
    const more = selection.querySelector('[data-script-more]');
    const count = selection.querySelector('[data-script-selection-count]');
    const empty = selection.querySelector('[data-script-no-matches]');
    let expanded = false;
    function update() {
      const query = search.value.trim().toLocaleLowerCase();
      let matched = 0;
      choices.forEach(choice => {
        const selected = choice.querySelector('input').checked;
        const matches = choice.textContent.toLocaleLowerCase().includes(query);
        choice.hidden = !selected && (!matches || (!query && !expanded && matched >= 6));
        if (matches) matched++;
      });
      const selected = choices.filter(choice => choice.querySelector('input').checked).length;
      count.textContent = selected ? `${selected}개 선택 · 최대 10개` : '기사 선택 전';
      empty.hidden = matched !== 0;
      if (more) {
        more.hidden = Boolean(query) || choices.length <= 6;
        more.textContent = expanded ? '간단히 보기' : `기사 더 보기 (${choices.length}개)`;
        more.setAttribute('aria-expanded', String(expanded));
      }
    }
    search.addEventListener('input', update);
    selection.addEventListener('change', update);
    more?.addEventListener('click', () => { expanded = !expanded; update(); });
    update();
  }
  root.querySelectorAll('[data-ai-studio]').forEach(form => {
    const label = form.querySelector('[data-script-consent]');
    const consent = label?.querySelector('[name=consent]');
    const provider = form.querySelector('[name=provider]');
    if (!consent || !provider) return;
    function mode() {
      const external = provider.value !== 'offline';
      const submitLabel = form.querySelector('[data-script-generate-label]');
      if (submitLabel) submitLabel.textContent = external ? `${provider.options[provider.selectedIndex].textContent}로 대본 생성` : '체험 대본 생성';
      label.hidden = !external;
      consent.required = external;
      if (!external) consent.checked = false;
    }
    form.addEventListener('change', event => {
      // Approvals never carry over to a different article/model/length selection.
      if (event.target !== consent) consent.checked = false;
      mode();
    });
    mode();
  });
  const panel = root.querySelector('[data-script-dialog-panel]');
  if (panel && typeof HTMLDialogElement !== 'undefined' && HTMLDialogElement.prototype.showModal) {
    const dialog = document.createElement('dialog');
    dialog.id = 'script-create-dialog';
    dialog.className = 'script-create-dialog';
    dialog.setAttribute('aria-labelledby', 'script-dialog-title');
    root.append(dialog);
    dialog.append(panel);
    const close = panel.querySelector('[data-script-dialog-close]');
    close.hidden = false;
    let opener = null;
    function open(trigger) {
      opener = trigger || opener;
      if (!dialog.open) dialog.showModal();
    }
    root.querySelectorAll('[data-script-dialog-open]').forEach(trigger => trigger.addEventListener('click', event => {
      event.preventDefault(); open(trigger);
    }));
    close.addEventListener('click', () => dialog.close());
    dialog.addEventListener('click', event => {
      if (event.target === dialog) {
        const box = dialog.getBoundingClientRect();
        if (event.clientX < box.left || event.clientX > box.right || event.clientY < box.top || event.clientY > box.bottom) dialog.close();
      }
    });
    dialog.addEventListener('close', () => opener?.focus());
    function deepLink() { if (location.hash === '#analysis-result') open(root.querySelector('[data-script-dialog-open]')); }
    window.addEventListener('hashchange', deepLink);
    deepLink();
  }
  root.querySelectorAll('[data-script-source-open]').forEach(link => link.addEventListener('click', event => {
    const sources = root.querySelector('#script-sources');
    if (!sources) return;
    event.preventDefault();
    sources.open = true;
    sources.querySelector('summary').focus();
  }));
  const readLinks = [...root.querySelectorAll('[data-script-read-scene]')];
  function markReadScene(index) {
    readLinks.forEach(link => {
      if (Number(link.dataset.scriptReadScene) === index) link.setAttribute('aria-current', 'location');
      else link.removeAttribute('aria-current');
    });
  }
  function readHash() {
    const match = location.hash.match(/^#script-scene-(\d+)$/);
    markReadScene(match ? Number(match[1]) : 1);
  }
  readLinks.forEach(link => link.addEventListener('click', () => markReadScene(Number(link.dataset.scriptReadScene))));
  window.addEventListener('hashchange', readHash);
  readHash();
  const editor = root.querySelector('[data-script-editor]');
  function openEditor(index) {
    if (!editor) return;
    editor.open = true;
    markReadScene(Number(index) + 1);
    const scene = editor.querySelector(`[data-edit-scene="${index}"]`);
    scene?.click();
    editor.scrollIntoView({block: 'nearest'});
    editor.querySelector(`[data-topic-scene]:not([hidden]) [name=narration]`)?.focus();
  }
  root.querySelectorAll('[data-script-edit-scene]').forEach(button => button.addEventListener('click', () => openEditor(button.dataset.scriptEditScene)));
  // Retain the existing outline controls and their synchronization with the editor.
  root.querySelectorAll('[data-outline-scene]').forEach(button => button.addEventListener('click', () => {
    if (editor) editor.open = true;
  }, true));
  editor?.addEventListener('input', () => {
    const notice = root.querySelector('[data-script-reading-dirty]');
    if (notice) notice.hidden = false;
    editor.querySelectorAll('[data-topic-scene]').forEach((scene, index) => {
      const narration = root.querySelector(`[data-script-read-narration="${index}"]`);
      const caption = root.querySelector(`[data-script-read-caption="${index}"]`);
      if (narration) narration.textContent = scene.querySelector('[name=narration]').value;
      if (caption) caption.textContent = scene.querySelector('[name=caption]').value;
    });
  });
  root.addEventListener('invalid', event => {
    for (let node = event.target.parentElement; node && node !== root; node = node.parentElement) {
      if (node.tagName === 'DETAILS') node.open = true;
      if (node.tagName === 'DIALOG' && !node.open) node.showModal();
    }
  }, true);
})();
