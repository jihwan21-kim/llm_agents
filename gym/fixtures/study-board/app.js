"use strict";

// First-party synthetic sample application with its own DOM and API behavior.
// This source is served directly from the checked-in fixture without sim.js.
(() => {
  const container = document.getElementById("slots");
  const status = document.getElementById("status");

  function render(slots) {
    container.replaceChildren();
    for (const slot of slots) {
      const row = document.createElement("article");
      row.className = "circle";
      const text = document.createElement("div");
      const heading = document.createElement("h3");
      heading.textContent = slot.title;
      const count = document.createElement("p");
      count.textContent = slot.joined + " / " + slot.capacity + " sample seats";
      text.append(heading, count);
      const button = document.createElement("button");
      button.type = "button";
      button.textContent = slot.joined >= slot.capacity ? "Full" : "Join";
      button.disabled = slot.joined >= slot.capacity;
      button.addEventListener("click", async () => {
        button.disabled = true;
        try {
          const response = await fetch("/api/join", {
            method: "POST",
            headers: {"Content-Type": "application/json"},
            body: JSON.stringify({slot: slot.id}),
          });
          if (!response.ok) throw Error("Local join request failed");
          const result = await response.json();
          status.textContent = "Joined " + slot.title + ". Local count: " + result.count;
          await load();
        } catch (_) {
          status.textContent = "Unable to join this sample activity.";
          button.disabled = false;
        }
      });
      row.append(text, button);
      container.append(row);
    }
  }

  async function load() {
    try {
      const response = await fetch("/api/slots");
      if (!response.ok) throw Error("Local board unavailable");
      const data = await response.json();
      render(data.slots);
    } catch (_) {
      status.textContent = "Sample activity board could not load.";
    }
  }
  load();
})();
