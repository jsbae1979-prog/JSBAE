// Read-only status refresh. Never dispatch or retry work from the browser timer.
(() => {
  if (!document.querySelector('.schedule-page')) return;
  let busy = false;
  window.setInterval(async () => {
    if (busy || document.hidden || document.activeElement?.closest('form,details')) return;
    busy = true;
    try {
      const response = await fetch('/schedules', {cache: 'no-store', credentials: 'same-origin'});
      if (!response.ok) return;
      const next = new DOMParser().parseFromString(await response.text(), 'text/html');
      if (document.activeElement?.closest('form,details')) return;
      for (const id of ['schedule-list', 'schedule-history']) {
        const current = document.getElementById(id), replacement = next.getElementById(id);
        if (current && replacement && !current.querySelector('details[open]')) current.replaceWith(replacement);
      }
      document.dispatchEvent(new Event('newsflow:updated'));
    } catch (_) { /* Current status stays visible. Manual refresh remains available. */ }
    finally { busy = false; }
  }, 5000);
})();
