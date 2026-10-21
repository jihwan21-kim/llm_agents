"use strict";

// Synthetic fixture that changes the DOM without navigating to another page.
// It deliberately makes no fetch, XHR, WebSocket or external requests.
(() => {
  const items = {
    notebook: { name: "Notebook", detail: "A plain paper notebook" },
    pen: { name: "Pen", detail: "A blue ink pen" },
    lamp: { name: "Lamp", detail: "An adjustable desk lamp" },
  };

  let selected = "notebook";
  let basketCount = 0;
  const buttons = [...document.querySelectorAll("button[data-item]")];
  const title = document.getElementById("selected-name");
  const detail = document.getElementById("selected-detail");
  const count = document.getElementById("basket-count");
  const status = document.getElementById("last-action");

  for (const button of buttons) {
    button.addEventListener("click", () => {
      const id = button.dataset.item;
      if (!Object.prototype.hasOwnProperty.call(items, id)) return;
      selected = id;
      title.textContent = items[id].name;
      detail.textContent = items[id].detail;
      for (const option of buttons) {
        option.setAttribute("aria-pressed", String(option === button));
      }
      status.textContent = "Selected " + id;
    });
  }

  document.getElementById("add-item").addEventListener("click", () => {
    basketCount++;
    count.textContent = "Basket: " + basketCount + " items";
    status.textContent = "Added " + selected;
  });
})();
