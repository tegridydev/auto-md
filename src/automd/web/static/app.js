// src/app.ts
var token = document.querySelector('meta[name="automd-token"]')?.content ?? "";
var sources = [];
var activeJob = null;
var eventSource = null;
var previewRequest = null;
var markdownUrl = null;
var toastTimer = 0;
var viewState = "setup";
var drawerReturnFocus = null;
var setupView = element("setupView");
var processingView = element("processingView");
var resultView = element("resultView");
var errorView = element("errorView");
var views = {
  setup: setupView,
  processing: processingView,
  result: resultView,
  error: errorView
};
var dropzone = element("dropzone");
var fileInput = element("fileInput");
var folderInput = element("folderInput");
var sourceList = element("sourceList");
var sourceCount = element("sourceCount");
var urlInput = element("urlInput");
var refInput = element("refInput");
var outputName = element("outputName");
var outputSuffix = element("outputSuffix");
var setupStatus = element("setupStatus");
var readyNote = element("readyNote");
var convertButton = element("convertButton");
var settingsButton = element("settingsButton");
var settingsDrawer = element("settingsDrawer");
var drawerBackdrop = element("drawerBackdrop");
var chunkSettings = element("chunkSettings");
var filterSummary = element("filterSummary");
var ocrSummary = element("ocrSummary");
var detailSummary = element("detailSummary");
var progressBar = element("progressBar");
var progressTrack = progressBar.parentElement;
var statusPercent = element("statusPercent");
var statusTitle = element("statusTitle");
var statusMessage = element("statusMessage");
var activityLog = element("activityLog");
var cancelButton = element("cancelButton");
var resultTitle = element("resultTitle");
var resultSummary = element("resultSummary");
var downloadButton = element("downloadButton");
var copyButton = element("copyButton");
var previewShell = element("previewShell");
var preview = element("preview");
var previewName = element("previewName");
var bundlePanel = element("bundlePanel");
var errorTitle = element("errorTitle");
var errorMessageText = element("errorMessage");
var toast = element("toast");
initializeTheme();
bindEvents();
renderSources();
updateOutputMode();
updateSettingsSummary();
function bindEvents() {
  element("themeToggle").addEventListener("click", toggleTheme);
  settingsButton.addEventListener("click", openSettings);
  element("editSettings").addEventListener("click", openSettings);
  element("closeSettings").addEventListener("click", closeSettings);
  element("doneSettings").addEventListener("click", closeSettings);
  drawerBackdrop.addEventListener("click", closeSettings);
  document.addEventListener("keydown", handleGlobalKeydown);
  element("chooseFiles").addEventListener("click", (event) => {
    event.stopPropagation();
    if (viewState === "setup") fileInput.click();
  });
  element("chooseFolder").addEventListener("click", (event) => {
    event.stopPropagation();
    if (viewState === "setup") folderInput.click();
  });
  dropzone.addEventListener("click", () => {
    if (viewState === "setup") fileInput.click();
  });
  dropzone.addEventListener("keydown", (event) => {
    if (viewState !== "setup") return;
    if (event.key === "Enter" || event.key === " ") {
      event.preventDefault();
      fileInput.click();
    }
  });
  for (const eventName of ["dragenter", "dragover"]) {
    dropzone.addEventListener(eventName, (event) => {
      event.preventDefault();
      if (viewState === "setup") dropzone.classList.add("dragging");
    });
  }
  for (const eventName of ["dragleave", "drop"]) {
    dropzone.addEventListener(eventName, (event) => {
      event.preventDefault();
      dropzone.classList.remove("dragging");
    });
  }
  dropzone.addEventListener("drop", (event) => {
    if (viewState !== "setup") return;
    addFiles(Array.from(event.dataTransfer?.files ?? []));
  });
  fileInput.addEventListener("change", () => {
    addFiles(Array.from(fileInput.files ?? []));
    fileInput.value = "";
  });
  folderInput.addEventListener("change", () => {
    addFiles(Array.from(folderInput.files ?? []));
    folderInput.value = "";
  });
  element("addUrl").addEventListener("click", addUrl);
  urlInput.addEventListener("keydown", (event) => {
    if (event.key === "Enter") {
      event.preventDefault();
      addUrl();
    }
  });
  document.querySelectorAll('input[name="outputMode"]').forEach((radio) => radio.addEventListener("change", updateOutputMode));
  for (const controlId of [
    "filterMode",
    "ocrMode",
    "includeToc",
    "notebookOutputs",
    "includePatterns",
    "excludePatterns",
    "chunkTarget",
    "chunkOverlap"
  ]) {
    const control = element(controlId);
    control.addEventListener("change", updateSettingsSummary);
    control.addEventListener("input", updateSettingsSummary);
  }
  setupView.addEventListener("submit", submitJob);
  cancelButton.addEventListener("click", cancelJob);
  element("newJobButton").addEventListener("click", () => {
    void resetForNewJob();
  });
  element("errorBackButton").addEventListener("click", () => {
    void returnToSetup();
  });
  copyButton.addEventListener("click", () => {
    void copyMarkdown();
  });
}
function addFiles(files) {
  if (viewState !== "setup") return;
  if (!files.length) {
    showToast("No files selected.");
    return;
  }
  const firstPath = relativePath(files[0]);
  const root = firstPath.includes("/") ? firstPath.split("/")[0] : "";
  const label = root || (files.length === 1 ? files[0].name : `${files.length} files`);
  sources.push({
    spec: { id: sourceId(), kind: "upload", label },
    files
  });
  if (!outputName.value) outputName.value = cleanOutputName(label);
  renderSources();
}
function addUrl() {
  if (viewState !== "setup") return;
  const value = urlInput.value.trim();
  if (!value) return showToast("Enter a repository or page URL.");
  let parsed;
  try {
    parsed = new URL(value);
  } catch {
    return showToast("That URL is not valid.");
  }
  if (parsed.username || parsed.password) {
    return showToast("URLs cannot contain credentials.");
  }
  if (!["http:", "https:"].includes(parsed.protocol)) {
    return showToast("Only HTTP and HTTPS URLs are supported.");
  }
  const githubMatch = parsed.hostname.toLowerCase() === "github.com" && /^\/[A-Za-z0-9_.-]+\/[A-Za-z0-9_.-]+(?:\.git)?\/?$/.test(parsed.pathname);
  const kind = githubMatch ? "github" : "web";
  const pathLabel = parsed.pathname.replace(/^\//, "").replace(/\/$/, "") || parsed.hostname;
  const label = githubMatch ? pathLabel.replace(/\.git$/, "") : `${parsed.hostname}/${pathLabel}`.replace(/\/$/, "");
  sources.push({
    spec: {
      id: sourceId(),
      kind,
      label,
      url: parsed.toString(),
      ...githubMatch && refInput.value.trim() ? { ref: refInput.value.trim() } : {}
    }
  });
  if (!outputName.value) {
    outputName.value = cleanOutputName(pathLabel.split("/").pop() ?? "web-page");
  }
  urlInput.value = "";
  refInput.value = "";
  renderSources();
}
function renderSources() {
  sourceList.replaceChildren();
  sourceCount.textContent = String(sources.length);
  if (!sources.length) {
    const empty = document.createElement("div");
    empty.className = "source-empty";
    empty.textContent = "No sources added";
    sourceList.append(empty);
  }
  for (const source of sources) {
    const item = document.createElement("div");
    item.className = "source-item";
    const type = document.createElement("span");
    type.className = "source-type";
    type.textContent = source.spec.kind === "upload" ? "local" : source.spec.kind;
    const info = document.createElement("div");
    info.className = "source-info";
    const title = document.createElement("strong");
    title.textContent = source.spec.label;
    const detail = document.createElement("small");
    detail.textContent = source.files ? `${source.files.length} file${source.files.length === 1 ? "" : "s"} \xB7 ${formatBytes(source.files.reduce((sum, file) => sum + file.size, 0))}` : source.spec.url ?? "";
    info.append(title, detail);
    const remove = document.createElement("button");
    remove.className = "remove-source";
    remove.type = "button";
    remove.textContent = "\xD7";
    remove.disabled = viewState !== "setup";
    remove.setAttribute("aria-label", `Remove ${source.spec.label}`);
    remove.addEventListener("click", () => {
      const index = sources.indexOf(source);
      if (index >= 0) sources.splice(index, 1);
      renderSources();
    });
    item.append(type, info, remove);
    sourceList.append(item);
  }
  const label = `${sources.length} source${sources.length === 1 ? "" : "s"}`;
  setupStatus.textContent = sources.length ? label : "Add a source";
  readyNote.textContent = sources.length ? `${label} ready` : "Waiting for sources";
  convertButton.disabled = sources.length === 0;
}
async function submitJob(event) {
  event.preventDefault();
  if (!sources.length) return showToast("Add a source first.");
  closeSettings();
  const mode = selectedOutputMode();
  const specFiles = [];
  const form = new FormData();
  if (sources.length > 64) return showToast("Use up to 64 sources per conversion.");
  const maxFileBytes = 100 * 1024 ** 2;
  const maxUploadBytes = 512 * 1024 ** 2;
  let partIndex = 0;
  let uploadBytes = 0;
  for (const source of sources) {
    for (const file of source.files ?? []) {
      uploadBytes += file.size;
      if (file.size > maxFileBytes) return showToast("Each file must be 100 MiB or smaller.");
      if (uploadBytes > maxUploadBytes || partIndex >= 2e4) {
        return showToast("Upload up to 512 MiB and 20,000 files at a time.");
      }
      const part = `upload_${partIndex++}`;
      form.append(part, file, file.name);
      specFiles.push({
        part,
        source_id: source.spec.id,
        relative_path: relativePath(file)
      });
    }
  }
  const payload = {
    sources: sources.map((source) => source.spec),
    files: specFiles,
    options: {
      output_name: outputName.value.trim(),
      output_mode: mode,
      filter_mode: element("filterMode").value,
      include_patterns: patternLines(element("includePatterns").value),
      exclude_patterns: patternLines(element("excludePatterns").value),
      ocr_mode: element("ocrMode").value,
      include_notebook_outputs: element("notebookOutputs").checked,
      include_toc: element("includeToc").checked,
      chunk_target: Number(element("chunkTarget").value),
      chunk_overlap: Number(element("chunkOverlap").value)
    }
  };
  form.append("spec", JSON.stringify(payload));
  showProcessing();
  try {
    const response = await uploadJob(form, (loaded, total) => {
      const percent = total ? Math.round(loaded / total * 10) : 2;
      setProgress(percent, "Uploading sources\u2026");
    });
    activeJob = response.job;
    cancelButton.disabled = false;
    listenForEvents(activeJob.id, response.events_url);
  } catch (error) {
    showFailure(errorMessage(error));
  }
}
function uploadJob(form, onProgress) {
  return new Promise((resolve, reject) => {
    const request = new XMLHttpRequest();
    request.open("POST", "/api/v1/jobs");
    request.withCredentials = true;
    request.setRequestHeader("X-AutoMD-Token", token);
    request.upload.addEventListener(
      "progress",
      (event) => onProgress(event.loaded, event.total)
    );
    request.addEventListener("load", () => {
      let value;
      try {
        value = JSON.parse(request.responseText);
      } catch {
        value = { error: request.statusText };
      }
      if (request.status === 202) {
        resolve(value);
      } else {
        reject(new Error(value.error ?? "Unable to start conversion"));
      }
    });
    request.addEventListener(
      "error",
      () => reject(new Error("The local server could not be reached."))
    );
    request.send(form);
  });
}
function listenForEvents(jobId, eventsUrl) {
  eventSource?.close();
  eventSource = new EventSource(eventsUrl);
  for (const eventName of ["progress", "complete", "failed", "cancelled"]) {
    eventSource.addEventListener(eventName, (rawEvent) => {
      const event = JSON.parse(rawEvent.data);
      handleProgress(event);
      if (["complete", "failed", "cancelled"].includes(event.event)) {
        eventSource?.close();
        void finishJob(jobId);
      }
    });
  }
  eventSource.onerror = () => {
    if (activeJob && !isTerminal(activeJob.status)) {
      statusMessage.textContent = "Reconnecting\u2026";
    }
  };
}
function handleProgress(event) {
  const phaseStart = {
    starting: 1,
    acquiring: 5,
    extracting: 18,
    packaging: 92,
    complete: 100,
    cancelling: 95,
    failed: 100,
    cancelled: 100
  };
  const phaseSpan = { acquiring: 13, extracting: 74, packaging: 7 };
  const start = phaseStart[event.phase] ?? 1;
  const ratio = event.total > 0 ? event.completed / event.total : 0;
  const percent = Math.min(100, Math.round(start + (phaseSpan[event.phase] ?? 0) * ratio));
  setProgress(percent, event.message);
  statusTitle.textContent = phaseTitle(event.phase);
  const logItem = document.createElement("li");
  logItem.textContent = event.message;
  activityLog.append(logItem);
  if (activityLog.children.length > 100) activityLog.firstElementChild?.remove();
}
async function finishJob(jobId) {
  try {
    const response = await fetch(`/api/v1/jobs/${encodeURIComponent(jobId)}`, {
      credentials: "same-origin"
    });
    if (!response.ok) throw new Error("Unable to read the completed job.");
    activeJob = await response.json();
    if (activeJob.status === "failed") {
      return showFailure(activeJob.error ?? "Conversion failed.");
    }
    if (activeJob.status === "cancelled") {
      return showFailure("The job was cancelled.", "Conversion cancelled");
    }
    showResult(activeJob);
  } catch (error) {
    showFailure(errorMessage(error));
  }
}
async function cancelJob() {
  if (!activeJob) return;
  cancelButton.disabled = true;
  statusMessage.textContent = "Cancelling\u2026";
  try {
    const response = await fetch(`/api/v1/jobs/${encodeURIComponent(activeJob.id)}/cancel`, {
      method: "POST",
      credentials: "same-origin",
      headers: { "X-AutoMD-Token": token }
    });
    if (!response.ok) throw new Error("Unable to cancel the job.");
  } catch (error) {
    cancelButton.disabled = false;
    showToast(errorMessage(error));
  }
}
function showProcessing() {
  activityLog.replaceChildren();
  cancelButton.disabled = true;
  setProgress(1, "Preparing upload\u2026");
  statusTitle.textContent = "Preparing sources";
  setView("processing");
}
function showResult(job) {
  const artifact = job.artifacts[0];
  if (!artifact) return showFailure("No downloadable artifact was produced.");
  resultTitle.textContent = artifact.name;
  const summary = [
    `${job.document_count} document${job.document_count === 1 ? "" : "s"}`,
    ...job.skipped_count ? [`${job.skipped_count} skipped`] : [],
    ...job.warning_count ? [`${job.warning_count} warning${job.warning_count === 1 ? "" : "s"}`] : []
  ];
  resultSummary.textContent = summary.join(" \xB7 ");
  const url = `/api/v1/jobs/${encodeURIComponent(job.id)}/artifacts/${encodeURIComponent(artifact.id)}`;
  downloadButton.href = url;
  downloadButton.download = artifact.name;
  previewName.textContent = artifact.name;
  previewRequest?.abort();
  markdownUrl = null;
  preview.textContent = "Loading\u2026";
  if (artifact.media_type === "text/markdown") {
    copyButton.classList.remove("hidden");
    previewShell.classList.remove("hidden");
    bundlePanel.classList.add("hidden");
    markdownUrl = url;
    void loadPreview(url);
  } else {
    copyButton.classList.add("hidden");
    previewShell.classList.add("hidden");
    bundlePanel.classList.remove("hidden");
  }
  setView("result");
}
async function loadPreview(url) {
  const request = new AbortController();
  previewRequest = request;
  try {
    const response = await fetch(`${url}?preview=1`, {
      credentials: "same-origin",
      signal: request.signal
    });
    if (!response.ok) throw new Error("Preview unavailable.");
    const text = await response.text();
    if (!request.signal.aborted) {
      preview.textContent = text.length >= 12e4 ? `${text}

[Preview limited. Copy or download for the full file.]` : text;
    }
  } catch (error) {
    if (!request.signal.aborted) preview.textContent = errorMessage(error);
  }
}
function showFailure(message, title = "Conversion failed") {
  eventSource?.close();
  errorTitle.textContent = title;
  errorMessageText.textContent = message;
  setView("error");
}
async function returnToSetup() {
  eventSource?.close();
  if (activeJob && isTerminal(activeJob.status)) await deleteJob(activeJob.id);
  activeJob = null;
  setView("setup");
  convertButton.focus();
}
async function resetForNewJob() {
  eventSource?.close();
  if (activeJob) await deleteJob(activeJob.id);
  activeJob = null;
  previewRequest?.abort();
  markdownUrl = null;
  sources.splice(0);
  outputName.value = "";
  renderSources();
  setView("setup");
  dropzone.focus();
}
async function deleteJob(jobId) {
  try {
    await fetch(`/api/v1/jobs/${encodeURIComponent(jobId)}`, {
      method: "DELETE",
      credentials: "same-origin",
      headers: { "X-AutoMD-Token": token }
    });
  } catch {
  }
}
async function copyMarkdown() {
  if (!markdownUrl || !navigator.clipboard) return showToast("Clipboard access is unavailable.");
  copyButton.disabled = true;
  try {
    const response = fetch(markdownUrl, { credentials: "same-origin" }).then((reply) => {
      if (!reply.ok) throw new Error("Markdown download failed.");
      return reply;
    });
    if (typeof ClipboardItem === "function" && typeof navigator.clipboard.write === "function") {
      const data = response.then(async (reply) => new Blob([await reply.blob()], { type: "text/plain" }));
      await navigator.clipboard.write([new ClipboardItem({ "text/plain": data })]);
    } else {
      await navigator.clipboard.writeText(await (await response).text());
    }
    showToast("Markdown copied.");
  } catch {
    showToast("Could not copy the Markdown. Use Download to save it.");
  } finally {
    copyButton.disabled = false;
  }
}
function setView(next) {
  viewState = next;
  for (const [name, view] of Object.entries(views)) {
    const active = name === next;
    view.classList.toggle("active", active);
    view.setAttribute("aria-hidden", String(!active));
  }
  const locked = next !== "setup";
  setSourceControlsDisabled(locked);
  settingsButton.disabled = locked;
  renderSources();
}
function setSourceControlsDisabled(disabled) {
  fileInput.disabled = disabled;
  folderInput.disabled = disabled;
  urlInput.disabled = disabled;
  refInput.disabled = disabled;
  element("chooseFiles").disabled = disabled;
  element("chooseFolder").disabled = disabled;
  element("addUrl").disabled = disabled;
  dropzone.setAttribute("aria-disabled", String(disabled));
  dropzone.tabIndex = disabled ? -1 : 0;
}
function updateOutputMode() {
  document.querySelectorAll(".segment").forEach((option) => {
    const radio = option.querySelector('input[type="radio"]');
    option.classList.toggle("selected", radio?.checked ?? false);
  });
  const rag = selectedOutputMode() === "rag";
  chunkSettings.classList.toggle("hidden", !rag);
  outputSuffix.textContent = rag ? "-rag.zip" : ".md";
  convertButton.querySelector("span").textContent = rag ? "Build bundle" : "Create .md";
  updateSettingsSummary();
}
function updateSettingsSummary() {
  const filter = element("filterMode").value;
  const ocr = element("ocrMode").value;
  const toc = element("includeToc").checked;
  const notebook = element("notebookOutputs").checked;
  filterSummary.textContent = { smart: "Smart filter", project: "Project ignores", all: "All files" }[filter] ?? "Filter";
  ocrSummary.textContent = { auto: "OCR auto", always: "OCR on", never: "OCR off" }[ocr] ?? "OCR";
  const details = [toc ? "TOC on" : "TOC off"];
  if (notebook) details.push("Notebook output");
  if (selectedOutputMode() === "rag") {
    details.push(`${element("chunkTarget").value} target`);
  }
  detailSummary.textContent = details.join(" \xB7 ");
}
function selectedOutputMode() {
  return document.querySelector('input[name="outputMode"]:checked')?.value ?? "markdown";
}
function openSettings() {
  if (viewState !== "setup") return;
  drawerReturnFocus = document.activeElement instanceof HTMLElement ? document.activeElement : null;
  settingsDrawer.classList.add("open");
  drawerBackdrop.classList.add("open");
  settingsDrawer.setAttribute("aria-hidden", "false");
  drawerBackdrop.setAttribute("aria-hidden", "false");
  settingsButton.setAttribute("aria-expanded", "true");
  window.setTimeout(() => element("closeSettings").focus(), 0);
}
function closeSettings() {
  if (!settingsDrawer.classList.contains("open")) return;
  settingsDrawer.classList.remove("open");
  drawerBackdrop.classList.remove("open");
  settingsDrawer.setAttribute("aria-hidden", "true");
  drawerBackdrop.setAttribute("aria-hidden", "true");
  settingsButton.setAttribute("aria-expanded", "false");
  updateSettingsSummary();
  drawerReturnFocus?.focus();
  drawerReturnFocus = null;
}
function handleGlobalKeydown(event) {
  if (!settingsDrawer.classList.contains("open")) return;
  if (event.key === "Escape") {
    event.preventDefault();
    closeSettings();
    return;
  }
  if (event.key !== "Tab") return;
  const focusable = Array.from(
    settingsDrawer.querySelectorAll(
      'button:not(:disabled), input:not(:disabled), select:not(:disabled), textarea:not(:disabled), [href], [tabindex]:not([tabindex="-1"])'
    )
  ).filter((item) => item.getClientRects().length > 0);
  const first = focusable[0];
  const last = focusable.at(-1);
  if (!first || !last) return;
  if (event.shiftKey && document.activeElement === first) {
    event.preventDefault();
    last.focus();
  } else if (!event.shiftKey && document.activeElement === last) {
    event.preventDefault();
    first.focus();
  }
}
function setProgress(percent, message) {
  progressBar.style.width = `${percent}%`;
  progressTrack.setAttribute("aria-valuenow", String(percent));
  statusPercent.textContent = `${percent}%`;
  statusMessage.textContent = message;
}
function phaseTitle(phase) {
  return {
    starting: "Starting",
    acquiring: "Preparing sources",
    extracting: "Extracting documents",
    packaging: "Packaging output",
    cancelling: "Cancelling",
    complete: "Complete",
    failed: "Failed",
    cancelled: "Cancelled"
  }[phase] ?? "Processing";
}
function relativePath(file) {
  return file.webkitRelativePath || file.name;
}
function sourceId() {
  return crypto.randomUUID().replaceAll("-", "");
}
function cleanOutputName(value) {
  return value.replace(/\.(?:zip|md)$/i, "").replace(/[^\p{L}\p{N}._ -]+/gu, "-").replace(/[ .-]+/g, "-").replace(/^-|-$/g, "").slice(0, 100) || "automd-output";
}
function patternLines(value) {
  return value.split(/\r?\n/).map((line) => line.trim()).filter(Boolean);
}
function formatBytes(value) {
  if (value < 1024) return `${value} B`;
  const units = ["KB", "MB", "GB"];
  let size = value / 1024;
  let unit = units[0];
  for (let index = 1; size >= 1024 && index < units.length; index++) {
    size /= 1024;
    unit = units[index];
  }
  return `${size.toFixed(size >= 10 ? 0 : 1)} ${unit}`;
}
function initializeTheme() {
  const saved = localStorage.getItem("automd-theme");
  if (saved === "light" || saved === "dark") document.documentElement.dataset.theme = saved;
  updateThemeColor();
}
function toggleTheme() {
  const current = document.documentElement.dataset.theme;
  const systemDark = matchMedia("(prefers-color-scheme: dark)").matches;
  const next = current === "dark" || !current && systemDark ? "light" : "dark";
  document.documentElement.dataset.theme = next;
  localStorage.setItem("automd-theme", next);
  updateThemeColor();
}
function updateThemeColor() {
  const dark = document.documentElement.dataset.theme === "dark" || !document.documentElement.dataset.theme && matchMedia("(prefers-color-scheme: dark)").matches;
  document.querySelector('meta[name="theme-color"]')?.setAttribute(
    "content",
    dark ? "#101116" : "#f4f5f7"
  );
}
function showToast(message) {
  toast.textContent = message;
  toast.classList.add("visible");
  window.clearTimeout(toastTimer);
  toastTimer = window.setTimeout(() => toast.classList.remove("visible"), 2800);
}
function errorMessage(value) {
  return value instanceof Error ? value.message : String(value);
}
function isTerminal(status) {
  return ["completed", "completed_with_warnings", "failed", "cancelled"].includes(status);
}
function element(id) {
  const value = document.getElementById(id);
  if (!value) throw new Error(`Missing element #${id}`);
  return value;
}
