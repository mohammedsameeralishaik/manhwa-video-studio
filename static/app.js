/* ==========================================================================
   Manhwa Video Studio — Premium Studio Logic & UX
   ========================================================================== */

const $ = (id) => document.getElementById(id);

let jobId = null;
let images = [];        // Extracted or uploaded original images
let selected = [];      // Ordered IDs of originals in the storyboard
let processed = [];     // Processed frames (with raw and formatted cuts)
let frameOrder = [];    // Ordered IDs of processed frames
let sceneModes = {};    // Camera motion modes per scene (blur_fill | vpan | dialogue)
let activeFrameId = null;
let isSimulatingMotion = false;
let pollTimer = null;
let lastClickedThumbIdx = null;

/* ---------------- Toast Notification System ---------------- */
function toast(msg, type = "error") {
  const container = $("toast-container");
  if (!container) return;

  const t = document.createElement("div");
  t.className = `toast toast-${type}`;
  
  const icon = type === "success" ? "✓" : type === "info" ? "ℹ" : "⚠️";
  t.innerHTML = `
    <span class="toast-icon">${icon}</span>
    <span class="toast-text">${msg}</span>
  `;
  container.appendChild(t);

  setTimeout(() => {
    t.style.opacity = "0";
    t.style.transform = "translateX(20px)";
    t.style.transition = "all 0.3s ease";
    setTimeout(() => t.remove(), 300);
  }, 4200);
}

function show(id) { $(id)?.classList.remove("hidden"); }
function hide(id) { $(id)?.classList.add("hidden"); }

function setStep(n) {
  document.querySelectorAll(".step").forEach(s => {
    const stepNum = +s.dataset.s;
    s.classList.toggle("on", stepNum === n);
    s.classList.toggle("completed", stepNum < n);
  });
}

function fileUrl(kind, name) {
  return `/api/file/${jobId}/${kind}/${encodeURIComponent(name)}`;
}

const imgOf = (id) => images.find(i => i.id === id);
const procOf = (id) => processed.find(p => p.id === id);

let currentRatio = "9:16";
let allResolutions = {};
let allCropModes = {};

/* ---------------- Options Loading ---------------- */
fetch("/api/options")
  .then(r => r.json())
  .then(opts => {
    allResolutions = opts.resolutions || {};
    allCropModes = opts.crop_modes || {};

    // Populate Transitions
    const transSelect = $("transition");
    if (transSelect) {
      transSelect.innerHTML = "";
      Object.entries(opts.transitions).forEach(([k, v]) => {
        const op = document.createElement("option");
        op.value = k;
        op.textContent = v;
        transSelect.appendChild(op);
      });
      transSelect.value = "mix";
    }

    // Populate Crop Modes
    const cropMode = $("crop-mode");
    if (cropMode) {
      cropMode.innerHTML = "";
      Object.entries(opts.crop_modes).forEach(([k, v]) => {
        const op = document.createElement("option");
        op.value = k;
        op.textContent = v;
        cropMode.appendChild(op);
      });
      cropMode.value = "scene_split";
    }

    // Populate initial resolutions for current aspect ratio
    populateResolutions(currentRatio);
  })
  .catch(err => console.error("Error loading options:", err));

function populateResolutions(ratio) {
  const cropRes = $("crop-res");
  const renderRes = $("resolution");
  const isLandscape = ratio === "16:9";

  [cropRes, renderRes].forEach(sel => {
    if (!sel) return;
    sel.innerHTML = "";

    // Add matching resolutions first
    Object.entries(allResolutions).forEach(([k, v]) => {
      const isResLandscape = v.ratio === "16:9";
      if (isResLandscape === isLandscape) {
        const op = document.createElement("option");
        op.value = k;
        op.textContent = `${v.label} · ${v.tag}`;
        sel.appendChild(op);
      }
    });

    // Fallback if needed or set default
    sel.value = isLandscape ? "1920x1080" : "1080x1920";
  });
}

function setAspectRatio(ratio) {
  currentRatio = ratio;
  const isLandscape = ratio === "16:9";

  const btn916 = $("ratio-btn-916");
  const btn169 = $("ratio-btn-169");
  btn916?.classList.toggle("active", !isLandscape);
  btn169?.classList.toggle("active", isLandscape);

  const mockup = $("mockup-frame");
  const miniMockup = $("mini-mockup-frame");
  const cinemaPlayer = $("cinema-player-frame");
  const theater = $("export-theater");
  const monitor = $("cinema-monitor");

  [mockup, miniMockup, cinemaPlayer, theater].forEach(el => {
    el?.classList.toggle("landscape", isLandscape);
  });
  monitor?.classList.toggle("vertical", !isLandscape);

  const pill = $("preview-ratio-pill");
  if (pill) pill.textContent = isLandscape ? "16:9 YOUTUBE WIDESCREEN" : "9:16 VERTICAL";

  const titleRatio = $("preview-title-ratio");
  if (titleRatio) titleRatio.textContent = isLandscape ? "16:9 Landscape Preview" : "9:16 Frame Preview";

  const btnProcessText = $("btn-process-text");
  if (btnProcessText) btnProcessText.textContent = isLandscape ? "Process Frames to 16:9 (YouTube)" : "Process Frames to 9:16";

  const cropTip = $("crop-mode-tip");
  if (cropTip) {
    cropTip.innerHTML = isLandscape
      ? "<b>Blur fill:</b> Fits whole panel in center with soft blurred ambient wings (preferred standard for YouTube manga recap channels). <b>Smart scene split:</b> Slices pages into horizontal 16:9 frames."
      : "<b>Smart scene split:</b> Analyzes gutters and slices tall pages into sequential vertical scenes.";
  }

  const aspectTag = $("active-aspect-tag");
  if (aspectTag) aspectTag.textContent = `Aspect: ${ratio}`;

  populateResolutions(ratio);
  updateStoryboardRatio();
  updateVideoHUD();
  toast(`Switched format to ${isLandscape ? "16:9 Landscape (YouTube)" : "9:16 Vertical (Shorts/Reels)"}`, "info");
}

function updateStoryboardRatio() {
  const isLandscape = currentRatio === "16:9";
  document.querySelectorAll(".sb-item").forEach(item => {
    item.classList.toggle("landscape", isLandscape);
  });
}

$("ratio-btn-916")?.addEventListener("click", () => setAspectRatio("9:16"));
$("ratio-btn-169")?.addEventListener("click", () => setAspectRatio("16:9"));

/* ---------------- Import Mode Switcher ---------------- */
const tabBtnUrl = $("tab-btn-url");
const tabBtnUpload = $("tab-btn-upload");
const panelUrl = $("panel-url");
const panelUpload = $("panel-upload");

tabBtnUrl?.addEventListener("click", () => {
  tabBtnUrl.classList.add("active");
  tabBtnUpload.classList.remove("active");
  panelUrl.classList.add("active");
  panelUpload.classList.remove("active");
});

tabBtnUpload?.addEventListener("click", () => {
  tabBtnUpload.classList.add("active");
  tabBtnUrl.classList.remove("active");
  panelUpload.classList.add("active");
  panelUrl.classList.remove("active");
});

/* ---------------- URL Scraper Trigger ---------------- */
$("btn-extract")?.addEventListener("click", async () => {
  const url = $("url").value.trim();
  if (!url) return toast("Please enter a manhwa chapter URL.", "error");
  if (!$("consent").checked) {
    return toast("Please check the authorization confirmation.", "error");
  }

  $("btn-extract").disabled = true;
  show("extract-progress");
  updateProgress("extract-progress", 5, "Connecting to source page…");

  try {
    const res = await fetch("/api/extract", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ url, consent: true }),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || "Extraction failed.");

    jobId = data.job_id;
    pollJob(jobPollExtract);
  } catch (err) {
    toast(err.message, "error");
    $("btn-extract").disabled = false;
    hide("extract-progress");
  }
});

/* ---------------- Local File Upload & Dropzone ---------------- */
const dropzone = $("dropzone");
const fileInput = $("file-input");
const btnBrowse = $("btn-browse");

btnBrowse?.addEventListener("click", () => fileInput.click());
dropzone?.addEventListener("click", (e) => {
  if (e.target !== btnBrowse) fileInput.click();
});

["dragenter", "dragover"].forEach(name => {
  dropzone?.addEventListener(name, (e) => {
    e.preventDefault();
    dropzone.classList.add("dragover");
  });
});

["dragleave", "drop"].forEach(name => {
  dropzone?.addEventListener(name, (e) => {
    e.preventDefault();
    dropzone.classList.remove("dragover");
  });
});

dropzone?.addEventListener("drop", (e) => {
  if (e.dataTransfer?.files?.length) {
    handleFileUpload(e.dataTransfer.files);
  }
});

fileInput?.addEventListener("change", (e) => {
  if (e.target?.files?.length) {
    handleFileUpload(e.target.files);
  }
});

async function handleFileUpload(fileList) {
  const files = Array.from(fileList);
  if (!files.length) return;

  const formData = new FormData();
  files.forEach(f => formData.append("files", f));

  show("extract-progress");
  updateProgress("extract-progress", 20, `Uploading ${files.length} panel(s)…`);

  try {
    const res = await fetch("/api/upload", {
      method: "POST",
      body: formData,
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || "Upload failed.");

    jobId = data.job_id;
    toast(`Successfully imported ${data.count} chapter panel(s)!`, "success");
    
    // Fetch job status to get full images list
    const jRes = await fetch(`/api/jobs/${jobId}`);
    const jobState = await jRes.json();
    jobPollExtract(jobState);
  } catch (err) {
    toast(err.message, "error");
    hide("extract-progress");
  }
}

/* ---------------- Polling Engine ---------------- */
function updateProgress(blockId, pct, message) {
  const block = $(blockId);
  if (!block) return;
  const fill = block.querySelector(".fill");
  const msg = block.querySelector(".msg");
  const pctText = block.querySelector(".progress-pct");
  if (fill) fill.style.width = `${pct}%`;
  if (msg && message) msg.textContent = message;
  if (pctText) pctText.textContent = `${pct}%`;
}

function pollJob(onDone) {
  clearInterval(pollTimer);
  pollTimer = setInterval(async () => {
    try {
      const res = await fetch(`/api/jobs/${jobId}`);
      if (!res.ok) return;
      const state = await res.json();

      const blockId = state.stage === "extracting" ? "extract-progress"
        : state.stage === "processing" ? "process-progress"
        : "render-progress";

      updateProgress(blockId, state.progress || 0, state.message || "Working…");

      if (state.stage === "error") {
        clearInterval(pollTimer);
        toast(state.message || "An unexpected error occurred.", "error");
        $("btn-extract").disabled = false;
        $("btn-process").disabled = false;
        $("btn-render").disabled = false;
      } else if (onDone(state)) {
        clearInterval(pollTimer);
      }
    } catch (e) {
      console.warn("Poll tick failed:", e);
    }
  }, 1000);
}

function jobPollExtract(s) {
  if (s.stage === "ready") {
    images = s.images || [];
    selected = [];
    buildGallery();
    show("sec-gallery");
    setStep(2);
    hide("extract-progress");
    $("btn-extract").disabled = false;
    $("sec-gallery").scrollIntoView({ behavior: "smooth" });
    toast(`Loaded ${images.length} panels ready for curation`, "success");
    return true;
  }
  return false;
}

/* ---------------- Gallery Management ---------------- */
function buildGallery() {
  const g = $("gallery");
  g.innerHTML = "";

  images.forEach((im, idx) => {
    const card = document.createElement("div");
    card.className = "thumb";
    card.dataset.id = im.id;
    card.dataset.idx = idx;

    card.innerHTML = `
      <img loading="lazy" src="${fileUrl("originals", im.file)}" alt="Panel ${idx + 1}">
      <span class="thumb-badge"></span>
      <span class="thumb-zoom" title="Inspect Fullscreen (Lightbox)">
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5">
          <polyline points="15 3 21 3 21 9"></polyline>
          <polyline points="9 21 3 21 3 15"></polyline>
          <line x1="21" y1="3" x2="14" y2="10"></line>
          <line x1="3" y1="21" x2="10" y2="14"></line>
        </svg>
      </span>
    `;

    // Click to toggle selection (supports Shift-click multi-select!)
    card.addEventListener("click", (e) => {
      if (e.target.closest(".thumb-zoom")) {
        e.stopPropagation();
        openLightbox(fileUrl("originals", im.file));
        return;
      }

      if (e.shiftKey && lastClickedThumbIdx !== null) {
        const start = Math.min(lastClickedThumbIdx, idx);
        const end = Math.max(lastClickedThumbIdx, idx);
        for (let i = start; i <= end; i++) {
          const id = images[i].id;
          if (!selected.includes(id)) selected.push(id);
        }
      } else {
        toggleSelect(im.id);
      }
      lastClickedThumbIdx = idx;
      updateGallerySelectionVisuals();
      renderStoryboard();
    });

    g.appendChild(card);
  });

  renderStoryboard();
}

function toggleSelect(id) {
  const i = selected.indexOf(id);
  if (i >= 0) selected.splice(i, 1);
  else selected.push(id);
}

function updateGallerySelectionVisuals() {
  document.querySelectorAll(".thumb").forEach(t => {
    const id = t.dataset.id;
    const isSelected = selected.includes(id);
    t.classList.toggle("sel", isSelected);
    const badge = t.querySelector(".thumb-badge");
    if (badge) {
      badge.textContent = isSelected ? `#${selected.indexOf(id) + 1}` : "";
    }
  });

  const countBadge = $("sel-count");
  if (countBadge) {
    countBadge.textContent = `${selected.length} of ${images.length} selected`;
  }
}

/* ---------------- Storyboard Timeline ---------------- */
function renderStoryboard() {
  updateGallerySelectionVisuals();
  const sb = $("storyboard");
  if (!sb) return;

  if (!selected.length) {
    sb.innerHTML = `
      <div class="empty-state">
        <svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
          <rect x="3" y="3" width="18" height="18" rx="2" ry="2"></rect>
          <circle cx="8.5" cy="8.5" r="1.5"></circle>
          <polyline points="21 15 16 10 5 21"></polyline>
        </svg>
        <p>No panels selected. Click images above to build your sequence.</p>
      </div>`;
    return;
  }

  sb.innerHTML = "";
  selected.forEach((id, n) => {
    const im = imgOf(id);
    if (!im) return;

    const item = document.createElement("div");
    item.className = "sb-item" + (currentRatio === "16:9" ? " landscape" : "");
    item.draggable = true;
    item.dataset.id = id;

    item.innerHTML = `
      <img src="${fileUrl("originals", im.file)}" alt="Scene ${n + 1}">
      <span class="ord">#${n + 1}</span>
      <button class="rm" title="Remove Panel">×</button>
    `;

    item.querySelector("img").addEventListener("click", () => {
      $("big-preview").src = fileUrl("originals", im.file);
    });

    item.querySelector(".rm").addEventListener("click", (e) => {
      e.stopPropagation();
      const idx = selected.indexOf(id);
      if (idx >= 0) selected.splice(idx, 1);
      renderStoryboard();
    });

    // Drag and Drop
    item.addEventListener("dragstart", () => item.classList.add("dragging"));
    item.addEventListener("dragend", () => item.classList.remove("dragging"));

    sb.appendChild(item);
  });

  // Drag over reorder events
  sb.querySelectorAll(".sb-item").forEach(el => {
    el.addEventListener("dragover", (e) => {
      e.preventDefault();
      const drag = sb.querySelector(".dragging");
      if (!drag || drag === el) return;
      const els = [...sb.querySelectorAll(".sb-item")];
      if (els.indexOf(drag) < els.indexOf(el)) el.after(drag);
      else el.before(drag);
    });

    el.addEventListener("drop", () => {
      selected = [...sb.querySelectorAll(".sb-item")].map(x => x.dataset.id);
      renderStoryboard();
    });
  });

  // Update big preview inside smartphone mockup
  if (selected.length) {
    $("big-preview").src = fileUrl("originals", imgOf(selected[0]).file);
  }
}

/* ---------------- Batch Gallery Buttons ---------------- */
$("btn-all")?.addEventListener("click", () => {
  selected = images.map(i => i.id);
  renderStoryboard();
});

$("btn-top10")?.addEventListener("click", () => {
  selected = images.slice(0, 10).map(i => i.id);
  renderStoryboard();
  toast("Selected first 10 panels (~20s Short)", "info");
});

$("btn-none")?.addEventListener("click", () => {
  selected = [];
  renderStoryboard();
});

$("btn-remove")?.addEventListener("click", () => {
  if (!selected.length) return;
  images = images.filter(i => !selected.includes(i.id));
  selected = [];
  buildGallery();
  toast("Removed selected panels from project.", "info");
});

/* ---------------- Step 2 -> Process to 9:16 Frames ---------------- */
$("btn-process")?.addEventListener("click", async () => {
  if (!selected.length) return toast("Select at least one panel first.", "error");

  $("btn-process").disabled = true;
  show("process-progress");
  updateProgress("process-progress", 5, "Preparing panel slicing algorithm…");

  try {
    const res = await fetch(`/api/jobs/${jobId}/process`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        selection: selected,
        crop_mode: $("crop-mode").value,
        resolution: $("crop-res").value,
      }),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || "Frame processing failed.");

    pollJob((s) => {
      if (s.stage === "processed") {
        processed = s.processed || [];
        frameOrder = processed.map(p => p.id);
        buildFrames();
        show("sec-video");
        setStep(3);
        hide("process-progress");
        $("btn-process").disabled = false;
        $("sec-video").scrollIntoView({ behavior: "smooth" });
        toast(`Generated ${processed.length} vertical 9:16 frames!`, "success");
        updateVideoHUD();
        return true;
      }
      return false;
    });
  } catch (err) {
    toast(err.message, "error");
    $("btn-process").disabled = false;
    hide("process-progress");
  }
});

/* ---------------- Step 3: Render Frames Timeline, Scene Director & Motion ---------------- */
function selectFrame(id) {
  activeFrameId = id;
  const p = procOf(id);
  if (!p) return;

  const n = frameOrder.indexOf(id);
  const title = $("active-scene-title");
  if (title) title.textContent = `Scene #${n + 1}`;

  const currentMode = sceneModes[id] || p.mode || "blur_fill";
  sceneModes[id] = currentMode;

  // Highlight active storyboard item
  document.querySelectorAll("#frames .sb-item").forEach(item => {
    item.classList.toggle("active", item.dataset.id === id);
  });

  // Update mode selector buttons in Scene Director
  ["blur", "vpan", "dialogue"].forEach(m => {
    const btn = $(`mode-btn-${m}`);
    const modeKey = m === "blur" ? "blur_fill" : m;
    btn?.classList.toggle("active", currentMode === modeKey);
  });

  // Update monitor image & mode label
  updateMonitorPreview(p, currentMode);

  // Update aspect & status pills
  const aspectInfo = $("scene-aspect-info");
  if (aspectInfo) {
    aspectInfo.textContent = p.aspect ? `Panel: ${p.aspect >= 1.2 ? "Portrait Scroll" : "Standard"} (${p.aspect}×)` : "Scene Ready";
  }
  const motionStatus = $("scene-motion-status");
  if (motionStatus) {
    motionStatus.textContent = currentMode === "vpan" ? "Glide: Face → Feet"
      : currentMode === "dialogue" ? "Zoom: 1.35× Dialogue" : "Pillarbox: 100% Fit";
  }
}

function updateMonitorPreview(p, mode) {
  const img = $("frame-preview");
  const label = $("monitor-mode-label");

  if (!img) return;

  // Use raw panel for vertical pan and dialogue zoom when available
  if ((mode === "vpan" || mode === "dialogue") && p.raw_file) {
    img.src = fileUrl("processed", p.raw_file);
  } else {
    img.src = fileUrl("processed", p.file);
  }

  if (label) {
    label.textContent = mode === "vpan" ? "🎬 Vertical Pan (Face to Feet)"
      : mode === "dialogue" ? "🔍 Dialogue & Face Zoom (1.35×)"
      : "🖼️ Pillarbox Blur (Default)";
  }

  // Refresh motion simulation if active
  if (isSimulatingMotion) {
    applyMotionSimulation(mode);
  }
}

function applyMotionSimulation(mode) {
  const screen = $("monitor-screen");
  if (!screen) return;
  screen.classList.remove("sim-blur", "sim-vpan", "sim-dialogue", "guide-visible", "simulating");

  if (!isSimulatingMotion) return;

  screen.classList.add("simulating");
  if (mode === "vpan") {
    screen.classList.add("sim-vpan");
  } else if (mode === "dialogue") {
    screen.classList.add("sim-dialogue", "guide-visible");
  } else {
    screen.classList.add("sim-blur");
  }
}

function toggleMotionSimulation() {
  isSimulatingMotion = !isSimulatingMotion;
  const btn = $("btn-toggle-preview-motion");
  const icon = $("play-btn-icon");
  const text = $("play-btn-text");

  btn?.classList.toggle("active", isSimulatingMotion);
  if (icon) icon.textContent = isSimulatingMotion ? "⏸" : "▶";
  if (text) text.textContent = isSimulatingMotion ? "Pause Motion" : "Simulate Motion";

  const p = procOf(activeFrameId);
  const mode = (p && sceneModes[activeFrameId]) || "blur_fill";
  applyMotionSimulation(mode);
}

function setFrameMode(mode) {
  if (!activeFrameId) return;
  sceneModes[activeFrameId] = mode;

  // Update button active states
  ["blur", "vpan", "dialogue"].forEach(m => {
    const btn = $(`mode-btn-${m}`);
    const modeKey = m === "blur" ? "blur_fill" : m;
    btn?.classList.toggle("active", mode === modeKey);
  });

  // Update badge on storyboard item
  const sbItem = document.querySelector(`#frames .sb-item[data-id="${activeFrameId}"]`);
  if (sbItem) {
    const pill = sbItem.querySelector(".sb-mode-pill");
    if (pill) {
      pill.className = `sb-mode-pill mode-${mode}`;
      pill.textContent = mode === "vpan" ? "🎬 V-Pan" : mode === "dialogue" ? "🔍 Zoom" : "🖼️ Blur";
    }
  }

  const p = procOf(activeFrameId);
  if (p) {
    updateMonitorPreview(p, mode);
  }

  const motionStatus = $("scene-motion-status");
  if (motionStatus) {
    motionStatus.textContent = mode === "vpan" ? "Glide: Face → Feet"
      : mode === "dialogue" ? "Zoom: 1.35× Dialogue" : "Pillarbox: 100% Fit";
  }

  toast(`Scene mode: ${mode === "vpan" ? "Vertical Pan (Face to Feet)" : mode === "dialogue" ? "Dialogue & Face Zoom" : "Pillarbox Blur Fit (Default)"}`, "info");
}

function deleteScene(id) {
  const idx = frameOrder.indexOf(id);
  if (idx >= 0) {
    frameOrder.splice(idx, 1);
    delete sceneModes[id];
    if (activeFrameId === id) {
      activeFrameId = frameOrder[Math.min(idx, frameOrder.length - 1)] || null;
    }
    buildFrames();
    toast("Scene removed from timeline.", "info");
  }
}

function buildFrames() {
  const sb = $("frames");
  sb.innerHTML = "";

  const badge = $("frame-count-badge");
  if (badge) badge.textContent = `${frameOrder.length} frames`;

  frameOrder.forEach((id, n) => {
    const p = procOf(id);
    if (!p) return;

    if (!sceneModes[id]) {
      sceneModes[id] = p.mode || "blur_fill";
    }
    const currentMode = sceneModes[id];

    const item = document.createElement("div");
    item.className = "sb-item" + (currentRatio === "16:9" ? " landscape" : "");
    if (id === activeFrameId) item.classList.add("active");
    item.draggable = true;
    item.dataset.id = id;

    const modeLabel = currentMode === "vpan" ? "🎬 V-Pan" : currentMode === "dialogue" ? "🔍 Zoom" : "🖼️ Blur";

    item.innerHTML = `
      <img src="${fileUrl("processed", p.file)}" alt="Frame ${n + 1}">
      <span class="ord">#${n + 1}</span>
      <span class="sb-mode-pill mode-${currentMode}">${modeLabel}</span>
      <button class="rm" title="Remove Scene">×</button>
    `;

    item.addEventListener("click", () => selectFrame(id));

    item.querySelector(".rm").addEventListener("click", (e) => {
      e.stopPropagation();
      deleteScene(id);
    });

    item.addEventListener("dragstart", () => item.classList.add("dragging"));
    item.addEventListener("dragend", () => item.classList.remove("dragging"));

    sb.appendChild(item);
  });

  sb.querySelectorAll(".sb-item").forEach(el => {
    el.addEventListener("dragover", (e) => {
      e.preventDefault();
      const drag = sb.querySelector(".dragging");
      if (!drag || drag === el) return;
      const els = [...sb.querySelectorAll(".sb-item")];
      if (els.indexOf(drag) < els.indexOf(el)) el.after(drag);
      else el.before(drag);
    });

    el.addEventListener("drop", () => {
      frameOrder = [...sb.querySelectorAll(".sb-item")].map(x => x.dataset.id);
      buildFrames();
    });
  });

  if (frameOrder.length) {
    if (!activeFrameId || !frameOrder.includes(activeFrameId)) {
      activeFrameId = frameOrder[0];
    }
    selectFrame(activeFrameId);
  }
  updateVideoHUD();
}

// Scene Director UI event bindings
$("mode-btn-blur")?.addEventListener("click", () => setFrameMode("blur_fill"));
$("mode-btn-vpan")?.addEventListener("click", () => setFrameMode("vpan"));
$("mode-btn-dialogue")?.addEventListener("click", () => setFrameMode("dialogue"));
$("btn-toggle-preview-motion")?.addEventListener("click", toggleMotionSimulation);

$("btn-apply-all-mode")?.addEventListener("click", () => {
  if (!activeFrameId) return;
  const currentMode = sceneModes[activeFrameId] || "blur_fill";
  frameOrder.forEach(id => {
    sceneModes[id] = currentMode;
  });
  buildFrames();
  toast(`Applied ${currentMode === "vpan" ? "Vertical Pan" : currentMode === "dialogue" ? "Dialogue Zoom" : "Pillarbox Blur"} to all ${frameOrder.length} scenes!`, "success");
});

$("btn-delete-scene")?.addEventListener("click", () => {
  if (activeFrameId) deleteScene(activeFrameId);
});

/* ---------------- Real-Time Video HUD Calculator ---------------- */
function updateVideoHUD() {
  const frames = frameOrder.length;
  const perImage = +$("per-image").value || 2.0;
  const transDur = +$("trans-dur").value || 0.6;
  const resolution = $("resolution").value || (currentRatio === "16:9" ? "1920x1080" : "1080x1920");

  let totalSeconds = 0;
  if (frames > 0) {
    totalSeconds = frames === 1 ? perImage : (frames * perImage) - ((frames - 1) * transDur);
  }

  const hudDur = $("hud-duration");
  const hudFrames = $("hud-frames");
  const hudFormat = $("hud-format");
  const hudBadge = $("hud-badge");

  if (hudDur) hudDur.textContent = `${totalSeconds.toFixed(1)}s`;
  if (hudFrames) hudFrames.textContent = `${frames}`;
  
  if (hudFormat) {
    const isLandscape = resolution.startsWith("1920") || resolution.startsWith("1280") || resolution.startsWith("2560");
    const label = resolution.includes("720") ? "720p" : resolution.includes("1440") ? "2K" : "1080p";
    hudFormat.textContent = `${label} (${isLandscape ? "16:9" : "9:16"})`;
  }

  if (hudBadge) {
    if (currentRatio === "16:9") {
      hudBadge.innerHTML = `<span style="background: rgba(99, 102, 241, 0.15); color: #818cf8; border: 1px solid rgba(99, 102, 241, 0.3);">🖥️ Standard 16:9 YouTube Video Format</span>`;
    } else if (totalSeconds <= 30) {
      hudBadge.innerHTML = `<span style="background: rgba(16, 185, 129, 0.15); color: #10b981; border: 1px solid rgba(16, 185, 129, 0.3);">⚡ Optimal for TikTok &amp; Reels (<30s)</span>`;
    } else if (totalSeconds <= 60) {
      hudBadge.innerHTML = `<span style="background: rgba(245, 158, 11, 0.15); color: #f59e0b; border: 1px solid rgba(245, 158, 11, 0.3);">⏱️ Great for YouTube Shorts (<60s)</span>`;
    } else {
      hudBadge.innerHTML = `<span style="background: rgba(99, 102, 241, 0.15); color: #818cf8; border: 1px solid rgba(99, 102, 241, 0.3);">🎞️ Extended Storyboard Video</span>`;
    }
  }
}

// Live range slider bindings
$("per-image")?.addEventListener("input", e => {
  $("v-dur").textContent = (+e.target.value).toFixed(1) + "s";
  updateVideoHUD();
});

$("zoom")?.addEventListener("input", e => {
  $("v-zoom").textContent = (+e.target.value).toFixed(2) + "×";
});

$("trans-dur")?.addEventListener("input", e => {
  $("v-trans").textContent = (+e.target.value).toFixed(1) + "s";
  updateVideoHUD();
});

$("resolution")?.addEventListener("change", () => updateVideoHUD());

/* ---------------- Step 3 -> Render Final Video ---------------- */
$("btn-render")?.addEventListener("click", async () => {
  if (!frameOrder.length) return toast("No frames selected for rendering.", "error");

  $("btn-render").disabled = true;
  show("render-progress");
  updateProgress("render-progress", 2, "Initializing FFmpeg render engine…");

  try {
    const res = await fetch(`/api/jobs/${jobId}/render`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        order: frameOrder,
        scene_modes: sceneModes,
        per_image: +$("per-image").value,
        trans_duration: +$("trans-dur").value,
        transition: $("transition").value,
        zoom: +$("zoom").value,
        zoom_mode: $("zoom-mode").value,
        resolution: $("resolution").value,
        fps: 30,
      }),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || "Render initialization failed.");

    pollJob((s) => {
      if (s.stage === "done") {
        const vid = $("video-preview");
        vid.src = `/api/video/${jobId}?t=${Date.now()}`;
        $("dl-video").href = `/api/download/video/${jobId}`;
        $("dl-zip").href = `/api/download/zip/${jobId}`;

        show("sec-export");
        setStep(4);
        hide("render-progress");
        $("btn-render").disabled = false;
        $("sec-export").scrollIntoView({ behavior: "smooth" });
        toast("Cinematic video rendered successfully!", "success");
        return true;
      }
      return false;
    });
  } catch (err) {
    toast(err.message, "error");
    $("btn-render").disabled = false;
    hide("render-progress");
  }
});

$("btn-back")?.addEventListener("click", () => {
  hide("sec-export");
  setStep(3);
  $("sec-video").scrollIntoView({ behavior: "smooth" });
});

/* ---------------- Lightbox Modal Handler ---------------- */
function openLightbox(src) {
  const lb = $("lightbox");
  const img = $("lightbox-img");
  if (!lb || !img) return;
  img.src = src;
  lb.classList.remove("hidden");
}

function closeLightbox() {
  const lb = $("lightbox");
  if (lb) lb.classList.add("hidden");
}

$("lightbox-close")?.addEventListener("click", closeLightbox);
$("lightbox-backdrop")?.addEventListener("click", closeLightbox);
document.addEventListener("keydown", (e) => {
  if (e.key === "Escape") closeLightbox();
});

/* ---------------- Storyboard Scroll Controls & Mouse Wheel ---------------- */
function setupTimelineScroll(sbId, leftBtnId, rightBtnId) {
  const sb = $(sbId);
  const leftBtn = $(leftBtnId);
  const rightBtn = $(rightBtnId);

  leftBtn?.addEventListener("click", () => {
    sb?.scrollBy({ left: -260, behavior: "smooth" });
  });

  rightBtn?.addEventListener("click", () => {
    sb?.scrollBy({ left: 260, behavior: "smooth" });
  });

  sb?.addEventListener("wheel", (e) => {
    if (e.deltaY !== 0) {
      e.preventDefault();
      sb.scrollLeft += e.deltaY;
    }
  }, { passive: false });
}

setupTimelineScroll("storyboard", "sb-scroll-left", "sb-scroll-right");
setupTimelineScroll("frames", "frames-scroll-left", "frames-scroll-right");
