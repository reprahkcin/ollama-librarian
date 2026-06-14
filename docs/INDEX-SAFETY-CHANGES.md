# Index Safety Changes (2026-06-13)

## Summary

Implemented comprehensive safety measures to prevent accidental index deletions:

1. **Auto-prune DISABLED by default** - The `--prune` flag is now opt-in
2. **Database lives with documents** - Index stored inside source directory
3. **Path mismatch protection** - Safety check refuses to prune if paths don't match

## What Changed

### 1. Prune Behavior (DISABLED by default)

**Before:**

- Every `/api/pdf/index` call ran with `--prune` flag
- This removed ANY indexed document not found in current run
- No way to disable this behavior

**After:**

- Prune is now **OFF by default**
- Only runs if you explicitly set: `OLLAMA_WEB_PDF_PRUNE_ON_INDEX=1`
- Safe for testing and development

**To enable pruning (if you need it):**

```bash
export OLLAMA_WEB_PDF_PRUNE_ON_INDEX=1
./scripts/librarian-start-macos.sh
```

### 2. Database Location (Now Inside Source Directory)

**Before:**

- Database: `~/Library/Application Support/ollama-librarian/pdf-rag.sqlite` (fixed)
- Source: `/Users/you/pdf_library` (changeable)
- **Problem:** Path mismatch could delete entire index

**After:**

- Database: `<source_path>/.ollama-librarian/pdf-rag.sqlite`
- Source: `<source_path>`
- **Benefit:** Index travels with documents, no path mismatch possible

**Custom database location (optional):**

```bash
export OLLAMA_WEB_PDF_INDEX_DB="/custom/path/to/index.db"
```

### 3. Path Mismatch Safety Check

**New behavior:**

- Before pruning, indexer verifies ALL indexed documents are under current source directory
- If ANY path mismatch detected, prune is **REFUSED** with error message
- Prevents accidental deletion of entire index

**Example error:**

```
[ERROR] SAFETY CHECK FAILED: 678 indexed documents are outside current
source directory '/tmp/test'. Refusing to prune to prevent data loss.
First mismatched path: /Users/you/pdf_library/document.pdf
```

## Migration Notes

### Existing Users

Your existing database at `~/Library/Application Support/ollama-librarian/pdf-rag.sqlite` will continue to work if:

- You set `OLLAMA_WEB_PDF_INDEX_DB` to point to it explicitly

**Or**, to migrate to new location:

1. Stop the app: `./scripts/librarian-stop-macos.sh`
2. Move database:
   ```bash
   mkdir -p ~/pdf_library/.ollama-librarian
   mv ~/Library/Application\ Support/ollama-librarian/pdf-rag.sqlite \
      ~/pdf_library/.ollama-librarian/
   ```
3. Start the app: `./scripts/librarian-start-macos.sh`

### New Users

No action needed - database will be created inside your source directory automatically.

## Testing

### Verify Safety Features Work

1. **Check prune is disabled:**

   ```bash
   # Should NOT include --prune in output
   grep -A 5 "index_args = " src/ollama_librarian/web.py
   ```

2. **Check database location:**

   ```bash
   # Start app
   ./scripts/librarian-start-macos.sh

   # Check where database is created
   ls -la ~/pdf_library/.ollama-librarian/pdf-rag.sqlite
   ```

3. **Test path mismatch protection:**

   ```bash
   # Set OLLAMA_WEB_PDF_PRUNE_ON_INDEX=1 temporarily
   export OLLAMA_WEB_PDF_PRUNE_ON_INDEX=1

   # Change source to different directory
   curl -X POST http://127.0.0.1:8088/api/pdf/source \
     -H 'Content-Type: application/json' \
     -d '{"source_path": "/tmp/test-library"}'

   # Try to index (should FAIL with safety error)
   curl -X POST http://127.0.0.1:8088/api/pdf/index

   # Check logs - should see SAFETY CHECK FAILED message
   ```

## Files Modified

### Code Changes

- **src/ollama_librarian/web.py**:
  - Added `pdf_prune_on_index: bool` to `WebConfig`
  - Added `OLLAMA_WEB_PDF_PRUNE_ON_INDEX` env var (default "0")
  - Added `get_pdf_index_db_path()` function
  - Modified `_index_worker()` to conditionally add `--prune`
  - Updated all `PDF_INDEX_DB` references to use `get_pdf_index_db_path()`

- **src/ollama_librarian/indexer.py**:
  - Added path mismatch safety check before prune logic
  - Prune now refuses to run if indexed docs are outside source directory

### Documentation Updates

- **docs/MANUAL-TEST-PLAN.md**:
  - Updated "Execution Rules" with index safety warnings
  - Added database location and prune behavior notes to Cycle 2 restart notice

## Environment Variables

### New Variables

| Variable                        | Default   | Description                                                 |
| ------------------------------- | --------- | ----------------------------------------------------------- |
| `OLLAMA_WEB_PDF_PRUNE_ON_INDEX` | `0` (OFF) | Set to `1` to enable automatic pruning of missing documents |

### Modified Variables

| Variable                  | Old Default                                                     | New Default                                              | Notes                      |
| ------------------------- | --------------------------------------------------------------- | -------------------------------------------------------- | -------------------------- |
| `OLLAMA_WEB_PDF_INDEX_DB` | `~/Library/Application Support/ollama-librarian/pdf-rag.sqlite` | Empty (uses `<source>/.ollama-librarian/pdf-rag.sqlite`) | Set explicitly to override |

## Recovery Instructions

If you accidentally deleted your index (before these changes):

1. **Check source files intact:**

   ```bash
   find ~/pdf_library -type f \( -name "*.pdf" -o -name "*.epub" \) | wc -l
   ```

2. **Re-index everything:**

   ```bash
   # Ensure prune is OFF (now default)
   unset OLLAMA_WEB_PDF_PRUNE_ON_INDEX

   # Start app
   ./scripts/librarian-start-macos.sh

   # Trigger full re-index
   curl -X POST http://127.0.0.1:8088/api/pdf/index

   # Monitor progress
   watch -n 5 'curl -sS http://127.0.0.1:8088/api/pdf/status | jq ".documents, .chunks"'
   ```

## Future Improvements

Potential enhancements to consider:

- [ ] Add `--dry-run` mode to show what would be pruned without actually deleting
- [ ] Add backup/snapshot of database before destructive operations
- [ ] Add UI warning before enabling prune mode
- [ ] Add prune statistics to `/api/pdf/status` endpoint
- [ ] Consider SQLite WAL mode for better concurrent access

## Questions?

If you encounter issues or have questions about these changes, please file an issue on GitHub.
