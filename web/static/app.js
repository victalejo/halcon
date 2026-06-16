"use strict";

const $ = (sel) => document.querySelector(sel);

const state = {
  mode: "username",
  results: [],
  target: "",
  kind: "username",
  source: null, // active EventSource
};

const els = {
  form: $("#search-form"),
  query: $("#query"),
  searchBtn: $("#search-btn"),
  cancelBtn: $("#cancel-btn"),
  modes: document.querySelectorAll(".mode"),
  nsfw: $("#nsfw"),
  timeout: $("#timeout"),
  concurrency: $("#concurrency"),
  progressSection: $("#progress-section"),
  progressLabel: $("#progress-label"),
  progressCount: $("#progress-count"),
  progressBar: $("#progress-bar"),
  resultsSection: $("#results-section"),
  results: $("#results"),
  foundCount: $("#found-count"),
  emptyState: $("#empty-state"),
  exportGroup: $("#export-group"),
  aiBtn: $("#ai-btn"),
  aiPanel: $("#ai-panel"),
  listStatus: $("#list-status"),
  toast: $("#toast"),
};

// --------------------------------- helpers ----------------------------------
function toast(message, isError = false) {
  els.toast.textContent = message;
  els.toast.classList.toggle("error", isError);
  els.toast.hidden = false;
  clearTimeout(toast._t);
  toast._t = setTimeout(() => (els.toast.hidden = true), 4000);
}

// HTML-escape for both text and attribute contexts (covers quotes, unlike a
// textContent round-trip which leaves " and ' intact).
function esc(value) {
  return value == null
    ? ""
    : String(value)
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;")
        .replace(/'/g, "&#39;");
}

// Only http/https URLs may become clickable links (blocks javascript:, data:…).
function safeUrl(url) {
  const str = String(url || "");
  return /^https?:\/\//i.test(str) ? str : null;
}

function setSearching(active) {
  els.searchBtn.disabled = active;
  els.query.disabled = active;
  els.cancelBtn.hidden = !active;
}

// --------------------------------- mode --------------------------------------
els.modes.forEach((btn) => {
  btn.addEventListener("click", () => {
    els.modes.forEach((b) => b.classList.remove("active"));
    btn.classList.add("active");
    state.mode = btn.dataset.mode;
    els.query.placeholder =
      state.mode === "email" ? "Enter an email…" : "Enter a username…";
    els.query.type = state.mode === "email" ? "email" : "text";
  });
});

// --------------------------------- search ------------------------------------
els.form.addEventListener("submit", (e) => {
  e.preventDefault();
  startSearch();
});

els.cancelBtn.addEventListener("click", () => stopSearch("Search stopped."));

function startSearch() {
  const q = els.query.value.trim();
  if (!q) return;
  if (state.mode === "email" && !q.includes("@")) {
    toast("Please enter a valid email address.", true);
    return;
  }

  stopSearch(); // close any prior stream
  state.results = [];
  state.target = q;
  state.kind = state.mode;

  els.results.innerHTML = "";
  els.aiPanel.hidden = true;
  els.aiPanel.innerHTML = "";
  els.exportGroup.hidden = true;
  els.aiBtn.hidden = true;
  els.emptyState.hidden = true;
  els.foundCount.textContent = "0";
  els.resultsSection.hidden = false;
  els.progressSection.hidden = false;
  els.progressBar.style.width = "0%";
  els.progressLabel.textContent = "Starting…";
  els.progressCount.textContent = "";

  const params = new URLSearchParams({
    q,
    nsfw: els.nsfw.checked ? "true" : "false",
    timeout: String(els.timeout.value || 30),
    concurrency: String(els.concurrency.value || 30),
  });
  const url = `/api/search/${state.kind}?${params.toString()}`;

  setSearching(true);
  const source = new EventSource(url);
  state.source = source;

  source.onmessage = (event) => {
    let data;
    try {
      data = JSON.parse(event.data);
    } catch {
      return;
    }
    handleEvent(data);
  };

  source.onerror = () => {
    // EventSource fires onerror on normal close too; only warn if still running.
    if (state.source) {
      stopSearch();
      if (!state.results.length && els.progressBar.style.width !== "100%") {
        toast("Connection to the server was lost.", true);
      }
    }
  };
}

function handleEvent(data) {
  switch (data.type) {
    case "start":
      els.progressLabel.textContent = `Scanning ${esc(data.total)} sites for "${esc(
        data.target
      )}"`;
      break;
    case "progress":
    case "found":
      updateProgress(data.completed, data.total);
      if (data.type === "found" && data.result) addResult(data.result);
      break;
    case "done":
      finishSearch(data);
      break;
    case "error":
      toast(data.message || "Search error.", true);
      stopSearch();
      break;
  }
}

function updateProgress(completed, total) {
  const pct = total ? Math.round((completed / total) * 100) : 0;
  els.progressBar.style.width = `${pct}%`;
  els.progressCount.textContent = `${completed}/${total} (${pct}%)`;
}

function addResult(result) {
  state.results.push(result);
  els.foundCount.textContent = String(state.results.length);
  els.results.appendChild(renderCard(result));
}

function renderCard(result) {
  const card = document.createElement("div");
  card.className = "result-card";

  let metaHtml = "";
  if (Array.isArray(result.metadata) && result.metadata.length) {
    metaHtml =
      '<dl class="result-meta">' +
      result.metadata
        .map((m) => {
          const name = esc(m && m.name);
          const value =
            m && m.value != null ? esc(m.value) : esc(JSON.stringify(m));
          return `<dt>${name}</dt><dd>${value}</dd>`;
        })
        .join("") +
      "</dl>";
  }

  const url = safeUrl(result.url);
  const urlHtml = url
    ? `<a class="result-url" href="${esc(url)}" target="_blank" rel="noopener">${esc(url)}</a>`
    : `<span class="result-url">${esc(result.url)}</span>`;

  card.innerHTML = `
    <div class="result-top">
      <span class="result-name">${esc(result.name)}</span>
      <span class="result-cat">${esc(result.category || "—")}</span>
    </div>
    ${urlHtml}
    ${metaHtml}
  `;
  return card;
}

function finishSearch(data) {
  els.progressBar.style.width = "100%";
  els.progressLabel.textContent = "Search complete";
  els.progressCount.textContent = `${data.found_count} found`;
  stopSearch();

  if (!state.results.length) {
    els.emptyState.hidden = false;
    return;
  }
  els.exportGroup.hidden = false;
  if (state.results.length >= 3) els.aiBtn.hidden = false;
}

function stopSearch(message) {
  if (state.source) {
    state.source.close();
    state.source = null;
  }
  setSearching(false);
  if (message) toast(message);
}

// --------------------------------- export ------------------------------------
els.exportGroup.addEventListener("click", async (e) => {
  const btn = e.target.closest("button[data-fmt]");
  if (!btn) return;
  await exportResults(btn.dataset.fmt, btn);
});

async function exportResults(fmt, btn) {
  if (!state.results.length) return;
  btn.disabled = true;
  try {
    const res = await fetch("/api/export", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        format: fmt,
        kind: state.kind,
        target: state.target,
        results: state.results,
        ai_analysis: state.aiAnalysis || null,
      }),
    });
    if (!res.ok) {
      const detail = await res.json().catch(() => ({}));
      throw new Error(detail.detail || `Export failed (${res.status})`);
    }
    const blob = await res.blob();
    triggerDownload(blob, fmt, res.headers.get("Content-Disposition"));
  } catch (err) {
    toast(err.message || "Export failed.", true);
  } finally {
    btn.disabled = false;
  }
}

function triggerDownload(blob, fmt, disposition) {
  let filename = `halcon_${state.target}.${fmt}`;
  if (disposition) {
    const match = /filename="?([^"]+)"?/.exec(disposition);
    if (match) filename = match[1];
  }
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}

// --------------------------------- AI ----------------------------------------
els.aiBtn.addEventListener("click", async () => {
  const siteNames = state.results.map((r) => r.name).filter(Boolean);
  els.aiBtn.disabled = true;
  els.aiBtn.textContent = "Analyzing…";
  try {
    const res = await fetch("/api/ai/analyze", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ site_names: siteNames }),
    });
    const data = await res.json();
    if (!data.available) {
      toast(data.message || "AI is not configured.", true);
      return;
    }
    if (!data.ok) {
      toast(data.message || "AI analysis failed.", true);
      return;
    }
    state.aiAnalysis = data.result;
    renderAI(data.result, data.remaining_quota);
  } catch (err) {
    toast(err.message || "AI request failed.", true);
  } finally {
    els.aiBtn.disabled = false;
    els.aiBtn.textContent = "✨ AI analysis";
  }
});

function renderAI(result, quota) {
  const blocks = [];
  if (result.summary)
    blocks.push(`<div class="ai-block"><h3>Summary</h3><p>${esc(result.summary)}</p></div>`);
  if (result.categorization)
    blocks.push(
      `<div class="ai-block"><h3>Profile type</h3><p>${esc(result.categorization)}</p></div>`
    );
  if (Array.isArray(result.insights) && result.insights.length)
    blocks.push(
      `<div class="ai-block"><h3>Insights</h3><ul>${result.insights
        .map((i) => `<li>${esc(i)}</li>`)
        .join("")}</ul></div>`
    );
  if (Array.isArray(result.risk_flags) && result.risk_flags.length)
    blocks.push(
      `<div class="ai-block"><h3>Risk flags</h3><ul>${result.risk_flags
        .map((i) => `<li>${esc(i)}</li>`)
        .join("")}</ul></div>`
    );
  if (Array.isArray(result.tags) && result.tags.length)
    blocks.push(
      `<div class="ai-block"><h3>Tags</h3><div class="tags">${result.tags
        .map((t) => `<span class="tag">${esc(t)}</span>`)
        .join("")}</div></div>`
    );
  if (quota != null)
    blocks.push(`<p class="muted">${esc(quota)} AI queries left today.</p>`);

  els.aiPanel.innerHTML = blocks.join("") || "<p class='muted'>No AI output.</p>";
  els.aiPanel.hidden = false;
}

// --------------------------------- health ------------------------------------
(async function checkHealth() {
  try {
    const res = await fetch("/api/health");
    const data = await res.json();
    if (data.site_list_present) {
      els.listStatus.textContent = "site list ready";
      els.listStatus.classList.add("ok");
    } else {
      els.listStatus.textContent = "downloading list…";
      els.listStatus.classList.add("warn");
    }
  } catch {
    els.listStatus.textContent = "offline";
    els.listStatus.classList.add("warn");
  }
})();
