# Error Handling Locations Index

## web.py Error Handlers by Route

### GET Routes
| Route | Handler | Lines | Error Handling |
|-------|---------|-------|---|
| `/` | `_handle_get_root` | 2366-2373 | Template replacement, no errors |
| `/api/tags` | `_handle_get_tags` | 2437-2438 | Proxy (see _proxy) |
| `/api/history` | `_handle_get_history` | 2440-2445 | JSON serialization |
| `/api/instructions` | `_handle_get_instructions` | 2447-2452 | JSON serialization |
| `/api/library/docs` | `_handle_get_library_docs` | 2454-2467 | Try/except, returns 500 on error |
| `/api/stash` | `_handle_get_stash` | 2469-2492 | Try/except, returns 500 on error |
| `/api/bibliography` | `_handle_get_bibliography` | 2494-2514 | Try/except, returns 500 on error |
| `/api/pdf/status` | `_handle_get_pdf_status` | 2516-2521 | No error handling (calls get_pdf_status) |
| `/api/update/status` | `_handle_get_update_status` | 2523-2528 | No error handling |
| `/api/pdf/file` | `_handle_get_pdf_file` | 2550-2576 | File resolution validation |
| `/api/epub/file` | `_handle_get_epub_file` | 2578-2604 | File resolution validation |

### POST Routes
| Route | Handler | Lines | Error Handling |
|-------|---------|-------|---|
| `/api/generate` | `_handle_post_generate` | 2607-2633 | Content-Length validation, proxy |
| `/api/abstract/evaluate` | `_handle_post_abstract_evaluate` | 2635-2720 | RuntimeError→502, Exception→500 |
| `/api/history` | `_handle_post_history` | 2722-2738 | Role validation, no errors |
| `/api/instructions` | `_handle_post_instructions` | 2740-2754 | Type validation, no errors |
| `/api/pdf/index` | `_handle_post_pdf_index` | 2756-2762 | No error handling (async) |
| `/api/pdf/index/pause` | `_handle_post_pdf_index_pause` | 2764-2771 | No error handling |
| `/api/pdf/source` | `_handle_post_pdf_source` | 2773-2814 | ValueError→400, RuntimeError→409, Exception→500 |
| `/api/pdf/source/pick` | `_handle_post_pdf_source_pick` | 3078-3132 | RuntimeError→200, Exception→500 |
| `/api/update/apply` | `_handle_post_update_apply` | 2816-2841 | Error code mapping to status codes |
| `/api/update/check` | `_handle_post_update_check` | 2843-2850 | Returns 502 on error |
| `/api/pdf/ask` | `_handle_post_pdf_ask` | 2852-2901 | Exception→502 (all errors) |
| `/api/library/upload` | `_handle_post_library_upload` | 2903-2990 | Content-Length, file write, ValueError→400, Exception→500 |
| `/api/stash` | `_handle_post_stash` | 2992-3028 | Exception→502 |

### DELETE Routes
| Route | Handler | Lines | Error Handling |
|-------|---------|-------|---|
| `/api/history` | `_handle_delete_history` | 3031-3033 | No error handling |
| `/api/stash` | `_handle_delete_stash` | 3035-3076 | Exception→500 or 404 |
| `/api/bibliography` | `_handle_delete_bibliography` | 3134-3156 | Exception→500 |

## Key Error Functions

### Ollama API Interaction
| Function | Lines | Returns | Errors |
|----------|-------|---------|--------|
| `evaluate_abstract_relevance` | 761-821 | dict | RuntimeError (HTTP 500), Exception (invalid response) |
| `fetch_latest_release` | 857-884 | dict | RuntimeError (various validation) |
| `check_for_updates` | 1059-1133 | dict | HTTPError (404 fallback), generic Exception |
| `check_for_git_updates` | 1016-1056 | dict | RuntimeError (git commands) |

### PDF Operations
| Function | Lines | Returns | Errors |
|----------|-------|---------|--------|
| `get_pdf_status` | 1503-1547 | dict | Exception caught, ok=False returned |
| `start_pdf_index_job` | 1619-1625 | bool | No error handling |
| `ask_pdf_library` | 1628-1661 | dict | RuntimeError (unexpected response) |
| `_index_worker` | 1550-1616 | None | Exception caught, stored in PDF_INDEX_STATE |
| `pause_pdf_index_job` | 1439-1464 | dict | Exception returned as ok=False |

### File Operations
| Function | Lines | Returns | Errors |
|----------|-------|---------|--------|
| `set_pdf_source_path` | 399-433 | dict | ValueError, RuntimeError, OSError |
| `_resolve_library_file_path` | 2257-2271 | (path, error, code) | Returns tuple with error message and code |
| `_resolve_upload_target_path` | 2273-2321 | (root, target, error, code) | Returns tuple with error message and code |
| `list_library_docs` | 1974-2038 | dict | No error handling (sqlite3) |

### Utility Functions
| Function | Lines | Returns | Errors |
|----------|-------|---------|--------|
| `_pick_directory_with_native_dialog` | 436-555 | str or None | RuntimeError (timeout, dialog failure), None (user cancel) |
| `_load_pdf_source_override` | 349-363 | str or None | Exception logged as warning, None returned |
| `_bootstrap_pdf_source_override` | 376-391 | None | Exception logged as warning |

## indexer.py Error Locations

### HTTP Operations
| Function | Lines | Error Handling |
|----------|-------|---|
| `http_post_json` | 495-511 | HTTPError→RuntimeError, URLError→RuntimeError |
| `embed_text` | 514-534 | RuntimeError fallback, final RuntimeError if invalid format |
| `evaluate_abstract_relevance` (web.py) | 784-792 | HTTPError→RuntimeError, URLError→RuntimeError |

### PDF Processing
| Function | Lines | Error Handling |
|----------|-------|---|
| `extract_pdf_pages` | 582-592 | RuntimeError if PdfReader missing |
| `extract_pdf_pages_with_ocr` | 595-626 | RuntimeError if subprocess fails |
| `extract_epub_document_pages` | 443-454 | RuntimeError if epub library missing |
| `extract_markdown_document_pages` | 456-466 | RuntimeError if markdown parsing fails |
| `extract_html_document_pages` | 468-487 | RuntimeError (various) |
| `extract_text_document_pages` | 489-499 | RuntimeError (decoding) |

### Database Operations
| Function | Lines | Error Handling |
|----------|-------|---|
| `metadata_sync_command` | 837-899 | Exception caught in loop, printed to stderr |
| `index_command` | 1300+ | Multiple try/except blocks, JSON output |
| `status_command` | 1400+ | Multiple try/except blocks |
| `ask_command` | 1500+ | Multiple try/except blocks |

## Error Message Locations

### Generic/Poor Messages
- Line 507 (indexer): "HTTP {code} from {endpoint}: {detail}" - OK
- Line 510 (indexer): "Cannot reach Ollama at {base_url}: {exc}" - OK
- Line 534 (indexer): "Unexpected embedding response format from Ollama" - GENERIC
- Line 584 (indexer): "PDF parsing dependency is missing. Install 'pypdf'." - GOOD
- Line 623 (indexer): subprocess error message - GENERIC
- Line 797 (web): "Invalid response from Ollama generate endpoint" - GENERIC
- Line 798 (web): doesn't include actual response
- Line 2703 (web): str(exc) - depends on exception quality

### Good Messages
- Line 387 (web): "configured path is not a directory" - Could be better (which config?)
- Line 2295 (web): "unsupported file extension (allowed: .pdf, .txt, ...)" - GOOD
- Line 2465 (web): "Windows folder dialog timed out after {N}s. You can set the path manually." - GOOD
- Line 2974-2976 (web): "Cannot change library directory while indexing is running" - GOOD

## HTTP Status Code Usage

### 200 OK
- All successful operations
- See routes above

### 202 Accepted
- Line 2824: Update apply started

### 400 Bad Request (15+ uses)
- Line 330, 339, 342, 351: Invalid Content-Length
- Line 348, 361: Request body too large warning
- Line 405, 409, 415: Source path validation
- Line 649, 657, 665: Abstract evaluation validation
- Line 733, 749: History/instructions type validation
- Line 784, 797: Stash text validation
- Line 798-802: File upload validation
- Line 1241: Update target validation
- Line 1829: Stash id validation

### 401 Unauthorized
- Line 2190: Missing API key

### 403 Forbidden
- Line 2209-2213: CORS/Sec-Fetch-Site
- Line 2221-2224: Origin mismatch
- Line 2231-2234: Referer mismatch
- Line 2266: Path traversal attempt

### 404 Not Found
- Line 2269: File not found
- Line 2399, 2565, 2592: PDF/EPUB not found
- Line 3074: Stash entry not found
- Line 3190, 3222, 3244: Route not found

### 409 Conflict
- Line 419-420: Indexing in progress
- Line 2803: Already running error
- Line 2828: Update already running

### 412 Precondition Failed
- Line 2832: Update preflight failed

### 413 Payload Too Large
- Line 346-351: Body too large
- Line 2627-2630: Upload too large
- Line 2934-2940: Upload exceeds maximum

### 500 Internal Server Error
- Line 464-467: Library docs error
- Line 489-492: Stash error
- Line 2710-2714: Unexpected evaluation failure
- Line 2766: Index job failure
- Line 2810-2814: PDF source error
- Line 2834: Update apply failure
- Line 2977-2981: Upload write failure
- Line 3050-3052: Stash clear error
- Line 3090-3093: PDF source pick failure
- Line 3121-3124: PDF source pick failure
- Line 3146-3149: Bibliography clear error

### 502 Bad Gateway
- Line 2702-2705: Abstract evaluation failure
- Line 2845: Update check failure
- Line 2898-2900: PDF ask failure
- Line 3025-3027: Stash write failure
- Line 3261: Ollama connection error (proxy)

## Async Operation State Storage

### PDF_INDEX_STATE (lines 301-310)
```python
{
    "running": bool,
    "last_started_at": timestamp,
    "last_finished_at": timestamp,
    "last_result": dict,
    "last_error": str,  # ERROR FIELD
    "pause_requested": bool,
    "last_paused_at": timestamp,
    "active_pid": int
}
```

### UPDATE_STATE (lines 319-341)
```python
{
    "job_id": str,
    "running": bool,
    "state": "idle|checking|available|applying|done|failed",
    "step": str,
    "progress_pct": int,
    "message": str,
    "last_error": str,  # ERROR FIELD
    ...
}
```

## JavaScript Error Handling (app.js)

### Error Extraction Patterns
- Line 186: `data.error || HTTP ${res.status}`
- Line 524: `data.error || HTTP ${res.status}`
- Line 1322: `data.error || HTTP ${res.status}`
- Line 1612: `data.error || HTTP ${res.status}`
- Line 1704: `data.error || HTTP ${res.status}`
- Line 1732: `data.error || HTTP ${res.status}`
- Line 2115: `summarizeIndexError(rawError)` - custom function
- Line 2357: `data && data.last_error ? ` | ${data.last_error}` : ""`
- Line 2407: `(data && (data.error || data.last_error)) || HTTP ${res.status}`

### Error Display Elements
- Line 75: `pdfStatusErrorEl` - PDF status error
- Line 2183-2194: Shows last_error in `pdfStatusErrorEl`
- Line 2338: "PDF index: status error"
- Line 2357: Update status error message

### Error Summarization
- Line 2115-2117: `summarizeIndexError()` - Truncates and cleans error text

