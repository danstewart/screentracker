// ---------- DOM helpers ----------
const $ = (sel, root = document) => root.querySelector(sel);
const $$ = (sel, root = document) => Array.from(root.querySelectorAll(sel));

// ---------- State ----------
let currentMoveShowId = null; // when "Move" is clicked

// ---------- Search ----------
const searchInput = $("#search-input");
const searchResults = $("#search-results");

let searchTimer = null;

searchInput.addEventListener("input", (e) => {
  const q = e.target.value.trim();
  clearTimeout(searchTimer);

  if (!q) {
    searchResults.classList.add("hidden");
    searchResults.innerHTML = "";
    return;
  }

  searchTimer = setTimeout(() => doSearch(q), 280);
});

document.addEventListener("click", (e) => {
  if (!searchResults.contains(e.target) && e.target !== searchInput) {
    searchResults.classList.add("hidden");
  }
});

async function doSearch(q) {
  searchResults.classList.remove("hidden");
  searchResults.innerHTML = `<div class="search-loading">Searching…</div>`;

  try {
    const r = await fetch(`/api/search?q=${encodeURIComponent(q)}`);
    const data = await r.json();

    if (data.error) {
      searchResults.innerHTML = `<div class="search-empty">${escapeHtml(data.error)}</div>`;
      return;
    }

    if (!data.results.length) {
      searchResults.innerHTML = `<div class="search-empty">No results for "${escapeHtml(q)}"</div>`;
      return;
    }

    searchResults.innerHTML = data.results.map(renderResult).join("");

    $$(".search-result").forEach((el, idx) => {
      el.addEventListener("click", () => {
        addShow(data.results[idx]);
      });
    });
  } catch (err) {
    searchResults.innerHTML = `<div class="search-empty">Search failed: ${escapeHtml(err.message)}</div>`;
  }
}

function renderResult(r) {
  const poster = r.poster_url
    ? `<img src="${escapeAttr(r.poster_url)}" alt="" />`
    : `<div class="placeholder">${escapeHtml((r.title || "?")[0].toUpperCase())}</div>`;

  const badge = r.tvdb_type === "movie"
    ? `<span class="badge movie">Movie</span>`
    : `<span class="badge series">Series</span>`;

  const metaParts = [];
  if (r.year) metaParts.push(r.year);
  if (r.network) metaParts.push(r.network);
  if (r.country) metaParts.push(r.country.toUpperCase());

  return `
    <div class="search-result">
      ${poster}
      <div class="info">
        <h4>${escapeHtml(r.title)} ${badge}</h4>
        <div class="meta">${metaParts.map(escapeHtml).join(" · ")}</div>
        <div class="overview">${escapeHtml(r.overview || "")}</div>
      </div>
    </div>
  `;
}

// ---------- Add modal ----------
const modal = $("#genre-modal");
const modalPreview = $("#modal-preview");
const genreInput = $("#genre-input");
const genreSuggestions = $("#genre-suggestions");
const modalConfirm = $("#modal-confirm");
const modalCancel = $("#modal-cancel");

async function refreshGenreSuggestions() {
  const r = await fetch("/api/genres");
  const data = await r.json();
  genreSuggestions.innerHTML = data.genres
    .map((g) => `<option value="${escapeAttr(g.name)}">`)
    .join("");
}

async function submitShow(payload) {
  const r = await fetch("/api/shows", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  const data = await r.json();
  sessionStorage.setItem("flash_added", JSON.stringify({
    title: data.show.title,
    genre: data.genre_name,
    showId: data.show.id,
  }));
  location.reload();
}

async function addShow(result) {
  searchResults.classList.add("hidden");
  searchInput.value = "";
  await submitShow({ ...result, genre_name: "" });
}

function openMoveModal(showId, currentTitle, currentGenre) {
  currentMoveShowId = showId;

  modalPreview.innerHTML = `
    <div class="preview-info">
      <h4>${escapeHtml(currentTitle)}</h4>
    </div>
  `;

  genreInput.value = currentGenre || "";
  refreshGenreSuggestions();
  modal.classList.remove("hidden");
  setTimeout(() => {
    genreInput.focus();
    genreInput.select();
  }, 50);
}

modalCancel.addEventListener("click", () => modal.classList.add("hidden"));
modal.addEventListener("click", (e) => {
  if (e.target === modal) modal.classList.add("hidden");
});

modalConfirm.addEventListener("click", async () => {
  const genreName = genreInput.value.trim();
  if (!genreName) {
    genreInput.focus();
    return;
  }

  if (currentMoveShowId) {
    await fetch(`/api/shows/${currentMoveShowId}/genre`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ genre_name: genreName }),
    });
  }

  modal.classList.add("hidden");
  location.reload();
});

genreInput.addEventListener("keydown", (e) => {
  if (e.key === "Enter") modalConfirm.click();
});

// ---------- View tabs ----------
const viewTabs = $$(".view-tab");
const watchingLibrary = $("#watching-library");
const watchedLibrary = $("#watched-library");

function setView(view) {
  localStorage.setItem("library-view", view);
  viewTabs.forEach((t) => t.classList.toggle("active", t.dataset.view === view));
  watchingLibrary.classList.toggle("hidden", view !== "watching");
  watchedLibrary.classList.toggle("hidden", view !== "watched");
}

setView(localStorage.getItem("library-view") || "watching");
viewTabs.forEach((tab) => tab.addEventListener("click", () => setView(tab.dataset.view)));

// ---------- Card menu ----------
function closeAllMenus() {
  $$(".show-menu-dropdown").forEach((d) => {
    d.classList.add("hidden");
    d.closest(".show-card").style.zIndex = "";
  });
}

// ---------- Card actions (event delegation) ----------
document.addEventListener("click", async (e) => {
  // Toggle overflow menu
  if (e.target.classList.contains("show-menu-btn")) {
    const dropdown = e.target.nextElementSibling;
    const isOpen = !dropdown.classList.contains("hidden");
    closeAllMenus();
    if (!isOpen) {
      dropdown.classList.remove("hidden");
      e.target.closest(".show-card").style.zIndex = 10;
    }
    return;
  }

  // Close menus when clicking outside
  if (!e.target.closest(".show-menu")) {
    closeAllMenus();
  }

  // Delete show
  if (e.target.classList.contains("show-delete")) {
    const id = e.target.dataset.showId;
    if (!confirm("Remove this from your library?")) return;
    await fetch(`/api/shows/${id}`, { method: "DELETE" });
    const card = e.target.closest(".show-card");
    const section = card.closest(".genre-block");
    card.remove();
    if (section && section.querySelectorAll(".show-card").length === 0) {
      section.remove();
    }
    return;
  }

  // Watch / Unwatch
  if (e.target.classList.contains("show-watched") || e.target.classList.contains("show-unwatch")) {
    const id = e.target.dataset.showId;
    const watched = e.target.classList.contains("show-watched");
    await fetch(`/api/shows/${id}/watched`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ watched }),
    });
    const card = e.target.closest(".show-card");
    const section = card.closest(".genre-block");
    card.remove();
    if (section && section.querySelectorAll(".show-card").length === 0) {
      section.remove();
    }
    return;
  }

  // Edit genre
  if (e.target.classList.contains("show-move")) {
    const card = e.target.closest(".show-card");
    const id = e.target.dataset.showId;
    const title = $(".show-title", card).textContent;
    const section = card.closest(".genre-block");
    const currentGenre = section && !section.classList.contains("orphan-block")
      ? $(".genre-header h2", section).textContent
      : "";
    openMoveModal(id, title, currentGenre);
    return;
  }

});

// ---------- Manual add ----------
const manualModal = $("#manual-modal");
const manualTitle = $("#manual-title");
const manualGenre = $("#manual-genre");
const manualImdb = $("#manual-imdb");
const manualGenreSuggestions = $("#manual-genre-suggestions");

async function openManualModal() {
  manualTitle.value = "";
  manualGenre.value = "";
  manualImdb.value = "";
  const r = await fetch("/api/genres");
  const data = await r.json();
  manualGenreSuggestions.innerHTML = data.genres
    .map((g) => `<option value="${escapeAttr(g.name)}">`)
    .join("");
  manualModal.classList.remove("hidden");
  setTimeout(() => manualTitle.focus(), 50);
}

$("#add-manual-btn").addEventListener("click", openManualModal);
$("#manual-cancel").addEventListener("click", () => manualModal.classList.add("hidden"));
manualModal.addEventListener("click", (e) => {
  if (e.target === manualModal) manualModal.classList.add("hidden");
});

$("#manual-confirm").addEventListener("click", async () => {
  const title = manualTitle.value.trim();
  const genre = manualGenre.value.trim();
  if (!title) { manualTitle.focus(); return; }
  if (!genre) { manualGenre.focus(); return; }

  manualModal.classList.add("hidden");
  await submitShow({
    title,
    genre_name: genre,
    imdb_url: manualImdb.value.trim(),
    tvdb_id: "",
    tvdb_type: "",
    year: "",
    overview: "",
    poster_url: "",
  });
});

manualImdb.addEventListener("keydown", (e) => {
  if (e.key === "Enter") $("#manual-confirm").click();
});

// ---------- Flash toast ----------
function showFlash(title, genre, showId) {
  const toast = document.createElement("div");
  toast.className = "flash-toast";
  toast.innerHTML = `
    <span class="flash-msg">Added <strong>${escapeHtml(title)}</strong>${genre ? ` under <strong>${escapeHtml(genre)}</strong>` : ""}</span>
    <button class="flash-edit">Edit genre</button>
    <button class="flash-close">×</button>
  `;
  document.body.appendChild(toast);
  requestAnimationFrame(() => toast.classList.add("flash-show"));

  const dismiss = () => {
    toast.classList.remove("flash-show");
    toast.addEventListener("transitionend", () => toast.remove(), { once: true });
  };

  const timer = setTimeout(dismiss, 6000);

  toast.querySelector(".flash-close").addEventListener("click", () => {
    clearTimeout(timer);
    dismiss();
  });

  toast.querySelector(".flash-edit").addEventListener("click", () => {
    clearTimeout(timer);
    dismiss();
    openMoveModal(showId, title, genre);
  });
}

const flashData = sessionStorage.getItem("flash_added");
if (flashData) {
  sessionStorage.removeItem("flash_added");
  const { title, genre, showId } = JSON.parse(flashData);
  showFlash(title, genre, showId);
}

// ---------- Utils ----------
function escapeHtml(s) {
  if (s == null) return "";
  return String(s)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}
function escapeAttr(s) {
  return escapeHtml(s);
}
