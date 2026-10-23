'use strict';
// Local form state only. The existing explicit submit handler performs the sole POST.
for (const form of document.querySelectorAll('[data-model-price-form]')) {
  const mode = form.querySelector('[data-model-price-mode]');
  if (!mode) continue;
  const official = form.querySelector('[data-official-price-fields]');
  const consent = official.querySelector('[name=estimate_consent]');
  const manual = form.querySelector('[data-manual-price-confirmation]');
  const price = form.querySelector('[name=price_per_second]');
  const durations = form.querySelector('[name=durations]');
  const submit = form.querySelector('button[type=submit]');
  const originalLabel = submit.textContent;
  const update = () => {
    const automatic = mode.value === 'official';
    official.hidden = !automatic;
    consent.required = automatic;
    consent.disabled = !automatic;
    if (manual) manual.hidden = automatic;
    price.readOnly = automatic;
    price.setAttribute('aria-readonly', String(automatic));
    price.placeholder = automatic ? '등록 시 공식 견적으로 자동 입력' : '';
    const lengths = new Set(durations.value.normalize('NFKC').split(',').map(v => v.trim()).filter(Boolean));
    form.querySelector('[data-model-quote-count]').textContent = `최대 ${lengths.size}회 조회 · `;
    const evidence = form.querySelector('[data-model-price-evidence]');
    if (evidence) {
      const matches = form.querySelector('[name=path]').value.trim() === evidence.dataset.quotedPath &&
        form.querySelector('[name=resolution]').value === evidence.dataset.quotedResolution &&
        [...lengths].sort((a,b)=>Number(a)-Number(b)).join(',') === evidence.dataset.quotedDurations &&
        Number(price.value) === Number(evidence.dataset.quotedPrice);
      evidence.querySelector('[data-price-conditions-changed]').hidden = matches;
    }
    submit.textContent = automatic ? `견적 조회 후 ${originalLabel}` : originalLabel;
  };
  mode.addEventListener('change', () => { consent.checked = false; update(); });
  for (const input of form.querySelectorAll('[name=path],[name=resolution],[name=durations],[name=price_per_second]')) {
    input.addEventListener('input', () => { consent.checked = false; update(); });
    input.addEventListener('change', () => { consent.checked = false; update(); });
  }
  update();
}
