"use strict";

// Synthetic fixture that changes the DOM without navigating to another page.
// When served by the approved isolated proxy, its one fixed same-origin POST
// produces a local metadata-only receipt. No user data or external requests.
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

  document.getElementById("add-item").addEventListener("click", async () => {
    basketCount++;
    count.textContent = "Basket: " + basketCount + " items";
    status.textContent = "Added " + selected + " (receipt pending)";
    try {
      // Fixed synthetic metadata, never input contents or personal fields.
      const response = await fetch("/__mock_capture/fixture-receipt", {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({event: "basket_add", sequence: basketCount}),
      });
      if (!response.ok) throw Error("Local fixture receipt unavailable");
      status.textContent = "Added " + selected + " (recorded locally)";
    } catch (_) {
      status.textContent = "Added " + selected + " (local receipt unavailable)";
    }
  });
})();
