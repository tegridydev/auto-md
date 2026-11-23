type SourceKind = "upload" | "github" | "web";
type OutputMode = "markdown" | "rag";
type ViewState = "setup" | "processing" | "result" | "error";
type JobStatus =
  | "queued"
  | "running"
  | "completed"
  | "completed_with_warnings"
  | "failed"
  | "cancelled";

interface SourceSpec {
  id: string;
  kind: SourceKind;
  label: string;
  url?: string;
  ref?: string;
}

interface LocalSource {
  spec: SourceSpec;
  files?: File[];
}

interface ArtifactSummary {
  id: string;
  name: string;
  media_type: string;
  size: number;
  sha256: string;
}

interface JobSnapshot {
  id: string;
  status: JobStatus;
  message: string;
  document_count: number;
  skipped_count: number;
  warning_count: number;
  error: string | null;
  artifacts: ArtifactSummary[];
}

interface JobProgressEvent {
  sequence: number;
  event: string;
  phase: string;
  completed: number;
  total: number;
  message: string;
  source_id: string | null;
}

const token =
  document.querySelector<HTMLMetaElement>('meta[name="automd-token"]')?.content ?? "";
const sources: LocalSource[] = [];
let activeJob: JobSnapshot | null = null;
let eventSource: EventSource | null = null;
let previewRequest: AbortController | null = null;
let markdownUrl: string | null = null;
let toastTimer = 0;
let viewState: ViewState = "setup";
let drawerReturnFocus: HTMLElement | null = null;

const setupView = element<HTMLFormElement>("setupView");
const processingView = element<HTMLElement>("processingView");
const resultView = element<HTMLElement>("resultView");
const errorView = element<HTMLElement>("errorView");
const views: Record<ViewState, HTMLElement> = {
  setup: setupView,
  processing: processingView,
  result: resultView,
  error: errorView,
};

const dropzone = element<HTMLElement>("dropzone");
const fileInput = element<HTMLInputElement>("fileInput");
const folderInput = element<HTMLInputElement>("folderInput");
const sourceList = element<HTMLElement>("sourceList");
const sourceCount = element<HTMLElement>("sourceCount");
const urlInput = element<HTMLInputElement>("urlInput");
const refInput = element<HTMLInputElement>("refInput");
const outputName = element<HTMLInputElement>("outputName");
const outputSuffix = element<HTMLElement>("outputSuffix");
const setupStatus = element<HTMLElement>("setupStatus");
const readyNote = element<HTMLElement>("readyNote");
const convertButton = element<HTMLButtonElement>("convertButton");
const settingsButton = element<HTMLButtonElement>("settingsButton");
const settingsDrawer = element<HTMLElement>("settingsDrawer");
const drawerBackdrop = element<HTMLElement>("drawerBackdrop");
const chunkSettings = element<HTMLElement>("chunkSettings");
const filterSummary = element<HTMLElement>("filterSummary");
const ocrSummary = element<HTMLElement>("ocrSummary");
const detailSummary = element<HTMLElement>("detailSummary");
const progressBar = element<HTMLElement>("progressBar");
const progressTrack = progressBar.parentElement as HTMLElement;
const statusPercent = element<HTMLElement>("statusPercent");
const statusTitle = element<HTMLElement>("statusTitle");
const statusMessage = element<HTMLElement>("statusMessage");
const activityLog = element<HTMLOListElement>("activityLog");
const cancelButton = element<HTMLButtonElement>("cancelButton");
const resultTitle = element<HTMLElement>("resultTitle");
const resultSummary = element<HTMLElement>("resultSummary");
const downloadButton = element<HTMLAnchorElement>("downloadButton");
const copyButton = element<HTMLButtonElement>("copyButton");
const previewShell = element<HTMLElement>("previewShell");
const preview = element<HTMLElement>("preview");
const previewName = element<HTMLElement>("previewName");
const bundlePanel = element<HTMLElement>("bundlePanel");
const errorTitle = element<HTMLElement>("errorTitle");
const errorMessageText = element<HTMLElement>("errorMessage");
const toast = element<HTMLElement>("toast");

initializeTheme();
bindEvents();
renderSources();
updateOutputMode();
updateSettingsSummary();

function bindEvents(): void {
  element<HTMLButtonElement>("themeToggle").addEventListener("click", toggleTheme);
  settingsButton.addEventListener("click", openSettings);
  element<HTMLButtonElement>("editSettings").addEventListener("click", openSettings);
  element<HTMLButtonElement>("closeSettings").addEventListener("click", closeSettings);
  element<HTMLButtonElement>("doneSettings").addEventListener("click", closeSettings);
  drawerBackdrop.addEventListener("click", closeSettings);
  document.addEventListener("keydown", handleGlobalKeydown);

  element<HTMLButtonElement>("chooseFiles").addEventListener("click", (event) => {
    event.stopPropagation();
    if (viewState === "setup") fileInput.click();
  });
  element<HTMLButtonElement>("chooseFolder").addEventListener("click", (event) => {
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
  element<HTMLButtonElement>("addUrl").addEventListener("click", addUrl);
  urlInput.addEventListener("keydown", (event) => {
    if (event.key === "Enter") {
      event.preventDefault();
      addUrl();
    }
  });

  document
    .querySelectorAll<HTMLInputElement>('input[name="outputMode"]')
    .forEach((radio) => radio.addEventListener("change", updateOutputMode));
  for (const controlId of [
    "filterMode",
    "ocrMode",
    "includeToc",
    "notebookOutputs",
    "includePatterns",
    "excludePatterns",
    "chunkTarget",
    "chunkOverlap",
  ]) {
    const control = element<HTMLInputElement | HTMLSelectElement | HTMLTextAreaElement>(controlId);
    control.addEventListener("change", updateSettingsSummary);
    control.addEventListener("input", updateSettingsSummary);
  }

  setupView.addEventListener("submit", submitJob);
  cancelButton.addEventListener("click", cancelJob);
  element<HTMLButtonElement>("newJobButton").addEventListener("click", () => {
    void resetForNewJob();
  });
  element<HTMLButtonElement>("errorBackButton").addEventListener("click", () => {
    void returnToSetup();
  });
  copyButton.addEventListener("click", () => {
    void copyMarkdown();
  });
}

function addFiles(files: File[]): void {
  if (viewState !== "setup") return;
  if (!files.length) {
    showToast("No files selected.");
    return;
  }
  const firstPath = relativePath(files[0]!);
  const root = firstPath.includes("/") ? firstPath.split("/")[0]! : "";
  const label = root || (files.length === 1 ? files[0]!.name : `${files.length} files`);
  sources.push({
    spec: { id: sourceId(), kind: "upload", label },
    files,
  });
  if (!outputName.value) outputName.value = cleanOutputName(label);
  renderSources();
}

function addUrl(): void {
  if (viewState !== "setup") return;
  const value = urlInput.value.trim();
  if (!value) return showToast("Enter a repository or page URL.");
  let parsed: URL;
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
  const githubMatch =
    parsed.hostname.toLowerCase() === "github.com" &&
    /^\/[A-Za-z0-9_.-]+\/[A-Za-z0-9_.-]+(?:\.git)?\/?$/.test(parsed.pathname);
  const kind: SourceKind = githubMatch ? "github" : "web";
  const pathLabel = parsed.pathname.replace(/^\//, "").replace(/\/$/, "") || parsed.hostname;
  const label = githubMatch
    ? pathLabel.replace(/\.git$/, "")
    : `${parsed.hostname}/${pathLabel}`.replace(/\/$/, "");
  sources.push({
    spec: {
      id: sourceId(),
      kind,
      label,
      url: parsed.toString(),
      ...(githubMatch && refInput.value.trim() ? { ref: refInput.value.trim() } : {}),
    },
  });
  if (!outputName.value) {
    outputName.value = cleanOutputName(pathLabel.split("/").pop() ?? "web-page");
  }
  urlInput.value = "";
  refInput.value = "";
  renderSources();
}

function renderSources(): void {
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
    detail.textContent = source.files
      ? `${source.files.length} file${source.files.length === 1 ? "" : "s"} · ${formatBytes(source.files.reduce((sum, file) => sum + file.size, 0))}`
      : (source.spec.url ?? "");
    info.append(title, detail);
    const remove = document.createElement("button");
    remove.className = "remove-source";
    remove.type = "button";
    remove.textContent = "×";
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

async function submitJob(event: SubmitEvent): Promise<void> {
  event.preventDefault();
  if (!sources.length) return showToast("Add a source first.");
  closeSettings();
  const mode = selectedOutputMode();
  const specFiles: Array<{ part: string; source_id: string; relative_path: string }> = [];
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
      if (uploadBytes > maxUploadBytes || partIndex >= 20_000) {
        return showToast("Upload up to 512 MiB and 20,000 files at a time.");
      }
      const part = `upload_${partIndex++}`;
      form.append(part, file, file.name);
      specFiles.push({
        part,
        source_id: source.spec.id,
        relative_path: relativePath(file),
      });
    }
  }
  const payload = {
    sources: sources.map((source) => source.spec),
    files: specFiles,
    options: {
      output_name: outputName.value.trim(),
      output_mode: mode,
      filter_mode: element<HTMLSelectElement>("filterMode").value,
      include_patterns: patternLines(element<HTMLTextAreaElement>("includePatterns").value),
      exclude_patterns: patternLines(element<HTMLTextAreaElement>("excludePatterns").value),
      ocr_mode: element<HTMLSelectElement>("ocrMode").value,
      include_notebook_outputs: element<HTMLInputElement>("notebookOutputs").checked,
      include_toc: element<HTMLInputElement>("includeToc").checked,
      chunk_target: Number(element<HTMLInputElement>("chunkTarget").value),
      chunk_overlap: Number(element<HTMLInputElement>("chunkOverlap").value),
    },
  };
  form.append("spec", JSON.stringify(payload));
  showProcessing();
  try {
    const response = await uploadJob(form, (loaded, total) => {
      const percent = total ? Math.round((loaded / total) * 10) : 2;
      setProgress(percent, "Uploading sources…");
    });
    activeJob = response.job;
    cancelButton.disabled = false;
    listenForEvents(activeJob.id, response.events_url);
  } catch (error) {
    showFailure(errorMessage(error));
  }
}

function uploadJob(
  form: FormData,
  onProgress: (loaded: number, total: number) => void,
): Promise<{ job: JobSnapshot; events_url: string }> {
  return new Promise((resolve, reject) => {
    const request = new XMLHttpRequest();
    request.open("POST", "/api/v1/jobs");
    request.withCredentials = true;
    request.setRequestHeader("X-AutoMD-Token", token);
    request.upload.addEventListener("progress", (event) =>
      onProgress(event.loaded, event.total),
    );
    request.addEventListener("load", () => {
      let value: unknown;
      try {
        value = JSON.parse(request.responseText);
      } catch {
        value = { error: request.statusText };
      }
      if (request.status === 202) {
        resolve(value as { job: JobSnapshot; events_url: string });
      } else {
        reject(new Error((value as { error?: string }).error ?? "Unable to start conversion"));
      }
    });
    request.addEventListener("error", () =>
      reject(new Error("The local server could not be reached.")),
    );
    request.send(form);
  });
}

function listenForEvents(jobId: string, eventsUrl: string): void {
  eventSource?.close();
  eventSource = new EventSource(eventsUrl);
  for (const eventName of ["progress", "complete", "failed", "cancelled"]) {
    eventSource.addEventListener(eventName, (rawEvent) => {
      const event = JSON.parse((rawEvent as MessageEvent<string>).data) as JobProgressEvent;
      handleProgress(event);
      if (["complete", "failed", "cancelled"].includes(event.event)) {
        eventSource?.close();
        void finishJob(jobId);
      }
    });
  }
  eventSource.onerror = () => {
    if (activeJob && !isTerminal(activeJob.status)) {
      statusMessage.textContent = "Reconnecting…";
    }
  };
}

function handleProgress(event: JobProgressEvent): void {
  const phaseStart: Record<string, number> = {
    starting: 1,
    acquiring: 5,
    extracting: 18,
    packaging: 92,
    complete: 100,
    cancelling: 95,
    failed: 100,
    cancelled: 100,
  };
  const phaseSpan: Record<string, number> = { acquiring: 13, extracting: 74, packaging: 7 };
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

async function finishJob(jobId: string): Promise<void> {
  try {
    const response = await fetch(`/api/v1/jobs/${encodeURIComponent(jobId)}`, {
      credentials: "same-origin",
    });
    if (!response.ok) throw new Error("Unable to read the completed job.");
    activeJob = (await response.json()) as JobSnapshot;
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

async function cancelJob(): Promise<void> {
  if (!activeJob) return;
  cancelButton.disabled = true;
  statusMessage.textContent = "Cancelling…";
  try {
    const response = await fetch(`/api/v1/jobs/${encodeURIComponent(activeJob.id)}/cancel`, {
      method: "POST",
      credentials: "same-origin",
      headers: { "X-AutoMD-Token": token },
    });
    if (!response.ok) throw new Error("Unable to cancel the job.");
  } catch (error) {
    cancelButton.disabled = false;
    showToast(errorMessage(error));
  }
}

function showProcessing(): void {
  activityLog.replaceChildren();
  cancelButton.disabled = true;
  setProgress(1, "Preparing upload…");
  statusTitle.textContent = "Preparing sources";
  setView("processing");
}

function showResult(job: JobSnapshot): void {
  const artifact = job.artifacts[0];
  if (!artifact) return showFailure("No downloadable artifact was produced.");
  resultTitle.textContent = artifact.name;
  const summary = [
    `${job.document_count} document${job.document_count === 1 ? "" : "s"}`,
    ...(job.skipped_count ? [`${job.skipped_count} skipped`] : []),
    ...(job.warning_count ? [`${job.warning_count} warning${job.warning_count === 1 ? "" : "s"}`] : []),
  ];
  resultSummary.textContent = summary.join(" · ");
  const url = `/api/v1/jobs/${encodeURIComponent(job.id)}/artifacts/${encodeURIComponent(artifact.id)}`;
  downloadButton.href = url;
  downloadButton.download = artifact.name;
  previewName.textContent = artifact.name;
  previewRequest?.abort();
  markdownUrl = null;
  preview.textContent = "Loading…";
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

async function loadPreview(url: string): Promise<void> {
  const request = new AbortController();
  previewRequest = request;
  try {
    const response = await fetch(`${url}?preview=1`, {
      credentials: "same-origin",
      signal: request.signal,
    });
    if (!response.ok) throw new Error("Preview unavailable.");
    const text = await response.text();
    if (!request.signal.aborted) {
      preview.textContent = text.length >= 120_000
        ? `${text}\n\n[Preview limited. Copy or download for the full file.]`
        : text;
    }
  } catch (error) {
    if (!request.signal.aborted) preview.textContent = errorMessage(error);
  }
}

function showFailure(message: string, title = "Conversion failed"): void {
  eventSource?.close();
  errorTitle.textContent = title;
  errorMessageText.textContent = message;
  setView("error");
}

async function returnToSetup(): Promise<void> {
  eventSource?.close();
  if (activeJob && isTerminal(activeJob.status)) await deleteJob(activeJob.id);
  activeJob = null;
  setView("setup");
  convertButton.focus();
}

async function resetForNewJob(): Promise<void> {
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

async function deleteJob(jobId: string): Promise<void> {
  try {
    await fetch(`/api/v1/jobs/${encodeURIComponent(jobId)}`, {
      method: "DELETE",
      credentials: "same-origin",
      headers: { "X-AutoMD-Token": token },
    });
  } catch {
    // The process-level cleanup remains the final fallback.
  }
}

async function copyMarkdown(): Promise<void> {
  if (!markdownUrl || !navigator.clipboard) return showToast("Clipboard access is unavailable.");
  copyButton.disabled = true;
  try {
    const response = fetch(markdownUrl, { credentials: "same-origin" }).then((reply) => {
      if (!reply.ok) throw new Error("Markdown download failed.");
      return reply;
    });
    if (typeof ClipboardItem === "function" && typeof navigator.clipboard.write === "function") {
      // Keep clipboard permission tied to the click, even while the file is loading.
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

function setView(next: ViewState): void {
  viewState = next;
  for (const [name, view] of Object.entries(views) as Array<[ViewState, HTMLElement]>) {
    const active = name === next;
    view.classList.toggle("active", active);
    view.setAttribute("aria-hidden", String(!active));
  }
  const locked = next !== "setup";
  setSourceControlsDisabled(locked);
  settingsButton.disabled = locked;
  renderSources();
}

function setSourceControlsDisabled(disabled: boolean): void {
  fileInput.disabled = disabled;
  folderInput.disabled = disabled;
  urlInput.disabled = disabled;
  refInput.disabled = disabled;
  element<HTMLButtonElement>("chooseFiles").disabled = disabled;
  element<HTMLButtonElement>("chooseFolder").disabled = disabled;
  element<HTMLButtonElement>("addUrl").disabled = disabled;
  dropzone.setAttribute("aria-disabled", String(disabled));
  dropzone.tabIndex = disabled ? -1 : 0;
}

function updateOutputMode(): void {
  document.querySelectorAll<HTMLElement>(".segment").forEach((option) => {
    const radio = option.querySelector<HTMLInputElement>('input[type="radio"]');
    option.classList.toggle("selected", radio?.checked ?? false);
  });
  const rag = selectedOutputMode() === "rag";
  chunkSettings.classList.toggle("hidden", !rag);
  outputSuffix.textContent = rag ? "-rag.zip" : ".md";
  convertButton.querySelector("span")!.textContent = rag ? "Build bundle" : "Create .md";
  updateSettingsSummary();
}

function updateSettingsSummary(): void {
  const filter = element<HTMLSelectElement>("filterMode").value;
  const ocr = element<HTMLSelectElement>("ocrMode").value;
  const toc = element<HTMLInputElement>("includeToc").checked;
  const notebook = element<HTMLInputElement>("notebookOutputs").checked;
  filterSummary.textContent =
    ({ smart: "Smart filter", project: "Project ignores", all: "All files" } as Record<
      string,
      string
    >)[filter] ?? "Filter";
  ocrSummary.textContent =
    ({ auto: "OCR auto", always: "OCR on", never: "OCR off" } as Record<string, string>)[
      ocr
    ] ?? "OCR";
  const details = [toc ? "TOC on" : "TOC off"];
  if (notebook) details.push("Notebook output");
  if (selectedOutputMode() === "rag") {
    details.push(`${element<HTMLInputElement>("chunkTarget").value} target`);
  }
  detailSummary.textContent = details.join(" · ");
}

function selectedOutputMode(): OutputMode {
  return (document.querySelector<HTMLInputElement>('input[name="outputMode"]:checked')
    ?.value ?? "markdown") as OutputMode;
}

function openSettings(): void {
  if (viewState !== "setup") return;
  drawerReturnFocus = document.activeElement instanceof HTMLElement ? document.activeElement : null;
  settingsDrawer.classList.add("open");
  drawerBackdrop.classList.add("open");
  settingsDrawer.setAttribute("aria-hidden", "false");
  drawerBackdrop.setAttribute("aria-hidden", "false");
  settingsButton.setAttribute("aria-expanded", "true");
  window.setTimeout(() => element<HTMLButtonElement>("closeSettings").focus(), 0);
}

function closeSettings(): void {
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

function handleGlobalKeydown(event: KeyboardEvent): void {
  if (!settingsDrawer.classList.contains("open")) return;
  if (event.key === "Escape") {
    event.preventDefault();
    closeSettings();
    return;
  }
  if (event.key !== "Tab") return;
  const focusable = Array.from(
    settingsDrawer.querySelectorAll<HTMLElement>(
      'button:not(:disabled), input:not(:disabled), select:not(:disabled), textarea:not(:disabled), [href], [tabindex]:not([tabindex="-1"])',
    ),
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

function setProgress(percent: number, message: string): void {
  progressBar.style.width = `${percent}%`;
  progressTrack.setAttribute("aria-valuenow", String(percent));
  statusPercent.textContent = `${percent}%`;
  statusMessage.textContent = message;
}

function phaseTitle(phase: string): string {
  return (
    {
      starting: "Starting",
      acquiring: "Preparing sources",
      extracting: "Extracting documents",
      packaging: "Packaging output",
      cancelling: "Cancelling",
      complete: "Complete",
      failed: "Failed",
      cancelled: "Cancelled",
    } as Record<string, string>
  )[phase] ?? "Processing";
}

function relativePath(file: File): string {
  return (file as File & { webkitRelativePath?: string }).webkitRelativePath || file.name;
}

function sourceId(): string {
  return crypto.randomUUID().replaceAll("-", "");
}

function cleanOutputName(value: string): string {
  return (
    value
      .replace(/\.(?:zip|md)$/i, "")
      .replace(/[^\p{L}\p{N}._ -]+/gu, "-")
      .replace(/[ .-]+/g, "-")
      .replace(/^-|-$/g, "")
      .slice(0, 100) || "automd-output"
  );
}

function patternLines(value: string): string[] {
  return value
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter(Boolean);
}

function formatBytes(value: number): string {
  if (value < 1024) return `${value} B`;
  const units = ["KB", "MB", "GB"];
  let size = value / 1024;
  let unit = units[0]!;
  for (let index = 1; size >= 1024 && index < units.length; index++) {
    size /= 1024;
    unit = units[index]!;
  }
  return `${size.toFixed(size >= 10 ? 0 : 1)} ${unit}`;
}

function initializeTheme(): void {
  const saved = localStorage.getItem("automd-theme");
  if (saved === "light" || saved === "dark") document.documentElement.dataset.theme = saved;
  updateThemeColor();
}

function toggleTheme(): void {
  const current = document.documentElement.dataset.theme;
  const systemDark = matchMedia("(prefers-color-scheme: dark)").matches;
  const next = current === "dark" || (!current && systemDark) ? "light" : "dark";
  document.documentElement.dataset.theme = next;
  localStorage.setItem("automd-theme", next);
  updateThemeColor();
}

function updateThemeColor(): void {
  const dark =
    document.documentElement.dataset.theme === "dark" ||
    (!document.documentElement.dataset.theme && matchMedia("(prefers-color-scheme: dark)").matches);
  document.querySelector<HTMLMetaElement>('meta[name="theme-color"]')?.setAttribute(
    "content",
    dark ? "#101116" : "#f4f5f7",
  );
}

function showToast(message: string): void {
  toast.textContent = message;
  toast.classList.add("visible");
  window.clearTimeout(toastTimer);
  toastTimer = window.setTimeout(() => toast.classList.remove("visible"), 2800);
}

function errorMessage(value: unknown): string {
  return value instanceof Error ? value.message : String(value);
}

function isTerminal(status: JobStatus): boolean {
  return ["completed", "completed_with_warnings", "failed", "cancelled"].includes(status);
}

function element<T extends HTMLElement>(id: string): T {
  const value = document.getElementById(id);
  if (!value) throw new Error(`Missing element #${id}`);
  return value as T;
}
