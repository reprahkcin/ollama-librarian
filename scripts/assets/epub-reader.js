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

function strictEncodeURIComponent(value) {
  return encodeURIComponent(String(value)).replace(
    /[!'()*]/g,
    (ch) => `%${ch.charCodeAt(0).toString(16).toUpperCase()}`,
  );
}

function getQuery() {
  const params = new URLSearchParams(window.location.search);
  return {
    path: (params.get("path") || "").trim(),
    section: Math.max(1, Number(params.get("section") || "1") || 1),
    cfi: (params.get("cfi") || "").trim(),
  };
}

async function loadEpub() {
  const metaEl = document.getElementById("meta");
  let openTimer = null;
  try {
    const q = getQuery();
    if (!q.path) {
      metaEl.textContent = "Missing EPUB path";
      return;
    }

    if (typeof window.JSZip === "undefined") {
      metaEl.textContent = "EPUB dependency error: JSZip not loaded";
      return;
    }
    if (typeof window.ePub !== "function") {
      metaEl.textContent = "EPUB dependency error: epub.js not loaded";
      return;
    }

    const headers = apiKey ? { "X-API-Key": apiKey } : {};
    const url = `/api/epub/file?path=${strictEncodeURIComponent(q.path)}`;
    metaEl.textContent = "Downloading EPUB...";
    const res = await fetch(url, { headers });
    if (!res.ok) {
      metaEl.textContent = `Failed to load EPUB: HTTP ${res.status}`;
      return;
    }

    metaEl.textContent = "Parsing EPUB (large files can take a while)...";
    const bytes = await res.arrayBuffer();
    const openedAtMs = Date.now();
    openTimer = window.setInterval(() => {
      const elapsed = Math.max(0, Math.floor((Date.now() - openedAtMs) / 1000));
      metaEl.textContent = `Opening EPUB... ${elapsed}s`;
    }, 1000);
    const book = ePub(bytes);
    const rendition = book.renderTo("viewer", {
      width: "100%",
      height: "100%",
    });

    rendition.on("relocated", (loc) => {
      if (openTimer) {
        window.clearInterval(openTimer);
        openTimer = null;
      }
      const start = loc && loc.start ? loc.start : null;
      const href = start && start.href ? start.href : "";
      const disp = start && start.displayed ? start.displayed : null;
      const shown = disp && disp.page ? `p.${disp.page}` : href;
      metaEl.textContent = `${q.path}${shown ? ` | ${shown}` : ""}`;
    });

    const prevBtn = document.getElementById("prev");
    const nextBtn = document.getElementById("next");
    prevBtn.addEventListener("click", () => rendition.prev());
    nextBtn.addEventListener("click", () => rendition.next());

    try {
      if (q.cfi) {
        await rendition.display(q.cfi);
        return;
      }
      const spine =
        book.spine && typeof book.spine.get === "function"
          ? book.spine.get(Math.max(0, q.section - 1))
          : null;
      if (spine && spine.href) {
        await rendition.display(spine.href);
      } else {
        await rendition.display();
      }
    } catch (err) {
      metaEl.textContent = `Failed to open location: ${err && err.message ? err.message : err}`;
      await rendition.display();
    }
  } catch (err) {
    if (openTimer) {
      window.clearInterval(openTimer);
      openTimer = null;
    }
    metaEl.textContent = `Failed to load EPUB: ${err && err.message ? err.message : err}`;
    console.error(err);
  }
}

loadEpub();
