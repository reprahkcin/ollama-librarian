# Third-Party Notices

This project includes or uses third-party software. This file provides attribution and license pointers to support compliance.

## Bundled/Vendored Assets

1. KaTeX

- Purpose: Offline math rendering assets used by the web UI.
- Source: https://github.com/KaTeX/KaTeX
- License: MIT
- Local license text: scripts/assets/katex/LICENSE
- Local asset path: scripts/assets/katex/

2. epub.js

- Purpose: In-app EPUB rendering for citation source links.
- Source: https://github.com/futurepress/epub.js
- License: BSD-2-Clause
- Local license text: scripts/assets/epubjs/LICENSE
- Local asset path: scripts/assets/epubjs/

3. JSZip

- Purpose: Runtime ZIP parser required by epub.js for EPUB archives.
- Source: https://github.com/Stuk/jszip
- License: MIT OR GPL-3.0
- Local license text: scripts/assets/jszip/LICENSE
- Local asset path: scripts/assets/jszip/

4. pako (included in bundled JSZip artifact)

- Purpose: Deflate/inflate support used internally by the bundled JSZip build.
- Source: https://github.com/nodeca/pako
- License: MIT
- Local license text: scripts/assets/jszip/PAKO_LICENSE
- Local asset path: scripts/assets/jszip/jszip.min.js

## Runtime Dependencies (Not Vendored Here)

1. Ollama

- Purpose: Local model runtime/API endpoint.
- Source: https://github.com/ollama/ollama
- License: See upstream repository license.
- Notes: Installed separately by user setup; not redistributed by this repository.

2. Python packages

- Purpose: Indexing/parsing dependencies installed from scripts/pdf-rag-requirements.txt
- Source and license: See each package's upstream metadata.
- Notes: Installed by users in their environment; not vendored in this repository.

## Models and Weights

1. Qwen and other Ollama-pulled models

- Distribution model: Pulled by users at runtime; not bundled in this repository.
- License responsibility: Users must review and comply with each model's license/terms from the source model page.
- Practical guidance: Confirm terms before commercial use, redistribution, or publishing derivative artifacts.

## Maintainer Checklist

When adding new third-party components:

1. Add attribution, source URL, and license to this file.
2. If files are vendored into this repository, include required license/notice text in-tree.
3. If only referenced at runtime, document that users install/pull them separately and must follow upstream terms.
4. Update README links if notice locations change.
