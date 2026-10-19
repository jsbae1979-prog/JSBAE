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

const settingsIndex = document.querySelector('.suite-settings-index');
function markSettingsSection() {
  if (!settingsIndex) return;
  const target = document.getElementById(location.hash.slice(1));
  const id = target?.closest('.settings-card, #advanced')?.id || 'connections';
  settingsIndex.querySelectorAll('a[href^="#"]').forEach(link => {
    const active = link.hash === `#${id}`;
    link.classList.toggle('selected', active);
    if (active) link.setAttribute('aria-current', 'location');
    else link.removeAttribute('aria-current');
  });
}
markSettingsSection();
window.addEventListener('hashchange', markSettingsSection);
