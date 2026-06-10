# Ollama-Librarian Error Handling Analysis

## Executive Summary

The ollama-librarian codebase has a mixed error handling approach with room for improvement. While basic error handling exists at the HTTP layer, there are inconsistencies in error messaging, logging, and response formats. The main issues are:

1. **Inconsistent error response structures** - some endpoints return `{error: ...}`, others return `{ok: false, error: ...}`
2. **Generic error messages** - exceptions are often caught broadly without providing context
3. **Limited error logging** - most errors are captured but not logged for debugging
4. **Missing status codes for specific scenarios** - some error conditions are returned with generic 500 status
5. **Frontend error handling** - relies heavily on extracting `error` or `last_error` fields from responses

---

## 1. Key Files Involved in Error Handling

### Backend (Python)
- **src/ollama_librarian/web.py** (3280 lines)
  - Main HTTP request handler with 30+ route handlers
  - Error handling at request validation and route level
  - Proxy to Ollama API with error translation
  
- **src/ollama_librarian/indexer.py** (2260 lines)
  - PDF/document indexing with extensive error points
  - Ollama API interaction and embedding errors
  - OCR processing errors
  - Database operations
  
### Frontend (JavaScript)
- **src/ollama_librarian/assets/app.js** (2973 lines)
  - Error extraction from JSON responses
  - Error display in UI
  - Status polling with error handling

---

## 2. Current Error Response Formats

### Format Variations Found

#### Format 1: Simple Error Object (Most Common)
```json
{"error": "error message"}
```
**Used in:**
- PDF file retrieval endpoints (404 responses)
- Stash operations (DELETE)
- Library document listing (500)
- General file operations

#### Format 2: OK + Error Pattern
```json
{"ok": false, "error": "error message"}
```
**Used in:**
- Abstract evaluation (`_handle_post_abstract_evaluate`)
- PDF source path setting (`_handle_post_pdf_source`)
- PDF source picker (`_handle_post_pdf_source_pick`)
- Update apply operations (`_handle_post_update_apply`)

#### Format 3: Last Error Field (Async Operations)
```json
{
  "ok": true,
  "index_job": {
    "running": false,
    "last_error": "specific error message",
    ...
  }
}
```
**Used in:**
- PDF status (`get_pdf_status`)
- Update status (`get_update_status`)

#### Format 4: Proxy Pass-through
```
HTTP Status with original Ollama error response
```
**Used in:**
- `/api/generate` (proxied directly)
- `/api/tags` (proxied directly)

---

## 3. HTTP Status Codes Used

| Code | Usage | Frequency |
|------|-------|-----------|
| **200** | Success | Very common |
| **202** | Accepted (Update apply started) | 1 use |
| **400** | Invalid request / validation errors | 15+ uses |
| **401** | Unauthorized (missing API key) | 1 use |
| **403** | Forbidden (CORS/origin violations) | 3 uses |
| **404** | Not found (missing files/entries) | 5+ uses |
| **409** | Conflict (indexing in progress, update running) | 3 uses |
| **412** | Precondition failed (update preflight check) | 1 use |
| **413** | Payload too large | 3 uses |
| **500** | Generic server error | 8+ uses |
| **502** | Bad gateway (Ollama connection issues) | 7+ uses |

---

## 4. Error Handling Patterns by Operation Type

### A. Ollama API Interactions

**Location:** `web.py` lines 784-792 and 1792-1799

```python
try:
    with urlopen(req, timeout=90) as resp:
        body = resp.read().decode("utf-8", errors="replace")
except HTTPError as exc:
    detail = exc.read().decode("utf-8", errors="replace")
    raise RuntimeError(f"HTTP {exc.code}: {detail}") from exc
except URLError as exc:
    raise RuntimeError(f"Cannot reach Ollama at {OLLAMA_BASE}: {exc}") from exc
```

**Status Code:** 502 returned to client
**Logging:** Line 2700 uses `LOGGER.warning()` for evaluation failures
**Issue:** No distinction between transient vs permanent Ollama failures

---

### B. PDF Indexing Operations

**Location:** `web.py` lines 1550-1616 (indexer worker thread)

```python
def _index_worker():
    try:
        # ... run indexing command
        if proc.returncode != 0:
            detail = (err or out or "").strip()
            raise RuntimeError(detail or f"Command failed: {' '.join(cmd)}")
    except Exception as exc:
        with PDF_LOCK:
            PDF_INDEX_STATE["last_error"] = str(exc)
    finally:
        # cleanup
```

**Status:** Stored in `PDF_INDEX_STATE["last_error"]`
**Logging:** No LOGGER call; error only stored internally
**UI Display:** `app.js` line 2115 `summarizeIndexError()` extracts and displays

---

### C. File Operations

**Location:** `web.py` lines 2257-2271 (library file resolution)

```python
def _resolve_library_file_path(self, requested_path):
    if not isinstance(requested_path, str) or not requested_path.strip():
        return None, "path is required", 400
    
    if not resolved_path.startswith(resolved_root + os.sep):
        return None, "path is outside configured PDF library", 403
    
    if not os.path.isfile(resolved_path):
        return None, "File not found", 404
    
    return resolved_path, None, 200
```

**Patterns:** Returns tuple (path, error_msg, status_code)
**Consistency:** Good - all file operations use this pattern
**Issue:** Generic messages without context

---

### D. PDF Ask (Retrieval Augmented Generation)

**Location:** `web.py` lines 2852-2901

```python
try:
    result = ask_pdf_library(...)
    normalized = normalize_pdf_ask_response_contract(result)
    return self._send(200, ...)
except Exception as exc:
    return self._send(502, json.dumps({"error": str(exc)}), ...)
```

**Status Code:** 502 for ANY exception
**Logging:** None
**Issue:** All failures treated as 502 (Bad Gateway), even application errors

---

### E. Update Operations

**Location:** `web.py` lines 1059-1133 (check for updates)

```python
try:
    release = dict(fetch_latest_release())
    available = is_newer_version(latest, current)
    _set_update_state(state="available" if available else "idle", ...)
except HTTPError as exc:
    if int(getattr(exc, "code", 0) or 0) == 404:
        return check_for_git_updates()  # fallback
    
    _set_update_state(state="failed", last_error=str(exc))
    return {"ok": False, "error": str(exc)}
except Exception as exc:
    _set_update_state(state="failed", last_error=str(exc))
    return {"ok": False, "error": str(exc)}
```

**Status Code:** 502 returned
**Logging:** None at this level
**Error Storage:** Stored in UPDATE_STATE for polling

---

## 5. Types of Errors That Lack Good Messages

### 1. PDF Processing Errors
- Missing pypdf library: `"PDF parsing dependency is missing. Install 'pypdf'."`
- OCR failures: Only raw subprocess output, no context about which file failed
- Missing pages: Silent failure, no indication that extraction failed
- Corrupted PDFs: Generic "Unexpected embedding response" message

**Example from `indexer.py` line 534:**
```python
raise RuntimeError("Unexpected embedding response format from Ollama")
```
**Problem:** Doesn't indicate which embedding request failed, or what format was received

### 2. Ollama Connectivity Issues
- Timeout during embedding: No distinction between "Ollama is down" vs "Ollama is slow"
- Network errors: Caught as generic URLError with just the exception string
- Response parsing: Generic "Invalid response from Ollama" (line 798)

**Example from `web.py` line 797:**
```python
except Exception as exc:
    raise RuntimeError("Invalid response from Ollama generate endpoint") from exc
```
**Problem:** Doesn't include the actual invalid response content

### 3. Database Errors
- SQLite connection errors: No specific handling, caught generically
- Transaction failures: No rollback strategy mentioned
- Constraint violations: Would be generic Exception

**Location:** `web.py` lines 1979-1985
```python
conn = sqlite3.connect(index_db)
try:
    rows = conn.execute(...)
finally:
    conn.close()
# No error handling!
```

### 4. Configuration Errors
- Invalid paths: Some checked, some not
- Missing files: Generic "file not found"
- Permission errors: Caught but not distinguished

**Example from `web.py` line 387:**
```python
raise RuntimeError("configured path is not a directory")
```
**Problem:** Doesn't specify which configuration or what path was problematic

### 5. Async Operation Errors
- Index job failures: Only visible via polling `/api/pdf/status`
- Update job failures: Only visible via polling `/api/update/status`
- No immediate feedback, requires UI to periodically check

---

## 6. Error Logging Mechanisms

### Current Logging Setup

**Logger Definition:** `web.py` line 26
```python
LOGGER = logging.getLogger("ollama_web_chat")
```

**Logging Locations:**
1. **Line 51** - Environment variable parsing warnings
2. **Line 356** - PDF source override parsing failures
3. **Line 390** - Invalid PDF source override configuration
4. **Line 592** - Failed to persist update state (exception-level)
5. **Line 642** - Failed to load persisted update state (exception-level)
6. **Line 893** - Unsafe release notes URL (warning)
7. **Line 2700** - Abstract evaluation failures (warning)
8. **Line 2708** - Unexpected evaluation failures (exception-level)

### Problems with Current Logging

1. **Inconsistent Usage** - Only 8 logging calls in 3280 lines
2. **No Request Context** - Don't include request ID, user info, or operation type
3. **No Error Categorization** - Don't distinguish transient vs permanent failures
4. **Silent Failures** - Most errors stored in state objects, never logged
5. **Missing Structured Logging** - All messages are strings, no structured fields

### Errors NOT Logged

- PDF indexing failures (caught at line 1608, stored but not logged)
- PDF ask failures (caught at line 2896, not logged)
- File upload/download errors (caught but not logged)
- Stash operation errors (caught but not logged)
- Update check failures for non-HTTP errors (some logged, some not)
- Ollama API errors through proxy (passed through without logging)

---

## 7. Web Interface Error Display

### JavaScript Error Extraction Pattern

**Common Pattern (appears 20+ times):**
```javascript
if (!res.ok) throw new Error(data.error || `HTTP ${res.status}`);
```

**Variations:**
```javascript
// Pattern 1: Simple error
throw new Error(data.error || `HTTP ${res.status}`)

// Pattern 2: With fallback
throw new Error(data.error || data.message || `HTTP ${res.status}`)

// Pattern 3: Check ok field
if (data.ok === false && data.error) throw new Error(data.error)

// Pattern 4: Multiple field checks
(data && (data.error || data.last_error)) || `HTTP ${res.status}`
```

### Error Display Locations

1. **PDF Index Status** (`app.js` lines 2189-2194)
   - Displays in `pdfStatusErrorEl`
   - Shows last_error from status
   - Limited to 1 line in UI

2. **Update Status** (`app.js` lines 2357-2394)
   - Displays in `updateStatusEl`
   - Shows last_error or generic "status error"
   - Polling-based (15 second refresh)

3. **PDF Ask Results** (`app.js` lines 2852-2901)
   - Shows error in throw
   - Caught by generic error handler
   - Displays as toast/alert

4. **File Upload** (`app.js` lines 168-186)
   - Collects failures from each file
   - Displays file-by-file in modal

### UI Error Handling Issues

1. **Limited Space** - Status errors truncated to single line
2. **Polling Delays** - Async errors may not appear for 15 seconds
3. **No Error Codes** - Can't distinguish error types programmatically
4. **No Retry Logic** - User must manually retry failed operations
5. **No Error Details** - Long errors truncated with no way to expand

---

## 8. Specific Scenarios and Status Codes

### Scenario: Ollama Connection Fails

**HTTP Request Path:**
1. Client calls `/api/abstract/evaluate`
2. Handler calls `evaluate_abstract_relevance()`
3. `urlopen()` fails with URLError
4. RuntimeError raised: "Cannot reach Ollama at..."
5. Caught at line 2699, returned as 502

**Response:**
```json
HTTP 502
{"ok": false, "error": "Cannot reach Ollama at http://127.0.0.1:11434: ..."}
```

**Issues:**
- 502 is technically correct but no "Retry-After" header
- No indication if user should retry or check Ollama service
- Error message includes base URL (could be a security consideration)

---

### Scenario: PDF File Not Found

**HTTP Request Path:**
1. Client calls `/api/pdf/file?path=/some/file.pdf`
2. Handler calls `_resolve_library_file_path()`
3. Returns (None, "File not found", 404)
4. Handler returns 404 with error

**Response:**
```json
HTTP 404
{"error": "File not found"}
```

**Issues:**
- Doesn't indicate if path is outside library or truly missing
- No trace of which file was requested (for debugging)
- Security issue: reveals filesystem structure

---

### Scenario: PDF Indexing Fails Mid-Process

**HTTP Request Path:**
1. Client calls `/api/pdf/index` to start indexing
2. Returns 200 immediately
3. Background thread spawned
4. Indexing fails (e.g., corrupted PDF)
5. Error stored in `PDF_INDEX_STATE["last_error"]`
6. Client polls `/api/pdf/status` every 15 seconds
7. Eventually sees `"last_error": "ocrmypdf failed..."`

**Response:**
```json
HTTP 200
{
  "ok": true,
  "running": false,
  "index_job": {
    "last_error": "ocrmypdf failed with code 1",
    "running": false,
    "last_started_at": 1717241000,
    "last_finished_at": 1717241045
  }
}
```

**Issues:**
- User doesn't know failure occurred until next poll
- No indication of which file failed
- Generic subprocess error message
- No way to retry just the failed file

---

### Scenario: Update Check Fails

**HTTP Request Path:**
1. Client calls `/api/update/check`
2. Handler calls `check_for_updates()`
3. HTTP request to GitHub API fails
4. HTTPError or generic Exception caught
5. State updated with error
6. Returned as 502

**Response:**
```json
HTTP 502
{
  "ok": false,
  "error": "HTTP 403: API rate limit exceeded",
  "state": {
    "state": "failed",
    "step": "check_failed",
    "message": "Update check failed",
    "last_error": "HTTP 403: API rate limit exceeded"
  }
}
```

**Issues:**
- Generic 502 for all failures (rate limit, network, auth)
- No indication of whether to retry or wait
- Error message from GitHub API leaks through without sanitization

---

### Scenario: User Uploads Non-PDF File

**HTTP Request Path:**
1. Client calls `/api/library/upload?name=file.txt`
2. Handler calls `_resolve_upload_target_path()`
3. Validates extension against SUPPORTED_DOC_EXTENSIONS
4. Returns (None, None, error_msg, 400)
5. Handler returns 400

**Response:**
```json
HTTP 400
{"error": "unsupported file extension (allowed: .pdf, .txt, .md, .html, .htm, .epub)"}
```

**Issues:**
- Good error message
- But user might not see full list if text is truncated
- No indication of what they uploaded

---

## 9. Error Response Format Inconsistencies

### Comparison Matrix

| Endpoint | Success Format | Error Format | Status |
|----------|---|---|---|
| `/api/tags` | Ollama format | Ollama format | varies |
| `/api/history` | `{messages: [...]}` | `{error: "..."}` | 400/500 |
| `/api/pdf/status` | `{ok: true, ...}` | `{ok: false, error: "..."}` | 200/500 |
| `/api/stash` | `{ok: true, ...}` | `{error: "..."}` | 200/500 |
| `/api/pdf/ask` | `{answer: "...", ...}` | `{error: "..."}` | 200/502 |
| `/api/abstract/evaluate` | `{confidence: N, ...}` | `{ok: false, error: "..."}` | 200/400/502 |
| `/api/update/check` | `{ok: true, state: {...}}` | `{ok: false, error: "..."}` | 200/502 |

**Key Problems:**
1. Success doesn't always include `ok: true`
2. Some errors are `{error: "..."}`, others are `{ok: false, error: "..."}`
3. Proxy endpoints return Ollama's format
4. Client must check both `error` field AND `ok` field

---

## 10. Recommendations for Improvement

### Priority 1: Standardize Error Response Format

**Recommended Format (RFC 7807-inspired):**
```json
{
  "ok": false,
  "error": "human_readable_message",
  "error_code": "machine_readable_code",
  "error_details": {
    "type": "validation_error|service_error|not_found|...",
    "path": "/api/endpoint",
    "request_id": "uuid-here"  // for tracing
  }
}
```

**Affected Endpoints:** All that return errors (~25 handlers)

---

### Priority 2: Improve Error Logging

**Implement structured logging:**
```python
LOGGER.error("PDF indexing failed", extra={
    "doc_path": str(doc_path),
    "error_type": type(exc).__name__,
    "error_message": str(exc),
    "operation": "pdf_index",
    "request_id": request_id
})
```

**Add logging to:**
- PDF indexing background thread
- PDF ask operations
- File operations
- Update checks
- Abstract evaluations

---

### Priority 3: Add Error Codes for Categorization

**Define error code constants:**
```python
class ErrorCode:
    # Validation
    INVALID_REQUEST = "invalid_request"
    MISSING_PARAMETER = "missing_parameter"
    INVALID_FILE_TYPE = "invalid_file_type"
    
    # Ollama
    OLLAMA_UNREACHABLE = "ollama_unreachable"
    OLLAMA_ERROR = "ollama_error"
    EMBEDDING_FAILED = "embedding_failed"
    
    # PDF Processing
    PDF_PARSE_ERROR = "pdf_parse_error"
    OCR_FAILED = "ocr_failed"
    PDF_CORRUPTED = "pdf_corrupted"
    
    # Database
    DB_ERROR = "database_error"
    
    # Filesystem
    FILE_NOT_FOUND = "file_not_found"
    PATH_TRAVERSAL_DENIED = "path_traversal_denied"
    PERMISSION_DENIED = "permission_denied"
    
    # Async Operations
    OPERATION_IN_PROGRESS = "operation_in_progress"
    OPERATION_TIMEOUT = "operation_timeout"
```

---

### Priority 4: Improve Async Operation Error Visibility

**Instead of polling, use WebSocket or Server-Sent Events:**
```javascript
const eventSource = new EventSource("/api/pdf/index/events");
eventSource.addEventListener("progress", (e) => {
  const data = JSON.parse(e.data);
  if (data.error) showError(data.error);
});
```

**Or return 202 with Location header:**
```
HTTP 202 Accepted
Location: /api/jobs/job-uuid
```

---

### Priority 5: Add Request ID Tracing

**Generate request ID at handler entry:**
```python
def do_POST(self):
    request_id = str(uuid.uuid4())
    self.request_id = request_id
    # ... use in logging ...
```

**Include in error responses:**
```json
{
  "error": "...",
  "request_id": "uuid-here"  // for support/debugging
}
```

---

### Priority 6: Distinguish Transient vs Permanent Errors

**Use appropriate status codes:**
- 429 Too Many Requests (with Retry-After)
- 503 Service Unavailable (with Retry-After)
- 504 Gateway Timeout (indicate retry is appropriate)

**Example for Ollama timeout:**
```python
except socket.timeout:
    return self._send(
        504,
        json.dumps({
            "error": "Ollama request timed out",
            "error_code": "ollama_timeout",
            "retryable": True
        }),
        headers={"Retry-After": "10"}
    )
```

---

### Priority 7: Improve Error Messages for Common Issues

**Current:** `"HTTP 502: Cannot reach Ollama at..."`
**Better:** `"Ollama is not running. Please start it with: ollama serve"`

**Current:** `"File not found"`
**Better:** `"PDF file not found at /path/to/file.pdf (path is outside configured library)"`

**Current:** `"ocrmypdf failed with code 1"`
**Better:** `"OCR processing failed for file.pdf: Language pack 'eng' not found (install with: apt-get install tesseract-ocr-eng)"`

---

### Priority 8: Handle Errors in Proxy Responses

**Current - line 3246-3261:**
```python
def _proxy(self, method, path, data):
    try:
        with urlopen(req, timeout=90) as resp:
            body = resp.read().decode("utf-8", errors="replace")
            return self._send(resp.status, body, ...)
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        return self._send(exc.code, detail, ...)
    except URLError as exc:
        return self._send(502, json.dumps({"error": str(exc)}), ...)
```

**Issue:** Ollama errors passed through unchanged, inconsistent with application errors

**Better:** Normalize Ollama responses
```python
def _proxy(self, method, path, data):
    try:
        # ... 
        parsed = json.loads(body) if body else {}
        # Ensure consistent error format
        if not response_ok and not isinstance(parsed, dict):
            parsed = {"error": body}
        return self._send(resp.status, json.dumps(parsed), ...)
```

---

## 11. Error Handling Gaps by Feature

### PDF Indexing
- [ ] No per-file error reporting
- [ ] No indication of which file failed
- [ ] No ability to skip failed files and continue
- [ ] OCR errors not distinguished from extraction errors
- [ ] Missing dependencies (pypdf, ocrmypdf) could be detected upfront

### PDF Asking (RAG)
- [ ] Timeout not handled distinctly
- [ ] Empty index not distinguished from query error
- [ ] Embedding failures not separated from answer generation failures
- [ ] No indication of how many documents were searched

### Update Checking
- [ ] Rate limit handling is generic
- [ ] No indication of when rate limit resets
- [ ] GitHub API errors not sanitized
- [ ] Token errors not distinguished

### PDF Upload
- [ ] Checksum not validated (integrity not verified)
- [ ] Large files may timeout without clear message
- [ ] No progress indication for large uploads
- [ ] Storage full not distinguished from other write errors

### Library Management
- [ ] Permission errors not distinguished from missing files
- [ ] Symlink handling not documented
- [ ] Path traversal attack prevented but error message doesn't explain why

---

## Summary Table: Error Handling Maturity

| Aspect | Rating | Notes |
|--------|--------|-------|
| **Error Response Format** | 2/5 | Inconsistent, multiple formats |
| **HTTP Status Codes** | 3/5 | Generally appropriate, but some are too generic |
| **Error Messages** | 2/5 | Often too generic or missing context |
| **Error Logging** | 1/5 | Minimal, inconsistent logging |
| **Error Recovery** | 2/5 | Limited retry logic, manual intervention needed |
| **Error Categorization** | 1/5 | No error codes, clients can't distinguish types |
| **Async Error Visibility** | 2/5 | Polling-based, delayed feedback |
| **Security** | 3/5 | Some information leakage, generally careful |
| **Documentation** | 0/5 | No error handling documented |
| **Testing** | 1/5 | Few error scenarios in tests |

**Overall Maturity:** 1.5/5 (Basic - errors handled but with quality issues)

---

## Implementation Priority Roadmap

### Phase 1 (Quick Wins)
1. Add error codes to all endpoints
2. Standardize error response format
3. Add request IDs for tracing
4. Improve error messages for top 5 scenarios

### Phase 2 (Logging & Visibility)
5. Implement structured logging
6. Add logging to all error paths
7. Create error summary dashboard/logs endpoint
8. Improve async error visibility

### Phase 3 (Robustness)
9. Add retry logic for transient errors
10. Implement circuit breaker for Ollama timeouts
11. Add health check for dependencies
12. Improve OCR error messages

### Phase 4 (Polish)
13. Add user-facing error recovery documentation
14. Implement advanced error handling (batch retry, etc.)
15. Add monitoring/alerting for error rates

