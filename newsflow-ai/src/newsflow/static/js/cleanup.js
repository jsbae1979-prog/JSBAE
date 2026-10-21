"use strict";
// Native modal top layer escapes card overflow/stacking contexts.
document.querySelectorAll('details.cleanup-control').forEach(details => {
  details.addEventListener('toggle', () => {
    if (!details.open || details.dataset.modalActive === 'true') return;
    const form = details.querySelector('form');
    if (!form) return;
    details.dataset.modalActive = 'true';
    const dialog = document.createElement('dialog');
    dialog.className = 'cleanup-dialog';
    dialog.setAttribute('aria-label', '삭제 확인');
    const title = document.createElement('h2');
    title.textContent = '삭제할 항목을 확인해 주세요';
    const cancel = document.createElement('button');
    cancel.type = 'button';
    cancel.textContent = '취소';
    cancel.addEventListener('click', () => dialog.close());
    dialog.append(title, form, cancel);
    document.body.append(dialog);
    dialog.addEventListener('close', () => {
      details.append(form);
      form.reset();
      details.open = false;
      details.dataset.modalActive = 'false';
      dialog.remove();
      details.querySelector('summary').focus();
    }, {once:true});
    dialog.showModal();
    cancel.focus();
  });
});
// Same-origin, explicit confirmation only. Never retry an unknown removal result.
document.querySelectorAll('[data-cleanup-form]').forEach(form => {
  form.addEventListener('submit', async event => {
    event.preventDefault();
    const button = event.submitter || form.querySelector('button');
    if (button.disabled) return;
    const payload = new FormData(form);
    if (button.name) payload.set(button.name, button.value);
    const error = form.querySelector('[data-cleanup-error]');
    error.hidden = true;
    button.disabled = true;
    try {
      const response = await fetch(form.action, {method:'POST', body:payload, credentials:'same-origin'});
      if (response.ok && response.redirected && new URL(response.url).origin === location.origin) {
        location.assign(response.url);
        return;
      }
      let detail;
      try { detail = (await response.json()).detail; } catch (_) { /* Fixed fallback below. */ }
      error.textContent = typeof detail === 'string' ? detail : '처리 결과를 확인하지 못했습니다. 휴지 보관을 확인해 주세요.';
      error.hidden = false;
      if (response.status >= 400 && response.status < 500) button.disabled = false;
    } catch (_) {
      error.textContent = '응답을 받지 못했습니다. 자동 재시도하지 않습니다. 휴지 보관에서 결과를 확인해 주세요.';
      error.hidden = false;
    }
  });
});
