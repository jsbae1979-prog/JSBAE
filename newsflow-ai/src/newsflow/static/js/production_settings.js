"use strict";
// Only changes visible controls. Saving, checking, logging in and generating stay explicit actions.
(() => {
  const form = document.getElementById('production-preferences');
  if (!form) return;
  const provider = form.elements.namedItem('provider');
  const voice = form.elements.namedItem('voice');
  const video = form.elements.namedItem('video_provider');
  const reveal = () => {
    for (const element of document.querySelectorAll('[data-ai-provider]')) {
      element.hidden = element.dataset.aiProvider !== provider.value;
    }
    for (const element of document.querySelectorAll('[data-voice-provider]')) {
      element.hidden = element.dataset.voiceProvider !== voice.selectedOptions[0].dataset.engine;
    }
    for (const element of document.querySelectorAll('[data-video-provider]')) {
      element.hidden = element.dataset.videoProvider !== video.value;
    }
  };
  for (const element of form.elements) {
    element.addEventListener('change', () => {
      document.getElementById('production-unsaved').hidden = false;
      reveal();
    });
  }
  reveal();
})();
