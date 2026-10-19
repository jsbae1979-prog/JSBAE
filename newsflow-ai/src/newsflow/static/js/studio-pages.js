"use strict";
// Filters the already loaded task records. No API request, retry or state mutation.
const activityButtons = document.querySelectorAll('[data-activity-filter]');
activityButtons.forEach(button => button.addEventListener('click', () => {
  const chosen = button.dataset.activityFilter;
  let visible = 0;
  document.querySelectorAll('.suite-activity [data-workspace-task]').forEach(row => {
    const status = row.dataset.taskStatus;
    const keep = chosen === 'all' || status === chosen || chosen === 'attention' && ['failed','interrupted','cancelled','unknown'].includes(status);
    row.hidden = !keep;
    if (keep) visible++;
  });
  activityButtons.forEach(item => {
    item.classList.toggle('selected', item === button);
    item.setAttribute('aria-pressed', String(item === button));
  });
  const empty = document.querySelector('[data-activity-empty]');
  if (empty) empty.hidden = visible > 0;
  const result = document.querySelector('[data-activity-result]');
  if (result) result.textContent = `${button.textContent}: ${visible}개 기록`;
}));

// Quick category controls submit only the existing local article GET filter.
document.querySelectorAll('[data-news-category]').forEach(button => button.addEventListener('click', () => {
  const form = button.closest('form');
  form.elements.category.value = button.dataset.newsCategory;
  form.requestSubmit();
}));
document.querySelectorAll('[data-activity-day]').forEach(button => button.addEventListener('click', () => {
  document.querySelector('[data-activity-day-result]').textContent = button.dataset.activityDay;
}));
// View selection only: no rendering, paid requests, autosave or timeline edits.
const videoSceneButtons = document.querySelectorAll('[data-video-scene-select]');
function selectVideoScene(index) {
  document.querySelectorAll('[data-video-scene]').forEach(scene => {
    scene.hidden = scene.dataset.videoScene !== index;
  });
  videoSceneButtons.forEach(button => button.setAttribute('aria-pressed', String(button.dataset.videoSceneSelect === index)));
}
videoSceneButtons.forEach(button => button.addEventListener('click', () => {
  selectVideoScene(button.dataset.videoSceneSelect);
  const details = document.getElementById('video-advanced-editing');
  if (details) details.open = true;
}));
if (videoSceneButtons.length) selectVideoScene('0');
document.querySelectorAll('[data-scene-weight]').forEach(button => {
  const seconds = Number(button.dataset.sceneWeight);
  if (Number.isFinite(seconds) && seconds > 0 && seconds <= 60) button.style.flexGrow = String(seconds);
});
document.querySelector('.workstation-video-grid')?.addEventListener('invalid', event => {
  const scene = event.target.closest('[data-video-scene]');
  if (scene) selectVideoScene(scene.dataset.videoScene);
  for (let node = event.target.parentElement; node && node !== event.currentTarget; node = node.parentElement) {
    if (node.tagName === 'DETAILS') node.open = true;
  }
}, true);

// Settings are real tabs. Hidden controls keep their form ownership and pending values.
(() => {
  const index = document.querySelector('.suite-settings-tabs');
  if (!index) return;
  const tabs = [...index.querySelectorAll('a[href^="#"]')];
  const panels = tabs.map(tab => document.getElementById(tab.hash.slice(1)));
  const storageKey = 'newsflow-settings-tab';
  const content = document.querySelector('.suite-settings-content');
  index.setAttribute('role', 'tablist');
  content.classList.add('settings-tabs-ready');
  tabs.forEach((tab, i) => {
    tab.id = `settings-tab-${panels[i].id}`;
    tab.setAttribute('role', 'tab');
    tab.setAttribute('aria-controls', panels[i].id);
    panels[i].setAttribute('role', 'tabpanel');
    panels[i].setAttribute('aria-labelledby', tab.id);
    panels[i].tabIndex = 0;
  });
  function panelFor(target) {
    return panels.find(panel => target && panel.contains(target)) ||
      (target?.closest('#settings-diagnostics') ? document.getElementById('advanced') : null);
  }
  function activate(panel, focus = false) {
    if (!panels.includes(panel)) panel = panels[0];
    panels.forEach((item, i) => {
      const selected = item === panel;
      item.hidden = !selected;
      tabs[i].classList.toggle('selected', selected);
      tabs[i].setAttribute('aria-selected', String(selected));
      tabs[i].tabIndex = selected ? 0 : -1;
      if (selected && focus) tabs[i].focus();
    });
    if (panel.tagName === 'DETAILS') panel.open = true;
    try { sessionStorage.setItem(storageKey, panel.id); } catch (_) { /* View preference is optional. */ }
  }
  function restore() {
    const target = document.getElementById(location.hash.slice(1));
    let remembered = null;
    try { remembered = document.getElementById(sessionStorage.getItem(storageKey)); } catch (_) { /* No storage required. */ }
    activate(panelFor(target) || remembered);
  }
  function choose(tab, focus = false) {
    if (location.hash !== tab.hash) history.pushState(null, '', tab.hash);
    activate(document.getElementById(tab.hash.slice(1)), focus);
  }
  tabs.forEach(tab => tab.addEventListener('click', event => {
    event.preventDefault(); choose(tab);
  }));
  index.addEventListener('keydown', event => {
    const position = tabs.indexOf(event.target);
    if (position < 0) return;
    let next;
    if (event.key === 'ArrowRight') next = (position + 1) % tabs.length;
    else if (event.key === 'ArrowLeft') next = (position + tabs.length - 1) % tabs.length;
    else if (event.key === 'Home') next = 0;
    else if (event.key === 'End') next = tabs.length - 1;
    else if (event.key === ' ') next = position;
    else return;
    event.preventDefault(); choose(tabs[next], true);
  });
  // A required field on another tab must be exposed before native validation focuses it.
  document.addEventListener('invalid', event => {
    const panel = panelFor(event.target);
    if (panel) activate(panel);
  }, true);
  window.addEventListener('hashchange', restore);
  window.addEventListener('popstate', restore);
  restore();
})();
