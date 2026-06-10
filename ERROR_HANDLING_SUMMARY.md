# Error Handling Summary - Quick Reference

## Key Findings

### 1. Three Main Error Response Formats
- **Format A:** `{"error": "message"}` - Simple error (file ops, stash, lists)
- **Format B:** `{"ok": false, "error": "message"}` - Explicit ok field (evaluate, source, updates)
- **Format C:** `{..., "index_job": {"last_error": "..."}}` - Nested for async ops
- **Format D:** Passthrough from Ollama (proxy endpoints)

**Problem:** Clients must handle multiple formats

### 2. HTTP Status Codes
- **502** returned for ANY Ollama connection failure (7+ places)
- **500** returned for generic internal errors (8+ places)
- **400/409/412/413** used for specific validation/state issues
- **Missing:** 429 (rate limit), 503 (service unavailable), 504 (timeout)

### 3. Error Logging is Minimal
- Only 8 LOGGER calls in 3280 lines of web.py
- No logging for: PDF indexing, PDF ask, file ops, stash ops
- No structured logging (no error codes, no request IDs)
- Async operation errors only stored in state, never logged

### 4. Error Messages Lack Context
- "File not found" - doesn't say which file or why
- "ocrmypdf failed with code 1" - doesn't say which PDF or which code means what
- "Cannot reach Ollama" - URL leaked, no recovery advice
- "Unexpected embedding response" - doesn't show what was received

### 5. Async Errors are Invisible Until Polling
- User doesn't know indexing failed until 15 second poll completes
- No way to immediately see which file failed
- No automatic retry or skip mechanism

## Files to Focus On

### Backend
1. **src/ollama_librarian/web.py** - All error responses (30+ handlers)
2. **src/ollama_librarian/indexer.py** - Indexing/embedding errors (20+ try/except blocks)

### Frontend
1. **src/ollama_librarian/assets/app.js** - Error display and extraction (20+ error checks)

## Quick Improvement List

### Immediate (1-2 hours)
1. Add error_code field to ALL error responses
2. Create ErrorCode enum with standard codes
3. Add request IDs to all responses
4. Improve 3 error messages: Ollama connection, PDF parsing, OCR

### Short-term (half day)
5. Add LOGGER calls to: indexing, PDF ask, file operations
6. Standardize error response format to: `{ok, error, error_code, request_id}`
7. Add 429/503/504 status codes for transient errors
8. Improve 5 more error messages

### Medium-term (1-2 days)
9. Add structured logging with request ID, operation, error type
10. Implement WebSocket or polling optimization for async errors
11. Add health check for dependencies (pypdf, ocrmypdf, Ollama)
12. Create error documentation for users

### Long-term (ongoing)
13. Add batch retry capability for failed files
14. Implement circuit breaker for Ollama timeouts
15. Add error metrics/monitoring
16. Test all error paths

## Most Common Error Scenarios

1. **Ollama not running** → 502 "Cannot reach Ollama at..." (no retry hint)
2. **PDF indexing fails mid-process** → Invisible until polling (last_error field)
3. **Corrupted PDF** → Generic subprocess error with no file indication
4. **Rate limited by GitHub** → Generic 502 with no retry-after hint
5. **Invalid file upload** → 400 with good message (best example in codebase)

## Error Handling Maturity Rating

| Category | Current | Target |
|----------|---------|--------|
| Response Format | 2/5 | 5/5 |
| Status Codes | 3/5 | 5/5 |
| Error Messages | 2/5 | 4/5 |
| Logging | 1/5 | 5/5 |
| Error Recovery | 2/5 | 4/5 |
| Error Codes | 1/5 | 5/5 |
| Async Visibility | 2/5 | 4/5 |
| **Overall** | **1.5/5** | **4.5/5** |

See `error_handling_analysis.md` for detailed recommendations and code examples.
