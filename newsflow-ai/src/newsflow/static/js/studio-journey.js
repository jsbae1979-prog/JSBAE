'use strict';
// Local section navigation only. Does not submit, approve, save or start a job.
(() => {
  const journey = document.querySelector('[data-journey-workspace="true"]');
  if (!journey) return;
  function update() {
    const step = ['#publish-workspace', '#youtube-publish', '#instagram-publish'].includes(location.hash)
      ? 'publish' : 'review';
    journey.querySelectorAll('[data-journey-step]').forEach(link => {
      const current = link.dataset.journeyStep === step;
      if (current) link.setAttribute('aria-current', 'page');
      else link.removeAttribute('aria-current');
      link.querySelector('[data-journey-current]').hidden = !current;
    });
  }
  window.addEventListener('hashchange', update);
  update();
})();
