function readMetaContent(name, fallback = "") {
  const el = document.querySelector(`meta[name="${name}"]`);
  return el ? String(el.getAttribute("content") || fallback) : String(fallback);
}

const API_KEY_REQUIRED =
  readMetaContent("ollama-api-key-required", "false") === "true";
const API_KEY_STORAGE_KEY = "ollama_web_api_key_v1";
let apiKey = localStorage.getItem(API_KEY_STORAGE_KEY) || "";

if (API_KEY_REQUIRED && !apiKey) {
  const entered = window.prompt("Enter API key for Ollama Librarian");
  if (typeof entered === "string" && entered.trim()) {
    apiKey = entered.trim();
    localStorage.setItem(API_KEY_STORAGE_KEY, apiKey);
  }
}

const nativeFetch = window.fetch.bind(window);
window.fetch = (input, init = undefined) => {
  const reqInit = init ? Object.assign({}, init) : {};
  const inheritedHeaders =
    !reqInit.headers &&
    typeof Request !== "undefined" &&
    input instanceof Request
      ? input.headers
      : undefined;
  const headers = new Headers(reqInit.headers || inheritedHeaders || {});
  if (apiKey) {
    headers.set("X-API-Key", apiKey);
  }
  reqInit.headers = headers;
  return nativeFetch(input, reqInit);
};

const modelEl = document.getElementById("model");
const promptEl = document.getElementById("prompt");
const sendEl = document.getElementById("send");
const cancelEl = document.getElementById("cancel");
const refreshEl = document.getElementById("refresh");
const clearEl = document.getElementById("clear");
const openLibraryDocsEl = document.getElementById("openLibraryDocs");
const openStashEl = document.getElementById("openStash");
const openBibliographyEl = document.getElementById("openBibliography");
const instructionsEl = document.getElementById("instructions");
const saveInstructionsEl = document.getElementById("saveInstructions");
const abstractNeedEl = document.getElementById("abstractNeed");
const abstractTextEl = document.getElementById("abstractText");
const evaluateAbstractEl = document.getElementById("evaluateAbstract");
const clearAbstractEl = document.getElementById("clearAbstract");
const abstractResultEl = document.getElementById("abstractResult");
const usePdfLibraryEl = document.getElementById("usePdfLibrary");
const deepStudyEl = document.getElementById("deepStudy");
const syncPdfLibraryEl = document.getElementById("syncPdfLibrary");
const uploadLibraryDocsEl = document.getElementById("uploadLibraryDocs");
const pdfProgressEl = document.getElementById("pdfProgress");
const pdfProgressBarEl = document.getElementById("pdfProgressBar");
const appVersionEl = document.getElementById("appVersion");
const updateStatusEl = document.getElementById("updateStatus");
const updateNotesLinkEl = document.getElementById("updateNotesLink");
const checkUpdatesEl = document.getElementById("checkUpdates");
const applyUpdateEl = document.getElementById("applyUpdate");
const studyBriefEl = document.getElementById("studyBrief");
const makeBibliographyEl = document.getElementById("makeBibliography");
const promptHistorySelectEl = document.getElementById("promptHistorySelect");
const promptUseSelectedEl = document.getElementById("promptUseSelected");
const promptPinSelectedEl = document.getElementById("promptPinSelected");
const promptClearHistoryEl = document.getElementById("promptClearHistory");
const pdfStatusEl = document.getElementById("pdfStatus");
const messagesEl = document.getElementById("messages");
const statusDotEl = document.getElementById("statusDot");
const statusTextEl = document.getElementById("statusText");
const metaEl = document.getElementById("meta");
const stashModalEl = document.getElementById("stashModal");
const stashListEl = document.getElementById("stashList");
const stashMetaEl = document.getElementById("stashMeta");
const stashTitleEl = document.getElementById("stashTitle");
const stashReloadEl = document.getElementById("stashReload");
const stashClearAllEl = document.getElementById("stashClearAll");
const stashCloseEl = document.getElementById("stashClose");
const docsModalEl = document.getElementById("docsModal");
const docsListEl = document.getElementById("docsList");
const docsMetaEl = document.getElementById("docsMeta");
const docsGroupsEl = document.getElementById("docsGroups");
const docsReloadEl = document.getElementById("docsReload");
const docsSelectAllEl = document.getElementById("docsSelectAll");
const docsSelectNoneEl = document.getElementById("docsSelectNone");
const docsCloseEl = document.getElementById("docsClose");
const docsSearchEl = document.getElementById("docsSearch");
let lastUserPrompt = "";
let libraryDocs = [];
let libraryGroups = [];
let excludedDocPaths = new Set();
let activeRequestController = null;
let pendingPromptText = "";
let stashViewMode = "stash";
let lastPdfSources = [];
let lastCitationQuery = "";
let promptHistory = [];
let promptHistoryIndex = -1;
let pinnedPrompts = [];
let syncSnapshot = null;

const DOC_FILTER_STORAGE_KEY = "ollama_web_excluded_docs_v1";
const PROMPT_HISTORY_STORAGE_KEY = "ollama_web_prompt_history_v1";
const PINNED_PROMPTS_STORAGE_KEY = "ollama_web_pinned_prompts_v1";
const MAX_PROMPT_HISTORY = 150;
const MAX_UPLOAD_BYTES = Number(
  readMetaContent("ollama-max-upload-bytes", "536870912"),
);
const SUPPORTED_UPLOAD_EXTENSIONS = new Set([
  ".pdf",
  ".txt",
  ".md",
  ".html",
  ".htm",
  ".epub",
]);
let latestUpdateVersion = "";

function extensionOfName(name) {
  const raw = String(name || "")
    .trim()
    .toLowerCase();
  const idx = raw.lastIndexOf(".");
  if (idx < 0) return "";
  return raw.slice(idx);
}

async function uploadLibraryFiles(fileList) {
  const allFiles = Array.from(fileList || []);
  if (!allFiles.length) return;

  const files = allFiles.filter((f) =>
    SUPPORTED_UPLOAD_EXTENSIONS.has(extensionOfName(f && f.name)),
  );
  if (!files.length) {
    metaEl.textContent =
      "No supported files selected (.pdf, .txt, .md, .html, .htm, .epub)";
    return;
  }

  const tooLarge = files.filter((f) => Number(f && f.size) > MAX_UPLOAD_BYTES);
  if (tooLarge.length) {
    const limitMb = Math.round(MAX_UPLOAD_BYTES / (1024 * 1024));
    const sample = tooLarge
      .slice(0, 2)
      .map((f) => String(f.name || ""))
      .join(" | ");
    metaEl.textContent = `Upload blocked: ${tooLarge.length} file(s) exceed ${limitMb} MB. ${sample}`;
    return;
  }

  uploadLibraryDocsEl.disabled = true;
  const originalText = uploadLibraryDocsEl.textContent;
  uploadLibraryDocsEl.textContent = "Uploading...";

  let uploaded = 0;
  let failed = 0;
  const failures = [];

  try {
    for (let i = 0; i < files.length; i += 1) {
      const file = files[i];
      metaEl.textContent = `Uploading ${i + 1}/${files.length}: ${file.name}`;
      const url = `/api/library/upload?name=${encodeURIComponent(file.name)}`;
      const res = await fetch(url, {
        method: "POST",
        headers: { "Content-Type": "application/octet-stream" },
        body: file,
      });
      let data = {};
      try {
        data = await res.json();
      } catch (_) {
        data = {};
      }
      if (!res.ok || data.ok === false) {
        failed += 1;
        failures.push(`${file.name}: ${data.error || `HTTP ${res.status}`}`);
        continue;
      }
      uploaded += 1;
    }

    if (uploaded > 0) {
      try {
        await fetch("/api/pdf/index", { method: "POST" });
      } catch (_) {
        // Upload succeeded even if index trigger fails.
      }
      refreshPdfStatus();
      if (!docsModalEl.classList.contains("docs-hidden")) {
        try {
          await loadLibraryDocs();
        } catch (_) {
          // Keep upload success message if docs refresh fails.
        }
      }
    }

    if (failed > 0) {
      const sample = failures.slice(0, 2).join(" | ");
      metaEl.textContent = `Uploaded ${uploaded}, failed ${failed}. ${sample}`;
    } else {
      metaEl.textContent = `Uploaded ${uploaded} file${uploaded === 1 ? "" : "s"}; indexing started`;
    }
  } finally {
    uploadLibraryDocsEl.disabled = false;
    uploadLibraryDocsEl.textContent = originalText;
  }
}

function pickLibraryFilesAndUpload() {
  const picker = document.createElement("input");
  picker.type = "file";
  picker.accept = ".pdf,.txt,.md,.html,.htm,.epub";
  picker.multiple = true;
  picker.style.display = "none";
  document.body.appendChild(picker);
  picker.addEventListener(
    "change",
    async () => {
      try {
        await uploadLibraryFiles(picker.files);
      } finally {
        picker.remove();
      }
    },
    { once: true },
  );
  picker.click();
}

function loadPromptHistory() {
  try {
    const raw = localStorage.getItem(PROMPT_HISTORY_STORAGE_KEY);
    if (!raw) return [];
    const arr = JSON.parse(raw);
    if (!Array.isArray(arr)) return [];
    return arr
      .filter((x) => typeof x === "string")
      .map((x) => x.trim())
      .filter(Boolean)
      .slice(-MAX_PROMPT_HISTORY);
  } catch (_) {
    return [];
  }
}

function loadPinnedPrompts() {
  try {
    const raw = localStorage.getItem(PINNED_PROMPTS_STORAGE_KEY);
    if (!raw) return [];
    const arr = JSON.parse(raw);
    if (!Array.isArray(arr)) return [];
    return arr
      .filter((x) => typeof x === "string")
      .map((x) => x.trim())
      .filter(Boolean)
      .slice(-MAX_PROMPT_HISTORY);
  } catch (_) {
    return [];
  }
}

function persistPromptHistory() {
  try {
    localStorage.setItem(
      PROMPT_HISTORY_STORAGE_KEY,
      JSON.stringify(promptHistory.slice(-MAX_PROMPT_HISTORY)),
    );
  } catch (_) {
    // Ignore storage errors.
  }
}

function persistPinnedPrompts() {
  try {
    localStorage.setItem(
      PINNED_PROMPTS_STORAGE_KEY,
      JSON.stringify(pinnedPrompts.slice(-MAX_PROMPT_HISTORY)),
    );
  } catch (_) {
    // Ignore storage errors.
  }
}

function collectPromptRows() {
  const out = [];
  const seen = new Set();

  for (let i = pinnedPrompts.length - 1; i >= 0; i -= 1) {
    const text = pinnedPrompts[i];
    if (!text || seen.has(text)) continue;
    seen.add(text);
    out.push({ text, pinned: true });
  }

  for (let i = promptHistory.length - 1; i >= 0; i -= 1) {
    const text = promptHistory[i];
    if (!text || seen.has(text)) continue;
    seen.add(text);
    out.push({ text, pinned: false });
  }
  return out;
}

function renderPromptHistoryDropdown(selectText = "") {
  if (!promptHistorySelectEl) return;
  const selected = String(selectText || promptHistorySelectEl.value || "");
  const rows = collectPromptRows();

  promptHistorySelectEl.innerHTML = "";
  const placeholder = document.createElement("option");
  placeholder.value = "";
  placeholder.textContent = rows.length
    ? "Previous prompts..."
    : "No previous prompts";
  promptHistorySelectEl.appendChild(placeholder);

  for (const row of rows) {
    const opt = document.createElement("option");
    opt.value = row.text;
    const shortText =
      row.text.length > 170 ? `${row.text.slice(0, 170)}...` : row.text;
    opt.textContent = row.pinned ? `[PIN] ${shortText}` : shortText;
    promptHistorySelectEl.appendChild(opt);
  }

  if (selected) {
    promptHistorySelectEl.value = selected;
  }
}

function rememberPrompt(text, persist = true) {
  const value = String(text || "").trim();
  if (!value) return;
  const existingIdx = promptHistory.lastIndexOf(value);
  if (existingIdx >= 0) {
    promptHistory.splice(existingIdx, 1);
  }
  promptHistory.push(value);
  if (promptHistory.length > MAX_PROMPT_HISTORY) {
    promptHistory = promptHistory.slice(-MAX_PROMPT_HISTORY);
  }
  promptHistoryIndex = promptHistory.length;
  if (persist) {
    persistPromptHistory();
  }
  renderPromptHistoryDropdown(value);
}

function recallPromptHistory(direction) {
  if (!promptHistory.length) {
    metaEl.textContent = "No saved prompts yet";
    return;
  }

  if (direction < 0) {
    promptHistoryIndex = Math.max(0, promptHistoryIndex - 1);
  } else {
    promptHistoryIndex = Math.min(promptHistory.length, promptHistoryIndex + 1);
  }

  if (promptHistoryIndex >= promptHistory.length) {
    promptEl.value = "";
    metaEl.textContent = "Prompt history: newest";
    return;
  }

  promptEl.value = promptHistory[promptHistoryIndex] || "";
  promptEl.focus();
  promptEl.setSelectionRange(promptEl.value.length, promptEl.value.length);
  metaEl.textContent = `Prompt history ${promptHistoryIndex + 1}/${promptHistory.length}`;
  renderPromptHistoryDropdown(promptEl.value);
}

function usePromptFromDropdown() {
  const selected = String(promptHistorySelectEl.value || "").trim();
  if (!selected) {
    metaEl.textContent = "Select a prompt from the list first";
    return "";
  }
  promptEl.value = selected;
  promptEl.focus();
  promptEl.setSelectionRange(promptEl.value.length, promptEl.value.length);
  return selected;
}

function togglePinSelectedPrompt() {
  const selected = String(promptHistorySelectEl.value || "").trim();
  if (!selected) {
    metaEl.textContent = "Select a prompt to pin or unpin";
    return;
  }
  const idx = pinnedPrompts.lastIndexOf(selected);
  if (idx >= 0) {
    pinnedPrompts.splice(idx, 1);
    persistPinnedPrompts();
    renderPromptHistoryDropdown(selected);
    metaEl.textContent = "Prompt unpinned";
    return;
  }
  pinnedPrompts.push(selected);
  if (pinnedPrompts.length > MAX_PROMPT_HISTORY) {
    pinnedPrompts = pinnedPrompts.slice(-MAX_PROMPT_HISTORY);
  }
  persistPinnedPrompts();
  renderPromptHistoryDropdown(selected);
  metaEl.textContent = "Prompt pinned";
}

function clearPromptHistory() {
  const keepPinned = new Set(pinnedPrompts);
  const before = promptHistory.length;
  promptHistory = promptHistory.filter((p) => keepPinned.has(p));
  promptHistoryIndex = promptHistory.length;
  persistPromptHistory();
  renderPromptHistoryDropdown();
  metaEl.textContent = `Cleared ${Math.max(0, before - promptHistory.length)} unpinned prompts`;
}

async function askSelectedPrompt() {
  if (activeRequestController) return;
  const selected = usePromptFromDropdown();
  if (!selected) return;
  await sendPrompt();
}

function setStatus(state, text) {
  statusDotEl.classList.remove("ok", "err");
  if (state === "ok") statusDotEl.classList.add("ok");
  if (state === "err") statusDotEl.classList.add("err");
  statusTextEl.textContent = text;
}

function formatAbstractEvalResult(data) {
  const score = Number(data && data.confidence ? data.confidence : 0);
  const confLabel = String(
    data && data.confidence_label ? data.confidence_label : "Unknown",
  );
  const recLabel = String(
    data && data.recommendation_label
      ? data.recommendation_label
      : "Maybe / needs manual review",
  );
  const reasons = Array.isArray(data && data.reasons) ? data.reasons : [];
  const signals = Array.isArray(data && data.signals) ? data.signals : [];
  const concerns = Array.isArray(data && data.concerns) ? data.concerns : [];

  const lines = [
    `Confidence: ${score}% (${confLabel})`,
    `Recommendation: ${recLabel}`,
  ];

  if (reasons.length) {
    lines.push("Why:");
    for (const item of reasons) lines.push(`- ${String(item)}`);
  }
  if (signals.length) {
    lines.push("Positive signals:");
    for (const item of signals) lines.push(`- ${String(item)}`);
  }
  if (concerns.length) {
    lines.push("Concerns:");
    for (const item of concerns) lines.push(`- ${String(item)}`);
  }

  return lines.join("\\n");
}

async function evaluateAbstract() {
  const researchNeed = String(abstractNeedEl.value || "").trim();
  const abstractText = String(abstractTextEl.value || "").trim();
  const model = String(modelEl.value || "").trim();
  const instructions = String(instructionsEl.value || "").trim();

  if (!researchNeed) {
    abstractResultEl.textContent = "Add your research need first.";
    abstractNeedEl.focus();
    return;
  }
  if (!abstractText) {
    abstractResultEl.textContent = "Paste an abstract to evaluate.";
    abstractTextEl.focus();
    return;
  }
  if (!model) {
    abstractResultEl.textContent =
      "No model available. Install a model, then refresh.";
    return;
  }

  evaluateAbstractEl.disabled = true;
  clearAbstractEl.disabled = true;
  abstractResultEl.textContent = "Evaluating abstract...";
  metaEl.textContent = `Abstract screener: ${model}`;

  try {
    const res = await fetch("/api/abstract/evaluate", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        model,
        research_need: researchNeed,
        abstract: abstractText,
        instructions: instructions || undefined,
      }),
    });
    let data = {};
    try {
      data = await res.json();
    } catch (_) {
      data = {};
    }
    if (!res.ok || data.ok === false) {
      throw new Error(data.error || `HTTP ${res.status}`);
    }

    abstractResultEl.textContent = formatAbstractEvalResult(data);
    metaEl.textContent = `Abstract screener: ${model} | ${data.confidence}% confidence`;
  } catch (err) {
    abstractResultEl.textContent = `Evaluation failed: ${err.message}`;
    metaEl.textContent = "Abstract screener failed";
  } finally {
    evaluateAbstractEl.disabled = false;
    clearAbstractEl.disabled = false;
  }
}

function clearAbstractInputs() {
  abstractNeedEl.value = "";
  abstractTextEl.value = "";
  abstractResultEl.textContent = "No evaluation yet.";
  abstractNeedEl.focus();
}

function isoNow() {
  return new Date().toISOString();
}

async function persistMessage(role, text, ts) {
  await fetch("/api/history", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ role, text, ts }),
  });
}

function escapeHtml(text) {
  return text
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

function sourceLinkFromDescriptor(rawDescriptor) {
  const raw = String(rawDescriptor || "").trim();
  if (!raw) return null;

  const buildDocHref = (path, loc) => {
    const cleanPath = String(path || "").trim();
    if (!cleanPath) return null;
    const sectionOrPage = Math.max(1, Number(loc || 1));
    if (/\\.epub$/i.test(cleanPath)) {
      return `/epub-reader?path=${strictEncodeURIComponent(cleanPath)}&section=${sectionOrPage}`;
    }
    if (/\\.pdf$/i.test(cleanPath)) {
      return `/api/pdf/file?path=${strictEncodeURIComponent(cleanPath)}#page=${sectionOrPage}`;
    }
    return null;
  };

  const urlMatch = raw.match(
    /(?:https?:\/\/|\/api\/pdf\/file\?|\/epub-reader\?)[^\s;,)\]]+/i,
  );
  if (urlMatch) {
    return { href: urlMatch[0], title: raw, label: "source" };
  }

  const indexed = raw.match(
    /source\\s+path\\s*(\\d+)(?:\\s*,?\\s*(?:location|page)\\s*(\\d+))?/i,
  );
  if (indexed) {
    const idx = Math.max(1, Number(indexed[1] || 1)) - 1;
    const loc = Number(indexed[2] || 1);
    const src = Array.isArray(lastPdfSources) ? lastPdfSources[idx] : null;
    const path = src && src.path ? String(src.path) : "";
    if (path) {
      const page =
        Number.isFinite(loc) && loc > 0
          ? loc
          : Number(src.page || src.location || 1);
      const href = buildDocHref(path, Math.max(1, Number(page || 1)));
      if (!href) return null;
      return { href, title: raw, label: "source" };
    }
  }

  const explicitSource = raw.match(/source\\s*=\\s*(.+?\\.(?:pdf|epub))\\b/i);
  if (explicitSource) {
    const path = String(explicitSource[1] || "").trim();
    const locMatch = raw.match(/(?:location|page)\\s*=\\s*(\\d+)/i);
    const loc = Number(locMatch && locMatch[1] ? locMatch[1] : 1);
    if (path) {
      const href = buildDocHref(path, Math.max(1, loc));
      if (!href) return null;
      return { href, title: raw, label: "source" };
    }
  }

  const pathMatch = raw.match(/(?:\/[\w .\-()&%+]+)+\.(?:pdf|epub)\b/i);
  if (pathMatch) {
    const path = pathMatch[0];
    const pageMatch = raw.match(/(?:page|location|p\\.)\\s*(\\d+)/i);
    const page = Number(pageMatch && pageMatch[1] ? pageMatch[1] : 1);
    const href = buildDocHref(path, Math.max(1, page));
    if (!href) return null;
    return { href, title: raw, label: "source" };
  }

  return null;
}

function protectMathSegments(text) {
  const segments = [];
  let out = String(text || "");
  out = out.replace(
    /\$\$[\s\S]*?\$\$|\\\[[\s\S]*?\\\]|\\\([\s\S]*?\\\)|\$[^$\\n]+\$/g,
    (m) => {
      const token = `@@MATHSEG_${segments.length}@@`;
      segments.push(m);
      return token;
    },
  );
  return { out, segments };
}

function renderInlineMarkdown(text) {
  const protectedMath = protectMathSegments(text);
  let out = protectedMath.out;
  out = out.replace(/`([^`]+)`/g, "<code>$1</code>");
  out = out.replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>");
  out = out.replace(/\*([^*]+)\*/g, "<em>$1</em>");
  out = out.replace(
    /\[([^\]]+)\]\(((?:https?:\/\/|\/api\/pdf\/file\?|\/epub-reader\?)[^\s]+)\)/g,
    '<a href="$2" target="_blank" rel="noopener noreferrer">$1</a>',
  );
  out = out.replace(
    /\[([^\]]*(?:source\s+path|source\s*=)[^\]]*)\]/gi,
    (_, inner) => {
      const raw = String(inner || "").trim();
      if (!raw) return "";
      const descriptorMatches = Array.from(
        raw.matchAll(
          /source\s+path\s*\d+(?:\s*,?\s*(?:location|page)\s*\d+)?|source\s*=\s*.+?\.(?:pdf|epub)(?:\s+(?:location|page)\s*=\s*\d+)?/gi,
        ),
      );
      const descriptors = descriptorMatches.length
        ? descriptorMatches
            .map((m) => String(m[0] || "").trim())
            .filter(Boolean)
        : raw
            .split(/\s*;\s*/)
            .map((x) => String(x || "").trim())
            .filter(Boolean);

      const links = [];
      for (const descriptor of descriptors) {
        const title = descriptor.replace(/"/g, "&quot;");
        const link = sourceLinkFromDescriptor(descriptor);
        if (link && link.href) {
          links.push(
            `<a class="source-inline" href="${link.href}" target="_blank" rel="noopener noreferrer" title="${title}">source</a>`,
          );
        } else {
          links.push(
            `<span class="source-inline" title="${title}">source</span>`,
          );
        }
      }
      return links.length ? ` ${links.join(" ")}` : "";
    },
  );
  out = out.replace(
    /\bsource\s+path\s*\d+(?:\s*,\s*(?:location|page)\s*\d+)?\b/gi,
    (match) => {
      const link = sourceLinkFromDescriptor(match);
      const title = String(match).replace(/"/g, "&quot;");
      if (link && link.href) {
        return `<a class="source-inline" href="${link.href}" target="_blank" rel="noopener noreferrer" title="${title}">source</a>`;
      }
      return `<span class="source-inline" title="${title}">source</span>`;
    },
  );
  out = out.replace(
    /\bsource\s*=\s*.+?\.(?:pdf|epub)(?:\s+(?:location|page)\s*=\s*\d+)?/gi,
    (match) => {
      const link = sourceLinkFromDescriptor(match);
      const title = String(match).replace(/"/g, "&quot;");
      if (link && link.href) {
        return `<a class="source-inline" href="${link.href}" target="_blank" rel="noopener noreferrer" title="${title}">source</a>`;
      }
      return `<span class="source-inline" title="${title}">source</span>`;
    },
  );
  out = out.replace(
    /@@MATHSEG_(\d+)@@/g,
    (_, idx) => protectedMath.segments[Number(idx)] || "",
  );
  return out;
}

function renderBracketSourceLinks(text) {
  const matches = Array.from(String(text || "").matchAll(/\[([^\]]+)\]/g));
  if (!matches.length) {
    return "";
  }

  const links = [];
  for (const match of matches) {
    const raw = String(match[1] || "").trim();
    if (!raw) {
      continue;
    }
    const title = raw.replace(/"/g, "&quot;");
    const link = sourceLinkFromDescriptor(raw);
    if (link && link.href) {
      links.push(
        `<a class="source-link" href="${link.href}" target="_blank" rel="noopener noreferrer" title="${title}">Source</a>`,
      );
    } else {
      links.push(
        `<span class="source-link-static" title="${title}">Source</span>`,
      );
    }
  }
  return links.join(" ");
}

function sanitizeNotesUrl(url) {
  const raw = String(url || "").trim();
  if (!raw) {
    return "";
  }
  try {
    const parsed = new URL(raw, window.location.origin);
    if (
      (parsed.protocol === "http:" || parsed.protocol === "https:") &&
      parsed.hostname
    ) {
      return parsed.href;
    }
  } catch (_) {
    return "";
  }
  return "";
}

function normalizeMathDelimiters(text) {
  // LLM output often mixes single and double-escaped delimiters (e.g. \\( ... \\)).
  // Normalize them so KaTeX can consistently detect inline/display math boundaries.
  const bs = String.fromCharCode(92);
  let out = text
    .split(bs + bs + "(")
    .join(bs + "(")
    .split(bs + bs + ")")
    .join(bs + ")")
    .split(bs + bs + "[")
    .join(bs + "[")
    .split(bs + bs + "]")
    .join(bs + "]");

  // Downgrade obvious prose accidentally wrapped as \( ... \) back to plain parentheses.
  // Example: \(the perpendicular distance between these sides\) should not be math.
  const open = bs + "(";
  const close = bs + ")";
  const rebuilt = [];
  let i = 0;

  while (i < out.length) {
    const start = out.indexOf(open, i);
    if (start === -1) {
      rebuilt.push(out.slice(i));
      break;
    }

    const end = out.indexOf(close, start + open.length);
    if (end === -1) {
      rebuilt.push(out.slice(i));
      break;
    }

    rebuilt.push(out.slice(i, start));
    const inner = out.slice(start + open.length, end);
    const content = inner.trim();
    if (!content) {
      rebuilt.push(open + inner + close);
      i = end + close.length;
      continue;
    }

    const hasLetters = /[A-Za-z]/.test(content);
    const hasSpaces = /\s/.test(content);
    const hasMathSignal = /[0-9=+\-*/^_<>]|\\[A-Za-z]+|[{}\[\]]/.test(content);
    const isLikelyProse = hasLetters && hasSpaces && !hasMathSignal;
    rebuilt.push(isLikelyProse ? "(" + inner + ")" : open + inner + close);
    i = end + close.length;
  }

  out = rebuilt.join("");

  return out;
}

function renderMathIn(element) {
  if (!element || typeof window.renderMathInElement !== "function") {
    return;
  }
  try {
    const bs = String.fromCharCode(92);
    window.renderMathInElement(element, {
      delimiters: [
        { left: "$$", right: "$$", display: true },
        { left: bs + "[", right: bs + "]", display: true },
        { left: "$", right: "$", display: false },
        { left: bs + "(", right: bs + ")", display: false },
      ],
      throwOnError: false,
    });
  } catch (_) {
    // Leave original text untouched if math rendering fails.
  }
}

function renderMarkdown(text) {
  const normalized = normalizeMathDelimiters(text);
  const escaped = escapeHtml(normalized);

  // Preserve fenced code blocks before other transformations.
  const codeBlocks = [];
  let withPlaceholders = escaped.replace(/```([\s\S]*?)```/g, (_, code) => {
    const token = `@@CODEBLOCK_${codeBlocks.length}@@`;
    codeBlocks.push(`<pre><code>${code.trim()}</code></pre>`);
    return token;
  });

  // Preserve multi-line block math so markdown line splitting does not break delimiters.
  const mathBlocks = [];
  withPlaceholders = withPlaceholders.replace(
    /\$\$([\s\S]*?)\$\$/g,
    (_, expr) => {
      const token = `@@MATHBLOCK_${mathBlocks.length}@@`;
      mathBlocks.push(`<div class="math-block">$$${expr.trim()}$$</div>`);
      return token;
    },
  );

  const lines = withPlaceholders.split("\\n");
  const html = [];
  let inUl = false;
  let inOl = false;

  const closeLists = () => {
    if (inUl) {
      html.push("</ul>");
      inUl = false;
    }
    if (inOl) {
      html.push("</ol>");
      inOl = false;
    }
  };

  for (let i = 0; i < lines.length; i += 1) {
    const raw = lines[i];
    const line = raw.trimEnd();
    const t = line.trim();

    if (!t) {
      let nextNonEmpty = "";
      for (let j = i + 1; j < lines.length; j += 1) {
        const candidate = lines[j].trim();
        if (candidate) {
          nextNonEmpty = candidate;
          break;
        }
      }
      const nextKeepsUl = inUl && /^[-*]\s+/.test(nextNonEmpty);
      const nextKeepsOl = inOl && /^\d+\.\s+/.test(nextNonEmpty);
      if (!nextKeepsUl && !nextKeepsOl) {
        closeLists();
      }
      continue;
    }

    if (/^\[[^\]]+\](?:\s*[,;]?\s*\[[^\]]+\])*$/.test(t)) {
      closeLists();
      const links = renderBracketSourceLinks(t);
      if (links) {
        html.push(`<p class="source-line">${links}</p>`);
        continue;
      }
    }

    const sourcesLine = t.match(/^sources?:\s*(.+)$/i);
    if (sourcesLine) {
      closeLists();
      const parts = sourcesLine[1].split(/\s*;\s*/).filter(Boolean);
      const links = [];
      for (const part of parts) {
        const link = sourceLinkFromDescriptor(part);
        const title = String(part || "")
          .trim()
          .replace(/"/g, "&quot;");
        if (link && link.href) {
          links.push(
            `<a class="source-link" href="${link.href}" target="_blank" rel="noopener noreferrer" title="${title}">Source</a>`,
          );
        } else if (title) {
          links.push(
            `<span class="source-link-static" title="${title}">Source</span>`,
          );
        }
      }
      if (links.length) {
        html.push(`<p class="source-line">${links.join(" ")}</p>`);
        continue;
      }
    }

    if (/\.(?:pdf|epub)\b/i.test(t) && !/\[[^\]]+\]\([^\)]+\)/.test(t)) {
      closeLists();
      const link = sourceLinkFromDescriptor(t);
      if (link && link.href) {
        const title = t.replace(/"/g, "&quot;");
        html.push(
          `<p class="source-line"><a class="source-link" href="${link.href}" target="_blank" rel="noopener noreferrer" title="${title}">Source</a></p>`,
        );
        continue;
      }
    }

    const headingMatch = t.match(/^(#{1,6})\s+(.*)$/);
    if (headingMatch) {
      closeLists();
      const level = headingMatch[1].length;
      const content = headingMatch[2];
      html.push(`<h${level}>${renderInlineMarkdown(content)}</h${level}>`);
      continue;
    }

    if (/^[-*]\s+/.test(t)) {
      if (!inUl) {
        closeLists();
        html.push("<ul>");
        inUl = true;
      }
      html.push(`<li>${renderInlineMarkdown(t.replace(/^[-*]\s+/, ""))}</li>`);
      continue;
    }

    if (/^\d+\.\s+/.test(t)) {
      if (!inOl) {
        closeLists();
        html.push("<ol>");
        inOl = true;
      }
      html.push(`<li>${renderInlineMarkdown(t.replace(/^\d+\.\s+/, ""))}</li>`);
      continue;
    }

    closeLists();
    html.push(`<p>${renderInlineMarkdown(t)}</p>`);
  }

  closeLists();
  let joined = html.join("");
  joined = joined.replace(
    /@@CODEBLOCK_(\d+)@@/g,
    (_, idx) => codeBlocks[Number(idx)] || "",
  );
  joined = joined.replace(
    /@@MATHBLOCK_(\d+)@@/g,
    (_, idx) => mathBlocks[Number(idx)] || "",
  );
  return joined;
}

async function loadInstructions() {
  try {
    const res = await fetch("/api/instructions");
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();
    instructionsEl.value =
      typeof data.instructions === "string" ? data.instructions : "";
  } catch (err) {
    addMessage("system", `Failed to load instructions: ${err.message}`);
  }
}

async function saveInstructions() {
  const instructions = instructionsEl.value.trim();
  try {
    const res = await fetch("/api/instructions", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ instructions }),
    });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    metaEl.textContent = instructions
      ? "Instructions saved"
      : "Instructions cleared";
  } catch (err) {
    addMessage("system", `Failed to save instructions: ${err.message}`);
  }
}

function addMessage(role, text, opts = {}) {
  const showAssistantTools = opts.showAssistantTools !== false;
  const el = document.createElement("div");
  el.className = `msg ${role}`;

  const citationOnly = role === "assistant" && opts.citationOnly === true;
  if (!citationOnly) {
    const textEl = document.createElement("div");
    textEl.className = role === "assistant" ? "msg-text md" : "msg-text";
    if (role === "assistant") {
      textEl.innerHTML = renderMarkdown(text);
      renderMathIn(textEl);
    } else {
      textEl.textContent = text;
    }
    el.appendChild(textEl);
  }

  if (
    role === "assistant" &&
    Array.isArray(opts.citationEntries) &&
    opts.citationEntries.length
  ) {
    const citationWrap = renderCitationActions(
      opts.citationEntries,
      opts.citationQuery || "",
    );
    if (citationWrap) {
      el.appendChild(citationWrap);
    }
  }

  if (role === "assistant" && showAssistantTools) {
    const tools = document.createElement("div");
    tools.className = "msg-tools";

    const stashBtn = document.createElement("button");
    stashBtn.className = "stash-btn";
    stashBtn.type = "button";
    stashBtn.textContent = "Stash";
    stashBtn.addEventListener("click", async () => {
      stashBtn.disabled = true;
      stashBtn.textContent = "Saving...";
      try {
        const result = await stashResponse(text);
        metaEl.textContent = `Stashed response (${result.count || "?"})`;
        stashBtn.textContent = "Stashed";
        setTimeout(() => {
          stashBtn.textContent = "Stash";
          stashBtn.disabled = false;
        }, 1200);
      } catch (err) {
        metaEl.textContent = `Stash failed: ${err.message}`;
        stashBtn.textContent = "Stash";
        stashBtn.disabled = false;
      }
    });

    const copyBtn = document.createElement("button");
    copyBtn.className = "copy-btn";
    copyBtn.type = "button";
    copyBtn.textContent = "Copy";
    copyBtn.addEventListener("click", async () => {
      const ok = await copyText(text);
      if (ok) {
        metaEl.textContent = "Copied response";
        copyBtn.textContent = "Copied";
        setTimeout(() => {
          copyBtn.textContent = "Copy";
        }, 1100);
      } else {
        metaEl.textContent = "Copy failed";
      }
    });

    tools.appendChild(stashBtn);
    tools.appendChild(copyBtn);
    el.appendChild(tools);
  }

  messagesEl.appendChild(el);
  messagesEl.scrollTop = messagesEl.scrollHeight;
}

async function copyText(text) {
  if (navigator.clipboard && window.isSecureContext) {
    try {
      await navigator.clipboard.writeText(text);
      return true;
    } catch (_) {
      // Fall through to legacy copy path.
    }
  }

  try {
    const ta = document.createElement("textarea");
    ta.value = text;
    ta.setAttribute("readonly", "");
    ta.style.position = "fixed";
    ta.style.top = "-1000px";
    ta.style.left = "-1000px";
    document.body.appendChild(ta);
    ta.focus();
    ta.select();
    const ok = document.execCommand("copy");
    document.body.removeChild(ta);
    return ok;
  } catch (_) {
    return false;
  }
}

async function addMessageAndStore(role, text) {
  const ts = isoNow();
  const opts = arguments.length > 2 ? arguments[2] : {};
  addMessage(role, text, opts);
  try {
    await persistMessage(role, text, ts);
  } catch (_) {
    // Keep UI responsive if history persistence fails.
  }
}

async function stashResponse(text, extra = {}) {
  const payload = {
    text,
    model: modelEl.value || "",
    use_pdf_library: !!usePdfLibraryEl.checked,
    ts: isoNow(),
    ...extra,
  };

  const res = await fetch("/api/stash", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });

  let data = {};
  try {
    data = await res.json();
  } catch (_) {
    data = {};
  }

  if (!res.ok) {
    const detail = data.error || `HTTP ${res.status}`;
    throw new Error(detail);
  }

  return data;
}

function persistDocFilterState() {
  try {
    localStorage.setItem(
      DOC_FILTER_STORAGE_KEY,
      JSON.stringify(Array.from(excludedDocPaths)),
    );
  } catch (_) {
    // Ignore storage errors.
  }
}

function loadDocFilterState() {
  try {
    const raw = localStorage.getItem(DOC_FILTER_STORAGE_KEY);
    if (!raw) return new Set();
    const arr = JSON.parse(raw);
    if (!Array.isArray(arr)) return new Set();
    return new Set(arr.filter((x) => typeof x === "string"));
  } catch (_) {
    return new Set();
  }
}

function getIncludedDocPaths() {
  return libraryDocs
    .filter((doc) => !excludedDocPaths.has(doc.path))
    .map((doc) => doc.path);
}

function hasIndexedChunks(doc) {
  return Number(doc && doc.chunks ? doc.chunks : 0) > 0;
}

function buildDocSelectionError(filters) {
  if (filters.includedCount <= 0) {
    return "All documents are excluded. Open Library Docs and include at least one document.";
  }
  if (filters.includedChunkCount <= 0) {
    const sample = filters.zeroChunkIncluded.slice(0, 3).join(", ");
    const suffix = filters.zeroChunkIncluded.length > 3 ? ", ..." : "";
    return `Selected document filter has no indexed text chunks (${sample}${suffix}). Include at least one document with chunks > 0 or OCR/re-index that PDF.`;
  }
  return "";
}

function buildDocFiltersForRequest() {
  const includedDocs = libraryDocs.filter(
    (doc) => !excludedDocPaths.has(doc.path),
  );
  const included = includedDocs.map((doc) => doc.path);
  const includedChunkCount = includedDocs.filter((doc) =>
    hasIndexedChunks(doc),
  ).length;
  const zeroChunkIncluded = includedDocs
    .filter((doc) => !hasIndexedChunks(doc))
    .map((doc) => doc.rel_path || pathBase(doc.path));
  return {
    includePaths: included,
    excludePaths: Array.from(excludedDocPaths),
    includedCount: included.length,
    includedChunkCount,
    zeroChunkIncluded,
  };
}

function setGroupIncluded(groupName, shouldInclude) {
  for (const doc of libraryDocs) {
    if ((doc.top_group || "(unknown)") !== groupName) continue;
    if (shouldInclude) {
      excludedDocPaths.delete(doc.path);
    } else {
      excludedDocPaths.add(doc.path);
    }
  }
  persistDocFilterState();
  renderLibraryDocs();
}

function pathParts(relPath) {
  const raw = String(relPath || "")
    .replace(/\\\\/g, "/")
    .replace(/^\/+/, "");
  if (!raw) return [];
  return raw.split("/").filter(Boolean);
}

function folderKeysForDoc(doc) {
  const parts = pathParts(doc.rel_path || doc.path || "");
  const dirs = parts.slice(0, Math.max(0, parts.length - 1));
  if (!dirs.length) {
    return { root: "(root)", child: "" };
  }
  const root = dirs[0];
  const child = dirs.length >= 2 ? `${dirs[0]}/${dirs[1]}` : "";
  return { root, child };
}

function setFolderIncluded(folderKey, depth, shouldInclude) {
  for (const doc of libraryDocs) {
    const { root, child } = folderKeysForDoc(doc);
    const matches = depth === 1 ? root === folderKey : child === folderKey;
    if (!matches) continue;
    if (shouldInclude) {
      excludedDocPaths.delete(doc.path);
    } else {
      excludedDocPaths.add(doc.path);
    }
  }
  persistDocFilterState();
  renderLibraryDocs();
}

function buildFolderHierarchy(docs) {
  const roots = new Map();
  for (const doc of docs) {
    const { root, child } = folderKeysForDoc(doc);
    if (!roots.has(root)) {
      roots.set(root, { key: root, docs: [], children: new Map() });
    }
    const rootNode = roots.get(root);
    rootNode.docs.push(doc);

    if (!child) continue;
    if (!rootNode.children.has(child)) {
      const childLabel = child.split("/").slice(-1)[0] || child;
      rootNode.children.set(child, { key: child, label: childLabel, docs: [] });
    }
    rootNode.children.get(child).docs.push(doc);
  }

  const rootList = Array.from(roots.values()).sort((a, b) =>
    a.key.localeCompare(b.key),
  );
  for (const node of rootList) {
    node.children = Array.from(node.children.values()).sort((a, b) =>
      a.label.localeCompare(b.label),
    );
  }
  return rootList;
}

function renderLibraryDocs() {
  const q = (docsSearchEl.value || "").trim().toLowerCase();
  const filtered = q
    ? libraryDocs.filter((doc) =>
        (doc.rel_path || doc.path || "").toLowerCase().includes(q),
      )
    : libraryDocs;

  const includedCount = Math.max(0, libraryDocs.length - excludedDocPaths.size);
  const hierarchy = buildFolderHierarchy(filtered);
  docsMetaEl.textContent =
    `Docs: ${libraryDocs.length} | Included: ${includedCount} | Excluded: ${excludedDocPaths.size}` +
    (hierarchy.length ? `\nFolders shown: ${hierarchy.length}` : "");

  docsGroupsEl.innerHTML = "";
  for (const rootNode of hierarchy) {
    const rootIncluded = rootNode.docs.filter(
      (d) => !excludedDocPaths.has(d.path),
    ).length;

    const row = document.createElement("div");
    row.className = "docs-group-row docs-group-root";

    const label = document.createElement("div");
    label.className = "docs-group-label";
    label.textContent = `${rootNode.key}: ${rootIncluded}/${rootNode.docs.length} included`;

    const actions = document.createElement("div");
    actions.className = "docs-group-actions";
    const inBtn = document.createElement("button");
    inBtn.type = "button";
    inBtn.className = "btn-soft";
    inBtn.textContent = "In";
    inBtn.addEventListener("click", () =>
      setFolderIncluded(rootNode.key, 1, true),
    );

    const outBtn = document.createElement("button");
    outBtn.type = "button";
    outBtn.className = "btn-soft";
    outBtn.textContent = "Out";
    outBtn.addEventListener("click", () =>
      setFolderIncluded(rootNode.key, 1, false),
    );

    actions.appendChild(inBtn);
    actions.appendChild(outBtn);
    row.appendChild(label);
    row.appendChild(actions);
    docsGroupsEl.appendChild(row);

    for (const childNode of rootNode.children) {
      const childIncluded = childNode.docs.filter(
        (d) => !excludedDocPaths.has(d.path),
      ).length;

      const childRow = document.createElement("div");
      childRow.className = "docs-group-row docs-group-child";

      const childLabel = document.createElement("div");
      childLabel.className = "docs-group-label";
      childLabel.textContent = `${childNode.label}: ${childIncluded}/${childNode.docs.length} included`;

      const childActions = document.createElement("div");
      childActions.className = "docs-group-actions";

      const childInBtn = document.createElement("button");
      childInBtn.type = "button";
      childInBtn.className = "btn-soft";
      childInBtn.textContent = "In";
      childInBtn.addEventListener("click", () =>
        setFolderIncluded(childNode.key, 2, true),
      );

      const childOutBtn = document.createElement("button");
      childOutBtn.type = "button";
      childOutBtn.className = "btn-soft";
      childOutBtn.textContent = "Out";
      childOutBtn.addEventListener("click", () =>
        setFolderIncluded(childNode.key, 2, false),
      );

      childActions.appendChild(childInBtn);
      childActions.appendChild(childOutBtn);
      childRow.appendChild(childLabel);
      childRow.appendChild(childActions);
      docsGroupsEl.appendChild(childRow);
    }
  }

  docsListEl.innerHTML = "";
  if (!filtered.length) {
    const empty = document.createElement("div");
    empty.className = "docs-item-meta";
    empty.textContent = "No matching documents.";
    docsListEl.appendChild(empty);
    return;
  }

  for (const doc of filtered) {
    const item = document.createElement("label");
    item.className = "docs-item";

    const box = document.createElement("input");
    const chunkCount = Number(doc.chunks || 0);
    const noChunks = chunkCount <= 0;
    box.type = "checkbox";
    box.checked = !excludedDocPaths.has(doc.path);
    box.addEventListener("change", () => {
      if (box.checked) {
        excludedDocPaths.delete(doc.path);
      } else {
        excludedDocPaths.add(doc.path);
      }
      persistDocFilterState();
      renderLibraryDocs();
    });

    const body = document.createElement("div");
    const pathLine = document.createElement("div");
    pathLine.className = "docs-item-path";
    pathLine.textContent = doc.rel_path || doc.path || "[unknown]";
    const metaLine = document.createElement("div");
    metaLine.className = "docs-item-meta";
    metaLine.textContent =
      `${doc.top_group || "(unknown)"} | pages=${doc.pages || 0} | chunks=${doc.chunks || 0}` +
      (noChunks ? " | no indexed text" : "");

    body.appendChild(pathLine);
    body.appendChild(metaLine);

    item.appendChild(box);
    item.appendChild(body);
    docsListEl.appendChild(item);
  }
}

async function loadLibraryDocs() {
  docsMetaEl.textContent = "Loading...";
  docsListEl.innerHTML = "";
  const res = await fetch("/api/library/docs");
  const data = await res.json();
  if (!res.ok) throw new Error(data.error || `HTTP ${res.status}`);

  libraryDocs = Array.isArray(data.documents) ? data.documents : [];
  libraryGroups = Array.isArray(data.groups) ? data.groups : [];

  const saved = loadDocFilterState();
  const validPaths = new Set(libraryDocs.map((d) => d.path));
  excludedDocPaths = new Set(
    Array.from(saved).filter((p) => validPaths.has(p)),
  );
  persistDocFilterState();

  renderLibraryDocs();
}

async function openLibraryDocsModal() {
  docsModalEl.classList.remove("docs-hidden");
  try {
    await loadLibraryDocs();
  } catch (err) {
    docsMetaEl.textContent = `Failed to load library docs: ${err.message}`;
  }
}

function closeLibraryDocsModal() {
  docsModalEl.classList.add("docs-hidden");
}

function formatStashTime(entry) {
  if (entry.saved_at_iso) return entry.saved_at_iso;
  if (entry.saved_at) {
    const d = new Date(Number(entry.saved_at) * 1000);
    return d.toISOString();
  }
  return "[unknown time]";
}

function renderStashEntries(payload) {
  const entries = Array.isArray(payload.entries) ? payload.entries : [];
  stashListEl.innerHTML = "";

  const shownType = payload.entry_type || "all";
  stashMetaEl.textContent = `Count: ${payload.count || 0}\nType: ${shownType}\nPath: ${payload.stash_path || ""}`;

  if (!entries.length) {
    const empty = document.createElement("div");
    empty.className = "stash-item-meta";
    empty.textContent = "No stashed snippets yet.";
    stashListEl.appendChild(empty);
    return;
  }

  for (const entry of entries) {
    const wrap = document.createElement("div");
    wrap.className = "stash-item";

    const top = document.createElement("div");
    top.className = "stash-item-meta";
    const entryType = entry.entry_type || "response";
    const model = entry.model || "unknown-model";
    top.textContent = `${formatStashTime(entry)} | ${entryType} | ${model}`;

    const rawText = typeof entry.text === "string" ? entry.text : "";
    const text = document.createElement("div");
    text.className = "stash-item-text md";
    text.innerHTML = renderMarkdown(rawText);
    renderMathIn(text);

    const actions = document.createElement("div");
    actions.className = "stash-item-actions";

    const copyBtn = document.createElement("button");
    copyBtn.className = "btn-soft";
    copyBtn.type = "button";
    copyBtn.textContent = "Copy";
    copyBtn.addEventListener("click", async () => {
      const ok = await copyText(rawText);
      metaEl.textContent = ok ? "Copied stashed snippet" : "Copy failed";
    });

    const delBtn = document.createElement("button");
    delBtn.className = "btn-soft";
    delBtn.type = "button";
    delBtn.textContent = "Delete";
    delBtn.addEventListener("click", async () => {
      if (!Number.isInteger(entry.stash_id)) return;
      delBtn.disabled = true;
      try {
        const res = await fetch(`/api/stash?id=${entry.stash_id}`, {
          method: "DELETE",
        });
        const data = await res.json();
        if (!res.ok) throw new Error(data.error || `HTTP ${res.status}`);
        await loadStashEntries();
        metaEl.textContent = "Deleted stash entry";
      } catch (err) {
        metaEl.textContent = `Delete failed: ${err.message}`;
        delBtn.disabled = false;
      }
    });

    actions.appendChild(copyBtn);
    actions.appendChild(delBtn);

    wrap.appendChild(top);
    wrap.appendChild(text);
    wrap.appendChild(actions);
    stashListEl.appendChild(wrap);
  }
}

async function loadStashEntries() {
  stashMetaEl.textContent = "Loading...";
  stashListEl.innerHTML = "";
  const endpoint =
    stashViewMode === "bibliography"
      ? "/api/bibliography?limit=200"
      : "/api/stash?limit=200";
  const res = await fetch(endpoint);
  const data = await res.json();
  if (!res.ok) throw new Error(data.error || `HTTP ${res.status}`);
  renderStashEntries(data);
}

async function openStashModal(mode = "stash") {
  stashViewMode = mode === "bibliography" ? "bibliography" : "stash";
  stashTitleEl.textContent =
    stashViewMode === "bibliography"
      ? "Bibliography Stash"
      : "Stashed Snippets";
  stashModalEl.classList.remove("stash-hidden");
  try {
    await loadStashEntries();
  } catch (err) {
    stashMetaEl.textContent = `Failed to load stash: ${err.message}`;
  }
}

function closeStashModal() {
  stashModalEl.classList.add("stash-hidden");
}

function pathBase(p) {
  if (!p) return "document";
  const parts = String(p).split("/");
  return parts[parts.length - 1] || "document";
}

function isPdfSourcePath(p) {
  return /\\.pdf$/i.test(String(p || "").trim());
}

function isEpubSourcePath(p) {
  return /\\.epub$/i.test(String(p || "").trim());
}

function buildSourceOpenUrl(path, loc) {
  const cleanPath = String(path || "").trim();
  const location = Math.max(1, Number(loc || 1));
  if (!cleanPath) return "";
  if (isPdfSourcePath(cleanPath)) {
    return `/api/pdf/file?path=${strictEncodeURIComponent(cleanPath)}#page=${location}`;
  }
  if (isEpubSourcePath(cleanPath)) {
    return `/epub-reader?path=${strictEncodeURIComponent(cleanPath)}&section=${location}`;
  }
  return "";
}

function sourceTitleFromPath(p) {
  const base = pathBase(p || "document");
  const noExt = base.replace(/\.[^/.]+$/, "");
  const normalized = noExt
    .replace(/[._-]+/g, " ")
    .replace(/\s+/g, " ")
    .trim();
  return normalized || "Untitled document";
}

function formatApaAuthorList(authors) {
  if (!Array.isArray(authors)) {
    return "";
  }
  const clean = authors
    .map((a) => String(a || "").trim())
    .filter((a) => a.length > 0)
    .slice(0, 6);
  if (!clean.length) {
    return "";
  }
  if (clean.length === 1) {
    return clean[0];
  }
  if (clean.length === 2) {
    return `${clean[0]} & ${clean[1]}`;
  }
  return `${clean.slice(0, clean.length - 1).join(", ")}, & ${clean[clean.length - 1]}`;
}

function strictEncodeURIComponent(value) {
  return encodeURIComponent(String(value)).replace(
    /[!'()*]/g,
    (ch) => `%${ch.charCodeAt(0).toString(16).toUpperCase()}`,
  );
}

function compactSourceLabel(p) {
  const base = pathBase(p);
  const maxLen = 56;
  if (base.length <= maxLen) return base;
  return `${base.slice(0, maxLen - 1)}...`;
}

function buildApaCitationEntries(sources) {
  const seen = new Set();
  const entries = [];
  for (const s of (Array.isArray(sources) ? sources : []).slice(0, 24)) {
    const path = String(s.path || "").trim();
    const loc = Number(s.page || s.location || 1);
    const key = `${path}#${loc}`;
    if (!path || seen.has(key)) continue;
    seen.add(key);

    const title = String(s.title || "").trim() || sourceTitleFromPath(path);
    const author = formatApaAuthorList(s.authors);
    const year = String(s.year || "").trim() || "n.d.";
    let titlePart = `*${title}*`;
    let locator = `loc. ${loc}`;
    const openUrl = buildSourceOpenUrl(path, loc);
    if (openUrl) {
      titlePart = `*[${title}](${openUrl})*`;
    }
    if (isPdfSourcePath(path)) {
      locator = `p. ${loc}`;
    } else if (isEpubSourcePath(path)) {
      locator = `section ${loc}`;
    }
    const citation = author
      ? `${author}. (${year}). ${titlePart}. (${locator}).`
      : `${titlePart}. (${year}). (${locator}).`;
    entries.push({
      citation,
      source: {
        path,
        page: loc,
        location: loc,
        title,
        authors: Array.isArray(s.authors) ? s.authors : [],
        year,
      },
    });
  }
  return entries;
}

function formatApaSources(sources) {
  return buildApaCitationEntries(sources).map((entry) => `- ${entry.citation}`);
}

function renderCitationActions(citationEntries, queryText = "") {
  const entries = Array.isArray(citationEntries) ? citationEntries : [];
  if (!entries.length) {
    return null;
  }

  const wrap = document.createElement("div");
  wrap.className = "citation-list";

  for (const entry of entries) {
    const row = document.createElement("div");
    row.className = "citation-row";

    const text = document.createElement("div");
    text.className = "citation-text md";
    text.innerHTML = renderInlineMarkdown(
      escapeHtml(String(entry.citation || "")),
    );

    const stashBtn = document.createElement("button");
    stashBtn.className = "stash-btn";
    stashBtn.type = "button";
    stashBtn.textContent = "Add to Bibliography";
    stashBtn.addEventListener("click", async () => {
      stashBtn.disabled = true;
      stashBtn.textContent = "Adding...";
      try {
        const payloadSources = entry.source ? [entry.source] : [];
        const result = await stashResponse(String(entry.citation || ""), {
          entry_type: "bibliography",
          query: queryText || lastCitationQuery || "",
          sources: payloadSources,
        });
        metaEl.textContent = `Added citation to bibliography (${result.count || "?"})`;
        stashBtn.textContent = "Added";
        setTimeout(() => {
          stashBtn.textContent = "Add to Bibliography";
          stashBtn.disabled = false;
        }, 1200);
      } catch (err) {
        metaEl.textContent = `Citation stash failed: ${err.message}`;
        stashBtn.textContent = "Add to Bibliography";
        stashBtn.disabled = false;
      }
    });

    row.appendChild(text);
    row.appendChild(stashBtn);
    wrap.appendChild(row);
  }

  return wrap;
}

function buildBibliographyText(sources, queryText = "") {
  const apaLines = formatApaSources(sources);
  if (!apaLines.length) {
    return "";
  }
  const heading = "References (APA 7):";
  const topic = queryText ? `\\nQuery: ${queryText}` : "";
  return `${heading}${topic}\\n\\n${apaLines.join("\\n")}`;
}

async function generateBibliographyFromLatestSources() {
  if (!Array.isArray(lastPdfSources) || !lastPdfSources.length) {
    addMessage(
      "system",
      "No recent PDF-grounded sources found. Ask with PDF-grounded mode first.",
    );
    return;
  }

  const citationEntries = buildApaCitationEntries(lastPdfSources);
  const bibliographyText = buildBibliographyText(
    lastPdfSources,
    lastCitationQuery,
  );
  if (!bibliographyText) {
    addMessage(
      "system",
      "Could not generate bibliography from current sources.",
    );
    return;
  }

  try {
    await addMessageAndStore("assistant", "", {
      citationOnly: true,
      citationEntries,
      citationQuery: lastCitationQuery,
    });
    await stashResponse(bibliographyText, {
      entry_type: "bibliography",
      query: lastCitationQuery,
      sources: Array.isArray(lastPdfSources) ? lastPdfSources : [],
    });
    metaEl.textContent = "Bibliography generated and opened";
    openStashModal("bibliography");
  } catch (err) {
    addMessage("system", `Bibliography generation failed: ${err.message}`);
  }
}

async function createStudyBrief() {
  const query = promptEl.value.trim() || lastUserPrompt;
  if (!query) {
    addMessage(
      "system",
      "Enter a topic first (or ask a question) to create a study brief.",
    );
    return;
  }
  if (!usePdfLibraryEl.checked) {
    addMessage(
      "system",
      "Enable PDF-grounded answers to create a study brief.",
    );
    return;
  }

  setBusy(true);
  metaEl.textContent = "Building study brief...";
  try {
    const model = modelEl.value;
    const filters = buildDocFiltersForRequest();
    if (libraryDocs.length) {
      const selectionError = buildDocSelectionError(filters);
      if (selectionError) {
        throw new Error(selectionError);
      }
    }
    const res = await fetch("/api/pdf/brief", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        query,
        model,
        top_k: deepStudyEl.checked ? 20 : 14,
        include_paths: filters.includePaths,
        exclude_paths: filters.excludePaths,
      }),
    });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();

    const sourceRows = Array.isArray(data.sources) ? data.sources : [];
    const citationEntries = buildApaCitationEntries(sourceRows);
    let answer = data.answer || "[no brief field]";

    lastPdfSources = sourceRows;
    lastCitationQuery = query;

    await addMessageAndStore("assistant", answer, {
      citationEntries,
      citationQuery: query,
    });
    await stashResponse(answer, {
      entry_type: "study_brief",
      query,
      sources: Array.isArray(data.sources) ? data.sources : [],
    });
    metaEl.textContent = "Study brief ready (and stashed)";
  } catch (err) {
    addMessage("system", `Study brief failed: ${err.message}`);
    metaEl.textContent = "Study brief failed";
  } finally {
    setBusy(false);
  }
}

function formatEpoch(ts) {
  if (!ts) return "never";
  const d = new Date(ts * 1000);
  return d.toLocaleString();
}

function summarizeIndexError(rawError) {
  if (!rawError) return "";
  const text = String(rawError).replace(/\\r/g, "");
  const lines = text
    .split("\\n")
    .map((line) => line.trim())
    .filter(Boolean);
  let best = lines.length ? lines[lines.length - 1] : text.trim();
  if (!best || /^traceback/i.test(best)) {
    const fallback = lines.find((line) => !/^traceback/i.test(line));
    best = fallback || "Indexing failed (see logs)";
  }
  if (best.length > 180) best = `${best.slice(0, 177)}...`;
  return best;
}

async function refreshPdfStatus() {
  try {
    const res = await fetch("/api/pdf/status");
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();
    const job = data.index_job || {};
    const docs = data.documents ?? 0;
    const chunks = data.chunks ?? 0;
    const idx = formatEpoch(data.last_indexed_at);
    const running = job.running ? "running" : "idle";

    if (job.running) {
      if (!syncSnapshot) {
        syncSnapshot = {
          startedAt: Number(
            job.last_started_at || Math.floor(Date.now() / 1000),
          ),
          startDocs: Number(docs || 0),
          startChunks: Number(chunks || 0),
        };
      }
      const elapsedSec = Math.max(
        1,
        Math.floor(Date.now() / 1000) -
          Number(syncSnapshot.startedAt || Math.floor(Date.now() / 1000)),
      );
      const chunkDelta = Math.max(
        0,
        Number(chunks || 0) - Number(syncSnapshot.startChunks || 0),
      );
      const chunksPerMin = Math.round((chunkDelta / elapsedSec) * 60);

      const result =
        job.last_result && typeof job.last_result === "object"
          ? job.last_result
          : {};
      const processed = Number(
        result.processed || result.updated || result.indexed || 0,
      );
      const total = Number(
        result.total || result.discovered || result.candidates || 0,
      );
      let progressPct = 0;
      let etaText = "ETA: estimating";

      if (
        Number.isFinite(total) &&
        total > 0 &&
        Number.isFinite(processed) &&
        processed >= 0
      ) {
        progressPct = Math.max(
          0,
          Math.min(100, Math.round((processed / total) * 100)),
        );
        const remaining = Math.max(0, total - processed);
        const perSec = processed > 0 ? processed / elapsedSec : 0;
        if (perSec > 0) {
          const etaSec = Math.round(remaining / perSec);
          etaText = `ETA: ~${Math.max(0, Math.ceil(etaSec / 60))} min`;
        }
      } else {
        progressPct = Math.max(
          8,
          Math.min(92, 12 + Math.round(Math.min(80, elapsedSec / 3))),
        );
      }

      pdfProgressEl.classList.remove("hidden");
      pdfProgressBarEl.style.width = `${progressPct}%`;
      pdfStatusEl.textContent = `PDF index: running (${progressPct}%)\nDocs: ${docs} | Chunks: ${chunks} | +${chunkDelta} this run\nElapsed: ${Math.ceil(elapsedSec / 60)} min | ${etaText} | ${chunksPerMin}/min`;
    } else {
      syncSnapshot = null;
      pdfProgressEl.classList.add("hidden");
      pdfProgressBarEl.style.width = "0%";
      const compactError = summarizeIndexError(job.last_error);
      const statusTail = compactError ? `\nLast error: ${compactError}` : "";
      pdfStatusEl.textContent = `PDF index: ${running}\nDocs: ${docs} | Chunks: ${chunks}\nLast indexed: ${idx}${statusTail}`;
    }
  } catch (err) {
    pdfProgressEl.classList.add("hidden");
    pdfProgressBarEl.style.width = "0%";
    pdfStatusEl.textContent = `PDF index status error: ${err.message}`;
  }
}

function renderUpdateUi(data) {
  const currentVersion = String((data && data.current_version) || "unknown");
  const latestVersion = String((data && data.latest_version) || "").trim();
  const notesUrl = sanitizeNotesUrl((data && data.release_notes_url) || "");
  const updateAvailable = Boolean(data && data.update_available);
  const source = String((data && data.source) || "none");
  const branch = String((data && data.branch) || "main");
  const applyTarget = String((data && data.apply_target) || "").trim();
  const state = String((data && data.state) || "idle");
  const message = String((data && data.message) || "Not checked");
  const err = data && data.last_error ? ` | ${data.last_error}` : "";

  appVersionEl.textContent = `Version: ${currentVersion}`;
  updateStatusEl.textContent = `Updates: ${state} (${source}) - ${message}${err}`;

  if (notesUrl) {
    updateNotesLinkEl.href = notesUrl;
    updateNotesLinkEl.hidden = false;
  } else {
    updateNotesLinkEl.href = "#";
    updateNotesLinkEl.hidden = true;
  }

  if (source === "git") {
    latestUpdateVersion = updateAvailable ? branch : "";
  } else {
    latestUpdateVersion = updateAvailable ? applyTarget || latestVersion : "";
  }
  applyUpdateEl.disabled = !latestUpdateVersion;
  if (source === "git") {
    applyUpdateEl.textContent = latestUpdateVersion
      ? `Sync from ${latestUpdateVersion}`
      : `Sync from ${branch}`;
  } else {
    applyUpdateEl.textContent = latestUpdateVersion
      ? `Update to ${latestUpdateVersion}`
      : "Update to Latest";
  }
}

async function refreshUpdateStatus() {
  try {
    const res = await fetch("/api/update/status");
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();
    renderUpdateUi(data || {});
  } catch (err) {
    updateStatusEl.textContent = `Updates: status error - ${err.message}`;
  }
}

async function checkForUpdates() {
  checkUpdatesEl.disabled = true;
  const original = checkUpdatesEl.textContent;
  checkUpdatesEl.textContent = "Checking...";
  try {
    const res = await fetch("/api/update/check", { method: "POST" });
    const data = await res.json();
    if (!res.ok || data.ok === false) {
      const detail =
        (data && (data.error || data.last_error)) || `HTTP ${res.status}`;
      throw new Error(detail);
    }
    if (data && data.release && !data.release_notes_url) {
      data.release_notes_url = sanitizeNotesUrl(data.release.notes_url || "");
    }
    renderUpdateUi(data || {});
    metaEl.textContent = data.update_available
      ? `Update available: ${data.latest_version}`
      : "Already on latest version";
  } catch (err) {
    updateStatusEl.textContent = `Updates: check failed - ${err.message}`;
    metaEl.textContent = "Update check failed";
  } finally {
    checkUpdatesEl.disabled = false;
    checkUpdatesEl.textContent = original;
  }
}

async function applyUpdate() {
  if (!latestUpdateVersion) return;
  applyUpdateEl.disabled = true;
  try {
    const res = await fetch("/api/update/apply", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ target_version: latestUpdateVersion }),
    });
    const data = await res.json();
    if (!res.ok || data.ok === false) {
      const detail =
        (data && (data.error || data.message)) || `HTTP ${res.status}`;
      throw new Error(detail);
    }
    renderUpdateUi((data && data.state) || data || {});
    metaEl.textContent = data.message || "Update job started";
  } catch (err) {
    updateStatusEl.textContent = `Updates: apply failed - ${err.message}`;
    metaEl.textContent = "Update apply failed";
  } finally {
    applyUpdateEl.disabled = !latestUpdateVersion;
  }
}

async function syncPdfLibrary() {
  syncPdfLibraryEl.disabled = true;
  syncPdfLibraryEl.textContent = "Syncing...";
  try {
    const res = await fetch("/api/pdf/index", { method: "POST" });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    syncSnapshot = {
      startedAt: Math.floor(Date.now() / 1000),
      startDocs: 0,
      startChunks: 0,
    };
    pdfProgressEl.classList.remove("hidden");
    pdfProgressBarEl.style.width = "8%";
    metaEl.textContent = "PDF index sync started";
  } catch (err) {
    addMessage("system", `Failed to start PDF sync: ${err.message}`);
  } finally {
    syncPdfLibraryEl.disabled = false;
    syncPdfLibraryEl.textContent = "Sync New PDFs";
    refreshPdfStatus();
  }
}

function setBusy(isBusy) {
  sendEl.disabled = isBusy;
  promptUseSelectedEl.disabled = isBusy;
  promptPinSelectedEl.disabled = isBusy;
  promptClearHistoryEl.disabled = isBusy;
  promptHistorySelectEl.disabled = isBusy;
  cancelEl.disabled = !isBusy;
  refreshEl.disabled = isBusy;
  modelEl.disabled = isBusy;
  instructionsEl.disabled = isBusy;
  saveInstructionsEl.disabled = isBusy;
  usePdfLibraryEl.disabled = isBusy;
  deepStudyEl.disabled = isBusy;
  syncPdfLibraryEl.disabled = isBusy;
  uploadLibraryDocsEl.disabled = isBusy;
  openLibraryDocsEl.disabled = isBusy;
  openStashEl.disabled = isBusy;
  studyBriefEl.disabled = isBusy;
  clearEl.disabled = isBusy;
  sendEl.textContent = isBusy ? "Thinking..." : "Send";
}

function cancelPromptRequest() {
  if (!activeRequestController) return;
  cancelEl.disabled = true;
  metaEl.textContent = "Cancelling...";
  activeRequestController.abort();
}

async function loadModels() {
  modelEl.innerHTML = "";
  setStatus("", "Checking service...");
  try {
    const res = await fetch("/api/tags");
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();
    const models = (data.models || []).map((m) => m.name);

    if (!models.length) {
      const opt = document.createElement("option");
      opt.textContent = "No models found";
      opt.value = "";
      modelEl.appendChild(opt);
      setStatus("err", "No models installed");
      return;
    }

    for (const name of models) {
      const opt = document.createElement("option");
      opt.value = name;
      opt.textContent = name;
      modelEl.appendChild(opt);
    }
    const preferred = models.includes("qwen2.5:14b")
      ? "qwen2.5:14b"
      : models[0];
    modelEl.value = preferred;
    setStatus("ok", `Online (${models.length} models)`);
  } catch (err) {
    setStatus("err", "Service unreachable");
    addMessage("system", `Failed to load models: ${err.message}`);
  }
}

async function loadHistory() {
  messagesEl.innerHTML = "";
  try {
    const res = await fetch("/api/history");
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();
    const items = Array.isArray(data.messages) ? data.messages : [];
    if (!items.length) {
      addMessage(
        "assistant",
        "Shared history is empty. Start the conversation.",
        {
          showAssistantTools: false,
        },
      );
      return;
    }
    for (const item of items) {
      const role = ["user", "assistant", "system"].includes(item.role)
        ? item.role
        : "system";
      const text = typeof item.text === "string" ? item.text : "";
      if (!text) continue;
      if (role === "user") {
        rememberPrompt(text, false);
        lastUserPrompt = text;
      }
      addMessage(role, text);
    }
    persistPromptHistory();
  } catch (err) {
    addMessage("system", `Failed to load shared history: ${err.message}`);
  }
}

async function sendPrompt() {
  if (activeRequestController) return;

  const prompt = promptEl.value.trim();
  const model = modelEl.value;
  const instructions = instructionsEl.value.trim();
  const usePdfLibrary = usePdfLibraryEl.checked;
  const deepStudy = deepStudyEl.checked;
  if (!prompt) return;
  if (!model) {
    addMessage("system", "No model is available. Install a model and refresh.");
    return;
  }

  rememberPrompt(prompt);

  if (!usePdfLibrary) {
    const proceedUngrounded = confirm(
      "Send this query without PDF grounding?\\n\\nThis app is optimized for PDF-grounded answers, and ungrounded queries are usually better handled by general chat tools.",
    );
    if (!proceedUngrounded) {
      usePdfLibraryEl.checked = true;
      metaEl.textContent = "PDF-grounded mode re-enabled";
      return;
    }
  }

  lastUserPrompt = prompt;
  pendingPromptText = prompt;

  await addMessageAndStore("user", prompt);
  promptEl.value = "";
  setBusy(true);
  metaEl.textContent = `Model: ${model}`;

  const start = performance.now();
  const requestController = new AbortController();
  activeRequestController = requestController;
  try {
    let answer = "";
    if (usePdfLibrary) {
      const filters = buildDocFiltersForRequest();
      if (libraryDocs.length) {
        const selectionError = buildDocSelectionError(filters);
        if (selectionError) {
          throw new Error(selectionError);
        }
      }
      const res = await fetch("/api/pdf/ask", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        signal: requestController.signal,
        body: JSON.stringify({
          query: prompt,
          model,
          top_k: deepStudy ? 16 : 8,
          deepen: deepStudy,
          include_paths: filters.includePaths,
          exclude_paths: filters.excludePaths,
        }),
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      if (data.ok === false && data.error) {
        throw new Error(data.error);
      }
      const sourceRows = Array.isArray(data.sources) ? data.sources : [];
      const citationEntries = buildApaCitationEntries(sourceRows);
      answer = data.answer || "[no answer field]";
      lastPdfSources = sourceRows;
      lastCitationQuery = prompt;
      await addMessageAndStore("assistant", answer, {
        citationEntries,
        citationQuery: prompt,
      });
    } else {
      const res = await fetch("/api/generate", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        signal: requestController.signal,
        body: JSON.stringify({
          model,
          prompt,
          stream: false,
          system: instructions || undefined,
          keep_alive: "60s",
        }),
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      answer = data.response || "[no response field]";
      await addMessageAndStore("assistant", answer);
    }

    const elapsedMs = Math.round(performance.now() - start);
    metaEl.textContent = `Model: ${model}${usePdfLibrary ? " + PDF" : ""} | ${elapsedMs} ms`;
  } catch (err) {
    if (err && err.name === "AbortError") {
      // Keep the canceled query in the input so users can quickly adjust and resend.
      if (!promptEl.value.trim()) {
        promptEl.value = pendingPromptText;
      }
      promptEl.focus();
      addMessage("system", "Request canceled.");
      metaEl.textContent = "Request canceled";
    } else {
      addMessage("system", `Request failed: ${err.message}`);
      metaEl.textContent = "Request failed";
    }
  } finally {
    if (activeRequestController === requestController) {
      activeRequestController = null;
    }
    pendingPromptText = "";
    setBusy(false);
  }
}

refreshEl.addEventListener("click", loadModels);
openLibraryDocsEl.addEventListener("click", openLibraryDocsModal);
openBibliographyEl.addEventListener("click", () =>
  openStashModal("bibliography"),
);
docsCloseEl.addEventListener("click", closeLibraryDocsModal);
docsReloadEl.addEventListener("click", async () => {
  try {
    await loadLibraryDocs();
  } catch (err) {
    docsMetaEl.textContent = `Failed to load library docs: ${err.message}`;
  }
});
docsSelectAllEl.addEventListener("click", () => {
  excludedDocPaths = new Set();
  persistDocFilterState();
  renderLibraryDocs();
});
docsSelectNoneEl.addEventListener("click", () => {
  excludedDocPaths = new Set(libraryDocs.map((d) => d.path));
  persistDocFilterState();
  renderLibraryDocs();
});
docsSearchEl.addEventListener("input", renderLibraryDocs);
docsModalEl.addEventListener("click", (e) => {
  if (e.target === docsModalEl) closeLibraryDocsModal();
});
openStashEl.addEventListener("click", () => openStashModal("stash"));
stashCloseEl.addEventListener("click", closeStashModal);
stashReloadEl.addEventListener("click", async () => {
  try {
    await loadStashEntries();
  } catch (err) {
    stashMetaEl.textContent = `Failed to load stash: ${err.message}`;
  }
});
stashClearAllEl.addEventListener("click", async () => {
  const clearLabel =
    stashViewMode === "bibliography"
      ? "all bibliography entries"
      : "all stashed snippets";
  if (!confirm(`Delete ${clearLabel}?`)) return;
  try {
    const clearEndpoint =
      stashViewMode === "bibliography"
        ? "/api/bibliography?all=1"
        : "/api/stash?all=1";
    const res = await fetch(clearEndpoint, { method: "DELETE" });
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || `HTTP ${res.status}`);
    await loadStashEntries();
    metaEl.textContent =
      stashViewMode === "bibliography"
        ? "Cleared bibliography stash"
        : "Cleared stash";
  } catch (err) {
    stashMetaEl.textContent = `Failed to clear stash: ${err.message}`;
  }
});
stashModalEl.addEventListener("click", (e) => {
  if (e.target === stashModalEl) closeStashModal();
});
saveInstructionsEl.addEventListener("click", saveInstructions);
evaluateAbstractEl.addEventListener("click", evaluateAbstract);
clearAbstractEl.addEventListener("click", clearAbstractInputs);
abstractTextEl.addEventListener("keydown", (e) => {
  if ((e.ctrlKey || e.metaKey) && e.key === "Enter") {
    e.preventDefault();
    evaluateAbstract();
  }
});
syncPdfLibraryEl.addEventListener("click", syncPdfLibrary);
checkUpdatesEl.addEventListener("click", checkForUpdates);
applyUpdateEl.addEventListener("click", applyUpdate);
uploadLibraryDocsEl.addEventListener("click", () => {
  pickLibraryFilesAndUpload();
});
usePdfLibraryEl.addEventListener("change", () => {
  if (usePdfLibraryEl.checked) {
    metaEl.textContent = "PDF-grounded mode enabled";
    return;
  }
  const proceedUngrounded = confirm(
    "Turn off PDF grounding?\\n\\nOllama Librarian is intended primarily for PDF-grounded research. Continue with ungrounded mode?",
  );
  if (!proceedUngrounded) {
    usePdfLibraryEl.checked = true;
    metaEl.textContent = "PDF-grounded mode kept on";
    return;
  }
  metaEl.textContent = "Ungrounded mode enabled";
});
studyBriefEl.addEventListener("click", createStudyBrief);
makeBibliographyEl.addEventListener(
  "click",
  generateBibliographyFromLatestSources,
);
cancelEl.addEventListener("click", cancelPromptRequest);
clearEl.addEventListener("click", async () => {
  try {
    await fetch("/api/history", { method: "DELETE" });
  } catch (_) {
    // If delete fails, still clear local view for usability.
  }
  messagesEl.innerHTML = "";
  addMessage("assistant", "Shared history cleared.", {
    showAssistantTools: false,
  });
  metaEl.textContent = "Ready";
  promptEl.focus();
});
sendEl.addEventListener("click", sendPrompt);
promptUseSelectedEl.addEventListener("click", askSelectedPrompt);
promptPinSelectedEl.addEventListener("click", togglePinSelectedPrompt);
promptClearHistoryEl.addEventListener("click", () => {
  if (!confirm("Clear unpinned prompt history?")) return;
  clearPromptHistory();
});
promptHistorySelectEl.addEventListener("change", () => {
  const selected = String(promptHistorySelectEl.value || "").trim();
  if (!selected) return;
  promptEl.value = selected;
  promptEl.focus();
  promptEl.setSelectionRange(promptEl.value.length, promptEl.value.length);
});
promptEl.addEventListener("keydown", (e) => {
  if (e.ctrlKey && !e.shiftKey && e.key === "ArrowUp") {
    e.preventDefault();
    recallPromptHistory(-1);
    return;
  }
  if (e.ctrlKey && !e.shiftKey && e.key === "ArrowDown") {
    e.preventDefault();
    recallPromptHistory(1);
    return;
  }
  if (e.key === "Enter" && !e.shiftKey) {
    e.preventDefault();
    sendPrompt();
  }
});

promptHistory = loadPromptHistory();
pinnedPrompts = loadPinnedPrompts();
promptHistoryIndex = promptHistory.length;
renderPromptHistoryDropdown();
loadHistory();
loadInstructions();
loadModels();
refreshPdfStatus();
refreshUpdateStatus();
setInterval(refreshPdfStatus, 15000);
setInterval(refreshUpdateStatus, 30000);
