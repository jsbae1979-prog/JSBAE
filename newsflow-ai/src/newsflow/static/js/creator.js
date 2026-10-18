"use strict";
// View interactions only. Never starts inference, synthesis, authentication or publishing.
document.querySelectorAll('[data-topic-search]').forEach(form => {
  form.addEventListener('submit', event => {
    const field = form.querySelector('[name="q"]');
    const error = form.querySelector('[data-topic-error]');
    field.value = field.value.trim();
    if (/^https?:\/\//i.test(field.value)) {
      event.preventDefault();
      error.textContent = '새 기사 URL 가져오기는 아직 지원하지 않아요. 기사 제목이나 주제로 검색해 주세요.';
      error.hidden = false;
      field.focus();
    }
  });
});
const articleMatch = /^#article-(\d+)$/.exec(location.hash);
if (articleMatch) {
  const article = document.getElementById(`article-${articleMatch[1]}`);
  if (article?.type === 'checkbox') { article.checked = true; article.focus(); }
}
document.querySelectorAll('form[action^="/ai/drafts/"]').forEach(form => {
  let hasEdits = false;
  const selector = form.querySelector('.scene-tabs');
  const dirty = form.querySelector('[data-editor-dirty]');
  function scenes() { return Array.from(form.querySelectorAll('[data-topic-scene]')); }
  function selectScene(index) {
    scenes().forEach((scene, i) => { scene.hidden = i !== index; });
    selector?.querySelectorAll('button').forEach((button, i) => button.setAttribute('aria-pressed', String(i === index)));
    const player = document.querySelector('[data-editor-player]');
    if (player?.readyState >= 1) {
      const time = scenes().slice(0,index).reduce((sum, scene) => sum + Number(scene.querySelector('[name="seconds"]').value || 0), 0);
      player.currentTime = Math.min(time, player.duration || 0);
    }
  }
  selector?.querySelectorAll('[data-edit-scene]').forEach(button => button.addEventListener('click', () => selectScene(Number(button.dataset.editScene))));
  if (selector) selectScene(0);
  function changed() { hasEdits = true; if (dirty) dirty.hidden = false; }
  form.addEventListener('input', changed);
  form.addEventListener('change', changed);
  form.querySelectorAll('[data-scene-up],[data-short-caption],[data-topic-narration-short]').forEach(button => button.addEventListener('click', changed));
  // Invalid fields in another scene must be reachable for native keyboard validation.
  form.addEventListener('invalid', event => {
    const scene = event.target.closest('[data-topic-scene]');
    if (scene) selectScene(scenes().indexOf(scene));
    for (let parent = event.target.parentElement; parent && parent !== form; parent = parent.parentElement) {
      if (parent.tagName === 'DETAILS') parent.open = true;
    }
  }, true);
  document.addEventListener('settings:form-saved', event => {
    if (event.detail.form === form) hasEdits = false;
  });
  window.addEventListener('beforeunload', event => {
    if (hasEdits) { event.preventDefault(); event.returnValue = ''; }
  });
});
