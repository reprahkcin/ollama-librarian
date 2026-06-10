# Ollama-Librarian Error Handling Analysis

This directory contains three comprehensive documents analyzing the error handling in the ollama-librarian codebase.

## Documents

### 1. ERROR_HANDLING_SUMMARY.md (Quick Reference)
**Best for:** Getting a quick overview in 5 minutes
- Key findings on error response formats
- HTTP status code usage
- Common error scenarios
- Error handling maturity ratings
- Quick improvement checklist

**Start here** if you're new to the codebase or need a high-level overview.

### 2. error_handling_analysis.md (Detailed Analysis)
**Best for:** Understanding the full picture and implementation planning
- Executive summary of issues
- Key files and their responsibilities
- Current error response format variations (4 different formats!)
- All HTTP status codes used
- Error handling patterns by operation type
- Types of errors lacking good messages
- Current logging mechanisms and gaps
- Web interface error display
- Specific scenarios with problematic error handling
- Recommendations prioritized by impact

**Read this** when planning improvements or understanding specific areas.

### 3. ERROR_LOCATIONS_INDEX.md (Implementation Reference)
**Best for:** Finding specific code and making targeted fixes
- All routes with error handling details
- Key error functions and their behaviors
- All error message locations
- HTTP status code usage with line numbers
- Async operation state storage structures
- JavaScript error handling patterns

**Use this** when implementing fixes or making code changes.

## Key Findings Summary

### 3 Main Issues
1. **Inconsistent error response formats** - clients must handle multiple JSON structures
2. **Poor error messages** - lack context, don't specify which file/operation failed
3. **Minimal error logging** - only 8 LOGGER calls in 3280 lines, async errors never logged

### Error Response Format Inconsistency
The codebase uses 4 different error response formats:
- `{"error": "message"}` - File operations, stash
- `{"ok": false, "error": "message"}` - Abstract evaluation, updates
- `{..., "index_job": {"last_error": "..."}}` - Async status
- Ollama passthrough - Original Ollama format

### HTTP Status Code Issues
- **502** used for ANY Ollama failure (7+ places) - no distinction between transient/permanent
- **500** used for generic errors (8+ places) - too broad
- **Missing codes:** 429 (rate limit), 503 (service unavailable), 504 (timeout)

### Error Logging Gaps
- PDF indexing failures: caught but not logged
- PDF ask failures: caught but not logged
- File operations: caught but not logged
- Update checks: inconsistent logging
- Ollama errors through proxy: no logging

## Recommendations Priority

### Phase 1 (1-2 hours) - Quick Wins
1. Add error_code field to all responses
2. Add request IDs for tracing
3. Create ErrorCode enum
4. Improve 3 key error messages

### Phase 2 (½ day) - Standardization
5. Standardize error response format
6. Add LOGGER calls to critical paths
7. Add 429/503/504 status codes
8. Improve 5 more error messages

### Phase 3 (1-2 days) - Logging & Visibility
9. Implement structured logging
10. Improve async error visibility
11. Add health checks for dependencies

### Phase 4 (Ongoing) - Polish
12. Add user documentation
13. Implement retry logic
14. Add monitoring/alerting

## Most Critical Files to Fix

1. **web.py line 2852-2901** - PDF ask operation
   - Returns 502 for ALL exceptions
   - No logging
   - No context in error message

2. **web.py line 1550-1616** - PDF indexing worker
   - Errors only stored, never logged
   - User invisible until 15 second poll
   - No file-specific error reporting

3. **web.py line 1059-1133** - Update checking
   - Generic 502 for rate limits/auth/network
   - No retry-after headers
   - GitHub errors leaked through

4. **indexer.py line 534** - Embedding response parsing
   - "Unexpected embedding response" doesn't say what was received
   - No context about which embedding failed

## Implementation Priority

**Highest Impact, Lowest Effort:**
1. Add error codes to all endpoints (1 hour)
2. Add structured request IDs (1 hour)
3. Improve 5 error messages (1 hour)
4. Add LOGGER calls to indexing (2 hours)

**Medium Impact, Medium Effort:**
5. Standardize response format (4 hours)
6. Add 429/503/504 handling (3 hours)
7. Implement structured logging (3 hours)

**Lower Impact, Higher Effort:**
8. Async error visibility improvement (4 hours)
9. Health checks for dependencies (3 hours)
10. User-facing documentation (2 hours)

## Files to Modify

| File | Changes | Effort |
|------|---------|--------|
| web.py | Add error codes, logging, standardize format | 8 hours |
| indexer.py | Improve error messages, add context | 4 hours |
| app.js | Handle multiple error formats (can refactor after) | 2 hours |
| New: errors.py | Create ErrorCode enum, logging utilities | 2 hours |

## Test Scenarios Not Currently Covered

1. Ollama timeout vs permanent failure
2. PDF with corrupted pages (partial extraction)
3. Rate limiting from GitHub API
4. Large file upload timeout
5. Concurrent indexing attempts
6. Database lock contention
7. Permission errors on file operations
8. Missing OCR dependencies
9. Embedding model not installed
10. WebSocket disconnections (if implemented)

## Maturity Rating Comparison

| Category | Current | Target | Gap |
|----------|---------|--------|-----|
| Response Format | 2/5 | 5/5 | 3 |
| HTTP Status Codes | 3/5 | 5/5 | 2 |
| Error Messages | 2/5 | 4/5 | 2 |
| Error Logging | 1/5 | 5/5 | 4 |
| Error Recovery | 2/5 | 4/5 | 2 |
| Error Categorization | 1/5 | 5/5 | 4 |
| Async Visibility | 2/5 | 4/5 | 2 |
| **Overall** | **1.5/5** | **4.5/5** | **3** |

## How to Use These Documents

1. **Start:** Read ERROR_HANDLING_SUMMARY.md (5 min)
2. **Plan:** Read error_handling_analysis.md sections 8-10 (20 min)
3. **Implement:** Use ERROR_LOCATIONS_INDEX.md as reference (ongoing)
4. **Reference:** Section 10 of error_handling_analysis.md for code examples

## Questions to Ask When Adding New Features

- What errors could this operation encounter?
- What context is needed to debug this error?
- Should this be logged?
- What HTTP status code best represents this error?
- Is there a machine-readable error code for this?
- Should the user retry? How often?
- Is this a transient or permanent failure?
- What should the user do to recover?

---

Generated: June 2, 2026
Analysis of: ollama-librarian v0.x.x
Scope: web.py, indexer.py, app.js error handling
