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
