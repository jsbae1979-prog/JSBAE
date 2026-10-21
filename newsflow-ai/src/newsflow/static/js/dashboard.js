"use strict";
// Filter stored news in this panel without navigating away or resetting production inputs.
const dashboardNewsList = document.querySelector('[data-dash-news-list]');
const dashboardNewsStatus = document.querySelector('[data-dash-news-status]');
let dashboardNewsRequest = null;
document.querySelectorAll('[data-dash-news-category]').forEach(link => {
  link.addEventListener('click', async event => {
    if (!dashboardNewsList || event.ctrlKey || event.metaKey || event.shiftKey || event.altKey) return;
    event.preventDefault();
    if (dashboardNewsRequest) dashboardNewsRequest.abort();
    const request = new AbortController();
    dashboardNewsRequest = request;
    dashboardNewsList.setAttribute('aria-busy', 'true');
    dashboardNewsStatus.textContent = '보관 뉴스 불러오는 중';
    try {
      const response = await fetch(`/dashboard/news?category=${encodeURIComponent(link.dataset.dashNewsCategory)}`, {
        credentials: 'same-origin', signal: request.signal, headers: {'Accept': 'text/html'}
      });
      if (!response.ok || !response.headers.get('Content-Type')?.includes('text/html')) throw new Error();
      const html = await response.text();
      if (dashboardNewsRequest !== request) return;
      dashboardNewsList.innerHTML = html;
      document.querySelectorAll('[data-dash-news-category]').forEach(item => {
        item.classList.toggle('selected', item === link);
        if (item === link) item.setAttribute('aria-current', 'true');
        else item.removeAttribute('aria-current');
      });
      dashboardNewsStatus.textContent = `${link.textContent} · 보관 뉴스 · 새 수집·AI 호출 없음`;
    } catch (error) {
      if (error.name !== 'AbortError') dashboardNewsStatus.textContent = '목록을 불러오지 못했습니다. 기존 목록은 유지됩니다.';
    } finally {
      if (dashboardNewsRequest === request) dashboardNewsList.removeAttribute('aria-busy');
    }
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
