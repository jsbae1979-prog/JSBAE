"use strict";
// Include operator instructions in print/PDF without changing the reader's screen state.
let guidePrintState = null;
window.addEventListener("beforeprint", () => {
  if (guidePrintState) return;
  guidePrintState = Array.from(document.querySelectorAll(".guide-body details"), (element) => [element, element.open]);
  guidePrintState.forEach(([element]) => { element.open = true; });
});
window.addEventListener("afterprint", () => {
  if (!guidePrintState) return;
  guidePrintState.forEach(([element, wasOpen]) => { element.open = wasOpen; });
  guidePrintState = null;
});
