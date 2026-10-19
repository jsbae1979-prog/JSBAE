"use strict";
// Presentation only: no POST, provider calls, approvals or automatic playback.
const dashboardPlayer = document.querySelector('[data-dashboard-player]');
document.querySelectorAll('[data-dash-video]').forEach(link => {
  link.addEventListener('click', event => {
    const id = link.dataset.videoId;
    const draft = link.dataset.draftId;
    if (!dashboardPlayer || !/^[1-9]\d*$/.test(id) || !/^[1-9]\d*$/.test(draft)) return;
    event.preventDefault();
    dashboardPlayer.pause();
    dashboardPlayer.removeAttribute('src');
    dashboardPlayer.querySelector('source').src = `/video/jobs/${id}/file`;
    dashboardPlayer.poster = `/video/jobs/${id}/thumbnail`;
    dashboardPlayer.setAttribute('aria-label', `${link.dataset.title} 미리보기`);
    dashboardPlayer.load();
    document.querySelector('.dash-player-ambient').src = dashboardPlayer.poster;
    document.querySelector('[data-dash-ai-warning]').hidden = link.dataset.aiScenes !== 'true';
    document.querySelector('[data-dash-preview-warning]').hidden = link.dataset.previewOnly !== 'true';
    document.querySelector('[data-dash-video-title]').textContent = link.dataset.title;
    document.querySelector('[data-dash-duration]').textContent = link.dataset.duration;
    const targets = {
      'edit': `/ai?draft_id=${draft}`, 'download': `/video/jobs/${id}/file?download=true`,
      'review': `/?video=${id}&publish_platform=unified#workspace-detail`,
      'publish': `/?video=${id}&publish_platform=unified#publish-workspace`,
      'youtube': `/?video=${id}#youtube-publish`,
      'instagram': `/?video=${id}&publish_platform=instagram#instagram-publish`
    };
    for (const [name, href] of Object.entries(targets)) document.querySelector(`[data-dash-${name}]`).href = href;
    document.querySelectorAll('[data-dash-video]').forEach(item => item.removeAttribute('aria-current'));
    link.setAttribute('aria-current', 'true');
  });
});
document.querySelectorAll('[data-chart-day]').forEach(button => {
  const show = () => { document.querySelector('#chart-readout').textContent = button.dataset.description; };
  button.addEventListener('focus', show);
  button.addEventListener('click', show);
  button.addEventListener('mouseenter', show);
});

// Read-only task details: never write frozen production settings or grant consent.
const workflowOptions = [...document.querySelectorAll('.workflow-option')];
workflowOptions.forEach(option => option.addEventListener('toggle', () => {
  if (option.open) workflowOptions.forEach(other => { if (other !== option) other.open = false; });
}));
document.addEventListener('keydown', event => {
  if (event.key === 'Escape') workflowOptions.forEach(option => {
    if (option.open) { option.open = false; option.querySelector('summary').focus(); }
  });
});
document.addEventListener('click', event => {
  if (!event.target.closest('.workflow-options')) workflowOptions.forEach(option => { option.open = false; });
});
