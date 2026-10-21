(() => {
  "use strict";
  const $ = id => document.getElementById(id);
  const state = { messages: [], selected: null, folder: "inbox", read: new Set(), starred: new Set() };
  const shell = $("shell");

  function filteredMessages() {
    const query = $("search").value.trim().toLowerCase();
    return state.messages.filter(m => {
      if (state.folder === "starred" && !state.starred.has(m.id)) return false;
      if (!query) return true;
      return [m.sender, m.subject, m.preview, m.body].some(v =>
        typeof v === "string" && v.toLowerCase().includes(query));
    });
  }

  function drawList() {
    const box = $("list");
    box.replaceChildren();
    const messages = filteredMessages();
    $("listCount").textContent = messages.length + " messages";
    $("inboxCount").textContent = state.messages.filter(m => !state.read.has(m.id)).length || "";
    $("listEmpty").style.display = messages.length ? "none" : "block";
    for (const msg of messages) {
      const item = document.createElement("button");
      item.type = "button";
      item.setAttribute("role", "listitem");
      item.className = "messageRow" +
        (state.selected === msg.id ? " selected" : "") +
        (state.read.has(msg.id) ? "" : " unread");
      const first = document.createElement("div");
      first.className = "messageFirst";
      const sender = document.createElement("span");
      sender.className = "messageSender";
      sender.textContent = msg.sender;
      const time = document.createElement("span");
      time.className = "messageTime";
      time.textContent = msg.time;
      first.append(sender, time);
      const subject = document.createElement("div");
      subject.className = "messageSubject";
      subject.textContent = msg.subject;
      const preview = document.createElement("div");
      preview.className = "messagePreview";
      preview.textContent = msg.preview;
      item.append(first, subject, preview);
      item.addEventListener("click", () => selectMessage(msg.id));
      box.append(item);
    }
  }

  function selectMessage(id) {
    const msg = state.messages.find(x => x.id === id);
    if (!msg) return;
    state.selected = id;
    state.read.add(id);
    // A minimal, first-party GET records only the selected message ID.
    fetch("/read/" + encodeURIComponent(id), {cache:"no-store"}).catch(() => {});
    $("readerEmpty").style.display = "none";
    $("readerContent").style.display = "block";
    $("mailSubject").textContent = msg.subject;
    $("senderAvatar").textContent = msg.sender.slice(0, 1).toUpperCase();
    $("fromName").textContent = msg.sender;
    $("fromAddress").textContent = msg.senderAddress;
    $("date").textContent = msg.time;
    $("bodyText").textContent = "Hello,\n\n" + msg.body;
    $("signature").textContent = "Best regards,\n" + msg.sender;
    $("linkButton").textContent = msg.linkLabel + "  ↗";
    $("linkButton").href = "/open/" + encodeURIComponent(id);
    shell.classList.add("reading");
    drawList();
  }

  document.querySelectorAll("[data-folder]").forEach(btn => {
    btn.addEventListener("click", () => {
      state.folder = btn.dataset.folder;
      document.querySelectorAll("[data-folder]").forEach(n => n.classList.toggle("active", n === btn));
      $("folderTitle").textContent = ({inbox: "Inbox", all: "All mail", starred: "Starred"})[state.folder];
      drawList();
    });
  });
  $("mobileBack").addEventListener("click", () => shell.classList.remove("reading"));
  $("search").addEventListener("input", drawList);

  fetch("/api/messages", {cache:"no-store"})
    .then(response => {
      if (!response.ok) throw new Error("Inbox unavailable");
      return response.json();
    }).then(data => {
      if (!Array.isArray(data)) throw new Error("Unexpected inbox response");
      state.messages = data.filter(row => typeof row.id === "string" &&
        typeof row.subject === "string" && typeof row.body === "string");
      drawList();
    }).catch(error => {
      $("listEmpty").textContent = error.message;
      $("listEmpty").style.display = "block";
    });
})();
