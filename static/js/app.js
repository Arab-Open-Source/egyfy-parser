import * as api from "./api.js";

const $ = (selector, root = document) => root.querySelector(selector);
const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];

const BLOCK_COLORS = {
  "Text": "#6b7280",
  "Section-Header": "#2563eb",
  "Page-Header": "#9ca3af",
  "Page-Footer": "#9ca3af",
  "List-Group": "#059669",
  "Table": "#7c3aed",
  "Caption": "#0891b2",
  "Footnote": "#b45309",
  "Table-Of-Contents": "#0d9488",
  "Form": "#dc2626",
};

const BLOCK_LABELS = {
  "Text": "Text",
  "Section-Header": "Section header",
  "Page-Header": "Page header",
  "Page-Footer": "Page footer",
  "List-Group": "List",
  "Table": "Table",
  "Caption": "Caption",
  "Footnote": "Footnote",
  "Table-Of-Contents": "Contents",
  "Form": "Form",
};

const STAGES = [
  { key: "text_ms", label: "Text layer", color: "#2563eb" },
  { key: "det_ms", label: "Detect", color: "#7c3aed" },
  { key: "rec_ms", label: "Recognize", color: "#059669" },
  { key: "ocr_ms", label: "Image OCR", color: "#0891b2" },
  { key: "math_ms", label: "Math", color: "#b45309" },
  { key: "order_ms", label: "Reading order", color: "#c2410c" },
];

const SOURCE_LABELS = {
  text: "Text layer",
  ocr: "OCR",
  hybrid: "Text + OCR",
  error: "Error",
};

const MODE_HINTS = {
  auto: "Use the PDF text layer where it is reliable; fall back to OCR elsewhere.",
  ocr: "Ignore the text layer and run OCR on every page.",
  text: "Use the text layer even when its quality checks fail.",
};

const FORMAT_EXTENSIONS = {
  md: "md",
  txt: "txt",
  csv: "csv",
  tables: "zip",
  json: "json",
  html: "html",
  zip: "zip",
};

const state = {
  info: null,
  doc: null,
  pages: new Map(),
  timings: [],
  mode: "auto",
  busy: false,
  runId: 0,
  lastFocused: null,
};

function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>"']/g, (character) => {
    const entities = {
      "&": "&amp;",
      "<": "&lt;",
      ">": "&gt;",
      '"': "&quot;",
      "'": "&#39;",
    };
    return entities[character];
  });
}

function icon(name, extraClass = "") {
  return `<svg class="icon ${extraClass}" aria-hidden="true"><use href="#i-${name}"/></svg>`;
}

function formatNumber(value, digits = 0) {
  return Number(value).toLocaleString("en-US", {
    maximumFractionDigits: digits,
    minimumFractionDigits: 0,
  });
}

function formatBytes(bytes) {
  if (!Number.isFinite(bytes) || bytes <= 0) {
    return "0 B";
  }
  if (bytes < 1024) {
    return `${Math.round(bytes)} B`;
  }
  if (bytes < 1024 * 1024) {
    return `${Math.round(bytes / 1024)} KB`;
  }
  const megabytes = (bytes / (1024 * 1024)).toFixed(1).replace(/\.0$/, "");
  return `${megabytes} MB`;
}

function pluralize(count, singular, plural) {
  return count === 1 ? singular : plural;
}

function setStatus(message, isError = false) {
  const element = $("#status");
  element.textContent = message || "";
  element.classList.toggle("is-error", Boolean(isError && message));
}

function toast(message, type = "success") {
  const element = document.createElement("div");
  element.className = type === "error" ? "toast is-error" : "toast";
  element.innerHTML = icon(type === "error" ? "x" : "check");
  const text = document.createElement("span");
  text.textContent = message;
  element.appendChild(text);
  $("#toasts").append(element);

  setTimeout(() => {
    element.classList.add("is-leaving");
    setTimeout(() => element.remove(), 220);
  }, 3200);
}

function currentTheme() {
  return document.documentElement.dataset.theme === "dark" ? "dark" : "light";
}

function applyTheme(theme) {
  document.documentElement.dataset.theme = theme;
  $("#theme-icon use").setAttribute("href", `#i-${theme === "dark" ? "sun" : "moon"}`);
  const label = theme === "dark" ? "Switch to light theme" : "Switch to dark theme";
  $("#theme").setAttribute("aria-label", label);
  $("#theme").title = label;
  const meta = document.querySelector('meta[name="theme-color"]');
  if (meta) {
    meta.content = theme === "dark" ? "#141613" : "#f6f6f3";
  }
}

function initTheme() {
  applyTheme(currentTheme());
  $("#theme").addEventListener("click", () => {
    const next = currentTheme() === "dark" ? "light" : "dark";
    applyTheme(next);
    try {
      localStorage.setItem("egyfy.theme", next);
    } catch (error) {
      // The theme still applies for this session when storage is unavailable.
    }
  });
}

function collectOptions() {
  const requestedPages = Number.parseInt($("#maxp").value, 10);
  return {
    mode: state.mode,
    clean: $("#clean").checked,
    math: $("#math").checked,
    furniture: $("#furniture").checked,
    pdf_order: $("#pdforder").checked,
    image_ocr: $("#imageocr").checked,
    dpi: Number($("#dpi").value) || 200,
    max_pages: Number.isFinite(requestedPages)
      ? Math.min(500, Math.max(0, requestedPages))
      : 20,
  };
}

function setMode(mode) {
  state.mode = mode;
  $$("#mode button").forEach((button) => {
    const active = button.dataset.value === mode;
    button.classList.toggle("is-active", active);
    button.setAttribute("aria-pressed", String(active));
  });
  $("#modehint").textContent = MODE_HINTS[mode] || "";
}

function initMode() {
  $$("#mode button").forEach((button) => {
    button.addEventListener("click", () => setMode(button.dataset.value));
  });
}

function initDisplayOptions() {
  const apply = () => {
    $$(".display-toggle").forEach((input) => {
      $("#out").classList.toggle(`hide-${input.dataset.layer}`, !input.checked);
    });
  };
  $$(".display-toggle").forEach((input) => input.addEventListener("change", apply));
  apply();
}

function buildLegend() {
  $("#legend").innerHTML = Object.entries(BLOCK_LABELS)
    .map(
      ([label, title]) =>
        `<span class="legend-item"><i class="legend-swatch" style="background:${BLOCK_COLORS[label]}"></i>${escapeHtml(title)}</span>`
    )
    .join("");
}

function initDropzone() {
  const dropzone = $("#drop");
  const input = $("#file");
  let dragDepth = 0;

  input.addEventListener("change", () => {
    const file = input.files?.[0];
    input.value = "";
    if (file) {
      start(file);
    }
  });

  dropzone.addEventListener("keydown", (event) => {
    if (event.key === "Enter" || event.key === " ") {
      event.preventDefault();
      input.click();
    }
  });

  dropzone.addEventListener("dragenter", (event) => {
    event.preventDefault();
    dragDepth += 1;
    dropzone.classList.add("is-dragging");
  });

  dropzone.addEventListener("dragover", (event) => {
    event.preventDefault();
  });

  dropzone.addEventListener("dragleave", () => {
    dragDepth = Math.max(0, dragDepth - 1);
    if (dragDepth === 0) {
      dropzone.classList.remove("is-dragging");
    }
  });

  dropzone.addEventListener("drop", (event) => {
    event.preventDefault();
    dragDepth = 0;
    dropzone.classList.remove("is-dragging");
    const file = event.dataTransfer?.files?.[0];
    if (file) {
      start(file);
    }
  });

  window.addEventListener("dragover", (event) => event.preventDefault());
  window.addEventListener("drop", (event) => event.preventDefault());
}

function setRunState(running) {
  $("#rerun").disabled = running || !state.doc;
  $("#rerun").classList.toggle("is-loading", running);
  $("#drop").classList.toggle("is-disabled", running);
  $("#file").disabled = running;
}

function updateDocumentSummary(file, documentInfo) {
  const pageLabel =
    documentInfo.kind === "pdf"
      ? `${documentInfo.pages} ${pluralize(documentInfo.pages, "page", "pages")}`
      : "Image";

  $("#fname").hidden = false;
  $("#fname-text").textContent = documentInfo.name;
  $("#fname-meta").textContent = `${pageLabel} · ${formatBytes(file.size)}`;
  $("#tbname").textContent = documentInfo.name;
  $("#tbmeta").textContent = pageLabel;
  $("#toolbar").hidden = false;
}

async function start(file) {
  if (state.busy) {
    return;
  }

  const limit = state.info?.max_upload || 200 * 1024 * 1024;
  if (file.size > limit) {
    toast(`The file is larger than the ${formatBytes(limit)} limit.`, "error");
    return;
  }

  state.busy = true;
  setRunState(true);
  setStatus("Uploading document…");

  try {
    const documentInfo = await api.uploadFile(file);
    state.doc = documentInfo;
    state.pages.clear();
    state.timings = [];
    state.runId += 1;
    updateDocumentSummary(file, documentInfo);
    await run();
  } catch (error) {
    setStatus(`Upload failed: ${error.message}`, true);
    toast(error.message, "error");
  } finally {
    state.busy = false;
    setRunState(false);
  }
}

async function run() {
  if (!state.doc) {
    return;
  }

  const runId = ++state.runId;
  const options = collectOptions();
  const requestedPages =
    options.max_pages === 0 ? state.doc.pages : options.max_pages;
  const total = Math.min(state.doc.pages, requestedPages);
  const started = performance.now();

  state.busy = true;
  state.pages.clear();
  state.timings = [];
  $("#out").innerHTML = "";
  renderStats();
  setRunState(true);

  try {
    for (let index = 0; index < total; index += 1) {
      if (runId !== state.runId) {
        return;
      }

      const limitNote =
        state.doc.pages > total ? ` (${total} of ${state.doc.pages})` : "";
      setStatus(`Reading page ${index + 1} of ${total}${limitNote}…`);

      const page = await api.readPage(state.doc.id, index, options);
      if (runId !== state.runId) {
        return;
      }

      state.pages.set(index, page);
      state.timings.push(page.timings || {});
      appendPageCard(page);
      renderStats();
    }

    const seconds = ((performance.now() - started) / 1000).toFixed(1);
    const failed = [...state.pages.values()].filter(
      (page) => page.source === "error"
    ).length;

    if (failed) {
      const message = `Parsed ${total} ${pluralize(total, "page", "pages")} in ${seconds} s. ${failed} ${pluralize(failed, "page", "pages")} could not be read.`;
      setStatus(message, true);
      toast(`${failed} ${pluralize(failed, "page", "pages")} could not be read.`, "error");
    } else {
      setStatus(`Parsed ${total} ${pluralize(total, "page", "pages")} in ${seconds} s.`);
      toast("Parsing complete.");
    }
  } catch (error) {
    if (runId === state.runId) {
      setStatus(`Reading failed: ${error.message}`, true);
      toast(error.message, "error");
    }
  } finally {
    if (runId === state.runId) {
      state.busy = false;
      setRunState(false);
    }
  }
}

function lineBox(box, scale) {
  const values = (box || [0, 0, 0, 0]).map((value) => (Number(value) || 0) * scale);
  return values.slice(0, 4);
}

function pageSvg(page) {
  const scale = Number(page.scale) || 1;
  const width = Number(page.w) || 1;
  const height = Number(page.h) || 1;
  const unit = Math.max(1, width / 640);

  const blocks = (page.blocks || [])
    .map((block, index) => {
      const [x0, y0, x1, y1] = lineBox(block.box, scale);
      const color = BLOCK_COLORS[block.label] || "#6b7280";
      const label = escapeHtml(BLOCK_LABELS[block.label] || block.label || "");
      return (
        `<rect class="block-box" data-block="${index}" x="${x0 - 2}" y="${y0 - 2}" width="${Math.max(0, x1 - x0) + 4}" height="${Math.max(0, y1 - y0) + 4}" stroke="${color}"/>` +
        `<text class="block-label" data-block="${index}" x="${Math.max(2, x0 - 2)}" y="${Math.max(13 * unit, y0 - 5 * unit)}" fill="${color}" stroke="#ffffff" stroke-width="${3 * unit}" font-size="${11 * unit}">${label}</text>`
      );
    })
    .join("");

  const boxes = (page.lines || [])
    .map((line, index) => {
      const [x0, y0, x1, y1] = lineBox(line.box, scale);
      return `<rect class="line-box" data-line="${index}" x="${x0}" y="${y0}" width="${Math.max(0, x1 - x0)}" height="${Math.max(0, y1 - y0)}"/>`;
    })
    .join("");

  const centers = (page.lines || []).map((line) => {
    const [x0, y0, x1, y1] = lineBox(line.box, scale);
    return [(x0 + x1) / 2, (y0 + y1) / 2];
  });

  const orderPath =
    centers.length > 1
      ? `<path class="reading-order" d="M${centers
          .map(([x, y]) => `${x},${y}`)
          .join(" L")}"/>`
      : "";
  const orderNumbers = centers
    .map(
      ([x, y], index) =>
        `<circle class="order-dot" cx="${x}" cy="${y}" r="${6.5 * unit}"/><text class="order-number" x="${x}" y="${y}" font-size="${8 * unit}">${index + 1}</text>`
    )
    .join("");

  return `<svg class="page-svg" width="${width}" height="${height}" viewBox="0 0 ${width} ${height}" role="img" aria-label="Page ${page.page} preview"><image href="${page.img}" width="${width}" height="${height}"/>${blocks}${boxes}${orderPath}${orderNumbers}</svg>`;
}

function stageBar(timings) {
  const total = timings.total_ms || 1;
  return STAGES.map(({ key, label, color }) => {
    const value = timings[key];
    if (!value) {
      return "";
    }
    const width = (100 * value) / total;
    return `<i style="width:${width}%;background:${color}" title="${label}: ${formatNumber(value, 1)} ms"></i>`;
  }).join("");
}

function pageJson(page) {
  return {
    page: page.page,
    width: page.width,
    height: page.height,
    source: page.source,
    rotation: page.rotation,
    skew: page.skew,
    note: page.note,
    lines: page.lines,
    blocks: page.blocks,
    markdown: page.markdown,
    text: page.text,
    timings: page.timings,
  };
}

function pageErrorMarkup(page) {
  return `<p class="page-error">${escapeHtml(page.note || "This page could not be read.")}</p>`;
}

function appendPageCard(page) {
  const article = document.createElement("article");
  article.className = "page-card";
  article.dataset.page = String(page.page - 1);

  const clean = $("#clean").checked;
  const preview =
    page.source === "error"
      ? pageErrorMarkup(page)
      : (clean ? page.preview_clean : page.preview) ||
        '<p class="empty-copy">No text detected.</p>';

  const extra = [
    page.rotation ? `rotated ${page.rotation}°` : "",
    page.skew ? `deskewed ${Math.abs(page.skew).toFixed(1)}°` : "",
  ]
    .filter(Boolean)
    .join(" · ");

  const lineRows = (page.lines || [])
    .map((line, index) => {
      const confidence = Number(line.conf);
      const low = Number.isFinite(confidence) && confidence < 0.8;
      const text = escapeHtml(line.text) || '<span class="muted">(empty)</span>';
      const value = Number.isFinite(confidence) ? confidence.toFixed(2) : "—";
      return `<div class="line-row" data-line="${index}"><span class="line-index">${index + 1}</span><span class="line-text" dir="auto">${text}</span><span class="confidence ${low ? "low" : ""}">${value}</span></div>`;
    })
    .join("");

  const meta = `${page.lines.length} ${pluralize(page.lines.length, "line", "lines")} · ${page.blocks.length} ${pluralize(page.blocks.length, "block", "blocks")}${extra ? ` · ${extra}` : ""}`;
  const sourceLabel = SOURCE_LABELS[page.source] || page.source;

  article.innerHTML = `
    <header class="page-header">
      <h3 class="page-title">Page ${page.page}</h3>
      <span class="source-badge ${escapeHtml(page.source)}">${escapeHtml(sourceLabel)}</span>
      <span class="page-meta">${escapeHtml(meta)}</span>
      <span class="spacer"></span>
      <span class="timing" title="Processing time by stage">
        <span class="timing-bar">${stageBar(page.timings)}</span>
        <span class="timing-value">${formatNumber(page.timings.total_ms || 0)} ms</span>
      </span>
      <div class="menu page-menu">
        <button class="icon-button" type="button" aria-label="Page ${page.page} actions" aria-haspopup="menu" aria-expanded="false">${icon("more")}</button>
        <div class="menu-panel" hidden role="menu">
          <button type="button" data-action="copy" role="menuitem">${icon("copy")}<span>Copy page Markdown</span></button>
          <div class="menu-separator"></div>
          <button type="button" data-format="md" role="menuitem">${icon("file")}<span>Markdown</span><span class="menu-ext">.md</span></button>
          <button type="button" data-format="txt" role="menuitem">${icon("lines")}<span>Plain text</span><span class="menu-ext">.txt</span></button>
          <button type="button" data-format="csv" role="menuitem">${icon("table")}<span>Lines CSV</span><span class="menu-ext">.csv</span></button>
          <button type="button" data-format="tables" role="menuitem">${icon("archive")}<span>Tables package</span><span class="menu-ext">.zip</span></button>
          <button type="button" data-format="json" role="menuitem">${icon("braces")}<span>JSON data</span><span class="menu-ext">.json</span></button>
          <button type="button" data-format="html" role="menuitem">${icon("external")}<span>Web page</span><span class="menu-ext">.html</span></button>
        </div>
      </div>
    </header>
    <div class="page-body">
      <div class="page-preview" title="Open larger preview">
        ${pageSvg(page)}
        <span class="zoom-hint">${icon("zoom")}Open preview</span>
      </div>
      <div class="text-pane">
        <div class="tabs" role="tablist" aria-label="Page ${page.page} content">
          <button type="button" class="tab is-active" data-tab="preview" role="tab" aria-selected="true">Preview</button>
          <button type="button" class="tab" data-tab="markdown" role="tab" aria-selected="false">Markdown</button>
          <button type="button" class="tab" data-tab="lines" role="tab" aria-selected="false">Lines (${page.lines.length})</button>
          <button type="button" class="tab" data-tab="json" role="tab" aria-selected="false">JSON</button>
        </div>
        <div class="tab-panel prose" data-panel="preview">${preview}</div>
        <div class="tab-panel code" data-panel="markdown" hidden>${escapeHtml(page.markdown || "")}</div>
        <div class="tab-panel line-list" data-panel="lines" hidden>${lineRows || '<p class="empty-copy">No lines detected.</p>'}</div>
        <div class="tab-panel code" data-panel="json" hidden>${escapeHtml(JSON.stringify(pageJson(page), null, 2))}</div>
      </div>
    </div>`;

  $$(".tab", article).forEach((tab) => {
    tab.addEventListener("click", () => {
      $$(".tab", article).forEach((item) => {
        const active = item === tab;
        item.classList.toggle("is-active", active);
        item.setAttribute("aria-selected", String(active));
      });
      $$("[data-panel]", article).forEach((panel) => {
        panel.hidden = panel.dataset.panel !== tab.dataset.tab;
      });
    });
  });

  const highlightLine = (value) => {
    $$("[data-line]", article).forEach((element) => {
      element.classList.toggle(
        "is-active",
        value !== null && element.dataset.line === String(value)
      );
    });
  };

  $$(".line-row", article).forEach((row) => {
    row.addEventListener("mouseenter", () => highlightLine(row.dataset.line));
    row.addEventListener("mouseleave", () => highlightLine(null));
  });

  $$(".line-box", article).forEach((box) => {
    box.addEventListener("mouseenter", () => {
      highlightLine(box.dataset.line);
      const row = article.querySelector(`.line-row[data-line="${box.dataset.line}"]`);
      if (row) {
        row.scrollIntoView({ block: "nearest" });
      }
    });
    box.addEventListener("mouseleave", () => highlightLine(null));
  });

  const highlightBlock = (value) => {
    $$("[data-block]", article).forEach((element) => {
      element.classList.toggle(
        "is-active",
        value !== null && element.dataset.block === String(value)
      );
    });
  };

  $$("[data-block]", article).forEach((block) => {
    block.addEventListener("mouseenter", () => highlightBlock(block.dataset.block));
    block.addEventListener("mouseleave", () => highlightBlock(null));
  });

  $(".page-preview", article).addEventListener("click", () => {
    openLightbox(Number(article.dataset.page));
  });

  const menuTrigger = $(".page-menu > .icon-button", article);
  const menuPanel = $(".page-menu > .menu-panel", article);
  menuTrigger.addEventListener("click", (event) => {
    event.stopPropagation();
    toggleMenu(menuTrigger, menuPanel);
  });

  $$("[data-action]", menuPanel).forEach((button) => {
    button.addEventListener("click", () => {
      menuPanel.hidden = true;
      menuTrigger.setAttribute("aria-expanded", "false");
      if (button.dataset.action === "copy") {
        const markdown = $("#clean").checked ? page.clean_markdown : page.markdown;
        copyText(markdown || "").then((ok) => {
          toast(ok ? "Page Markdown copied." : "Could not access the clipboard.", ok ? "success" : "error");
        });
      }
    });
  });

  $$("[data-format]", menuPanel).forEach((button) => {
    button.addEventListener("click", () => {
      menuPanel.hidden = true;
      menuTrigger.setAttribute("aria-expanded", "false");
      download(button.dataset.format, page.page - 1, menuTrigger);
    });
  });

  $("#out").append(article);
}

function refreshPreviews() {
  const clean = $("#clean").checked;
  $$(".page-card").forEach((card) => {
    const page = state.pages.get(Number(card.dataset.page));
    const panel = $('[data-panel="preview"]', card);
    if (!page || !panel) {
      return;
    }
    panel.innerHTML =
      page.source === "error"
        ? pageErrorMarkup(page)
        : (clean ? page.preview_clean : page.preview) ||
          '<p class="empty-copy">No text detected.</p>';
  });
}

function renderStats() {
  const count = state.timings.length;
  const element = $("#stats");

  if (!count) {
    element.innerHTML = '<p class="stats-empty">No pages processed yet.</p>';
    return;
  }

  const sum = (key) =>
    state.timings.reduce((total, timings) => total + (timings[key] || 0), 0);
  const total = sum("total_ms");
  const perPage = total / count;
  const throughput = perPage > 0 ? 1000 / perPage : 0;

  const stages = STAGES.filter(({ key }) => sum(key) > 0)
    .map(({ key, label, color }) => {
      const average = sum(key) / count;
      return `<span class="stage-item"><i class="stage-dot" style="background:${color}"></i>${label}<span class="stage-value">${formatNumber(average, 0)} ms</span></span>`;
    })
    .join("");

  element.innerHTML = `
    <div class="stat-grid">
      <div class="stat"><span class="stat-value">${formatNumber(perPage, 0)}</span><span class="stat-label">ms per page</span></div>
      <div class="stat"><span class="stat-value">${formatNumber(throughput, 1)}</span><span class="stat-label">pages per second</span></div>
    </div>
    <p class="stats-meta">${count} ${pluralize(count, "page", "pages")} processed</p>
    <div class="stage-list">${stages}</div>`;
}

function closeMenus(exceptPanel = null) {
  $$(".menu-panel").forEach((panel) => {
    if (panel === exceptPanel || panel.hidden) {
      return;
    }
    panel.hidden = true;
    const trigger = panel.parentElement?.querySelector('[aria-haspopup="menu"]');
    if (trigger) {
      trigger.setAttribute("aria-expanded", "false");
    }
  });
}

function toggleMenu(trigger, panel) {
  const willOpen = panel.hidden;
  closeMenus();
  panel.hidden = !willOpen;
  trigger.setAttribute("aria-expanded", String(willOpen));
}

function initToolbar() {
  const menu = $("#dlmenu");
  const trigger = $("#dlbtn");
  const panel = $(".menu-panel", menu);

  trigger.addEventListener("click", (event) => {
    event.stopPropagation();
    toggleMenu(trigger, panel);
  });

  $$("[data-format]", panel).forEach((button) => {
    button.addEventListener("click", () => {
      panel.hidden = true;
      trigger.setAttribute("aria-expanded", "false");
      download(button.dataset.format, null, trigger);
    });
  });

  $("#copyall").addEventListener("click", async () => {
    const indices = [...state.pages.keys()].sort((a, b) => a - b);
    if (!indices.length) {
      toast("There are no parsed pages to copy.", "error");
      return;
    }
    const clean = $("#clean").checked;
    const markdown = indices
      .map((index) => {
        const page = state.pages.get(index);
        const body = clean ? page.clean_markdown : page.markdown;
        return `<!-- page ${index + 1} -->\n${body}`;
      })
      .join("\n\n");
    const ok = await copyText(markdown);
    toast(ok ? "Document Markdown copied." : "Could not access the clipboard.", ok ? "success" : "error");
  });

  $("#rerun").addEventListener("click", () => run());
}

function fallbackFilename(format, pageIndex) {
  const stem = (state.doc?.name || "document").replace(/\.[^.]+$/, "");
  const suffix = pageIndex === null ? "" : `-p${pageIndex + 1}`;
  return `${stem}${suffix}.${FORMAT_EXTENSIONS[format] || "bin"}`;
}

function filenameFromResponse(response, fallback) {
  const disposition = response.headers.get("Content-Disposition") || "";
  const encoded = disposition.match(/filename\*=UTF-8''([^;]+)/i);
  if (encoded) {
    try {
      return decodeURIComponent(encoded[1]);
    } catch (error) {
      // Use the generated fallback when the server header is malformed.
    }
  }
  const plain = disposition.match(/filename="([^"]+)"/i);
  return plain ? plain[1] : fallback;
}

function saveBlob(blob, filename) {
  const link = document.createElement("a");
  link.href = URL.createObjectURL(blob);
  link.download = filename;
  document.body.append(link);
  link.click();
  setTimeout(() => {
    URL.revokeObjectURL(link.href);
    link.remove();
  }, 800);
}

async function download(format, pageIndex = null, button = null) {
  if (!state.doc) {
    return;
  }

  if (button) {
    button.disabled = true;
    button.classList.add("is-busy");
  }
  setStatus(pageIndex === null ? "Preparing export…" : `Preparing page ${pageIndex + 1}…`);

  try {
    const response = await api.exportDocument(
      state.doc.id,
      format,
      collectOptions(),
      pageIndex === null ? null : [pageIndex]
    );
    const blob = await response.blob();
    const filename = filenameFromResponse(response, fallbackFilename(format, pageIndex));
    saveBlob(blob, filename);
    setStatus("");
    toast(`Downloaded ${filename}.`);
  } catch (error) {
    setStatus(`Export failed: ${error.message}`, true);
    toast(error.message, "error");
  } finally {
    if (button) {
      button.disabled = false;
      button.classList.remove("is-busy");
    }
  }
}

async function copyText(text) {
  try {
    await navigator.clipboard.writeText(text);
    return true;
  } catch (error) {
    const field = document.createElement("textarea");
    field.value = text;
    field.setAttribute("readonly", "");
    field.style.position = "fixed";
    field.style.opacity = "0";
    document.body.append(field);
    field.select();
    let copied = false;
    try {
      copied = document.execCommand("copy");
    } catch (fallbackError) {
      copied = false;
    }
    field.remove();
    return copied;
  }
}

function openLightbox(pageIndex) {
  const page = state.pages.get(pageIndex);
  if (!page) {
    return;
  }
  state.lastFocused = document.activeElement;
  $("#lbstage").innerHTML = pageSvg(page);
  $("#lightbox").hidden = false;
  document.body.classList.add("has-lightbox");
  $("#lbclose").focus();
}

function closeLightbox() {
  if ($("#lightbox").hidden) {
    return;
  }
  $("#lightbox").hidden = true;
  $("#lbstage").innerHTML = "";
  document.body.classList.remove("has-lightbox");
  if (state.lastFocused && typeof state.lastFocused.focus === "function") {
    state.lastFocused.focus();
  }
}

function initLightbox() {
  $("#lbclose").addEventListener("click", closeLightbox);
  $("#lightbox").addEventListener("click", (event) => {
    if (event.target === $("#lightbox")) {
      closeLightbox();
    }
  });
}

function applyDefaults(defaults) {
  if (defaults.mode) {
    setMode(defaults.mode);
  }
  $("#clean").checked = defaults.clean !== false;
  $("#math").checked = Boolean(defaults.math);
  $("#furniture").checked = Boolean(defaults.furniture);
  $("#pdforder").checked = defaults.pdf_order !== false;
  $("#imageocr").checked = defaults.image_ocr !== false;

  if (defaults.dpi) {
    const value = String(Math.round(defaults.dpi));
    if (![...$("#dpi").options].some((option) => option.value === value)) {
      $("#dpi").append(new Option(value, value));
    }
    $("#dpi").value = value;
  }
  if (defaults.max_pages !== undefined && defaults.max_pages !== null) {
    $("#maxp").value = defaults.max_pages;
  }
}

async function init() {
  initTheme();
  initDropzone();
  initMode();
  initDisplayOptions();
  initToolbar();
  initLightbox();
  buildLegend();
  renderStats();

  $("#clean").addEventListener("change", refreshPreviews);
  document.addEventListener("click", () => closeMenus());
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape") {
      closeMenus();
      closeLightbox();
    }
  });

  try {
    const info = await api.getInfo();
    state.info = info;
    $("#ver").textContent = `Indra OCR ${info.engine_version}`;
    $("#ver").title = `EgyFy Parser ${info.version} · Indra OCR ${info.engine_version}`;
    applyDefaults(info.defaults || {});
  } catch (error) {
    setMode("auto");
    setStatus("The parser service is not responding.", true);
    toast(error.message, "error");
  }
}

init().catch((error) => {
  setStatus("The interface could not start.", true);
  toast(error.message, "error");
});
