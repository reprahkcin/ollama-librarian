# /api/pdf/ask Response Contract

This document defines the Phase 2 response contract for `POST /api/pdf/ask`.

## Goals

- Provide stable structured fields for frontend rendering and future APIs.
- Preserve backward compatibility for existing clients.
- Allow optional diagnostics (`debug_trace`) without changing default behavior.

## Request

Required fields:

- `query` (string)

Optional fields:

- `model` (string)
- `top_k` (integer)
- `include_paths` (string[])
- `exclude_paths` (string[])
- `debug_trace` (boolean, default `false`)

## Response (Success)

Top-level fields:

- `ok` (boolean)
- `answer` (string) - legacy field, retained for compatibility
- `answer_text` (string) - structured primary answer field
- `sources` (object[]) - legacy source list, retained for compatibility
- `citations` (object[]) - structured citation list
- `debug_trace` (object, optional; only when requested)

### `citations[]` shape

Each citation object contains:

- `citation_id` (string) - stable in-response identifier (e.g. `c1`, `c2`)
- `path` (string)
- `title` (string)
- `location` (number|string)
- `location_type` (string; e.g. `page` or `section`)
- `page` (number|null)
- `section` (number|null)
- `score` (number|null)

## Compatibility Rules

1. `answer` and `sources` remain present for legacy clients.
2. `answer_text` and `citations` are always present in successful responses.
3. If backend already returns `answer_text`/`citations`, they are preserved.
4. If backend returns only `answer`/`sources`, structured fields are synthesized.
5. `debug_trace` is omitted unless `debug_trace=true` is requested.

## Example Success Response

```json
{
  "ok": true,
  "answer": "Herbert Hoover was president during the onset of the Great Depression.",
  "answer_text": "Herbert Hoover was president during the onset of the Great Depression.",
  "sources": [
    {
      "path": "C:/library/us-history.pdf",
      "location": 12,
      "location_type": "page",
      "score": 2.31,
      "title": "US History"
    }
  ],
  "citations": [
    {
      "citation_id": "c1",
      "path": "C:/library/us-history.pdf",
      "title": "US History",
      "location": 12,
      "location_type": "page",
      "page": 12,
      "section": null,
      "score": 2.31
    }
  ]
}
```
