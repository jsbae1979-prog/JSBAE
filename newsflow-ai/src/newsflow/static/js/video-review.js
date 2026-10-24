'use strict';
// Read-only progressive enhancement. Never submit, check approvals or request new media.
document.querySelectorAll('[data-video-review-details]').forEach(details => {
  if (typeof HTMLDialogElement === 'undefined') return;
  const content = details.querySelector('[data-video-review-content]');
  const summary = details.querySelector('summary');
  if (!content || !summary) return;
  const trigger = document.createElement('button');
  trigger.type = 'button';
  trigger.className = 'button video-review-trigger';
  trigger.setAttribute('aria-haspopup', 'dialog');
  trigger.setAttribute('aria-expanded', 'false');
  trigger.append(...[...summary.childNodes].map(node => node.cloneNode(true)));
  const dialog = document.createElement('dialog');
  dialog.className = 'video-review-dialog';
  dialog.setAttribute('aria-labelledby', 'video-review-title');
  const heading = document.createElement('h2');
  heading.id = 'video-review-title';
  heading.textContent = '영상 정보·출처';
  const close = document.createElement('button');
  close.type = 'button';
  close.className = 'video-review-close';
  close.textContent = '닫기';
  const header = document.createElement('header');
  header.append(heading, close);
  dialog.append(header, content);
  document.body.append(dialog);
  details.before(trigger);
  details.hidden = true;
  trigger.addEventListener('click', () => {
    dialog.showModal();
    trigger.setAttribute('aria-expanded', 'true');
    close.focus();
  });
  close.addEventListener('click', () => dialog.close());
  dialog.addEventListener('close', () => {
    trigger.setAttribute('aria-expanded', 'false');
    trigger.focus();
  });
});
