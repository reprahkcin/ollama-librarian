# Ollama Librarian v1.0.9

This release adds hardware profile detection with VRAM constraints for discrete GPU systems, improves indexing safety, enhances citation features, and includes performance optimizations and bug fixes.

## Highlights

- **Hardware Profile Detection**: Automatic VRAM detection via nvidia-smi on discrete GPU machines, constraining model recommendations to min(RAM budget, VRAM budget)
- **Index Safety**: Source map mode with citation persistence, path traversal security hardening in prune operations
- **Performance**: Cached hardware pressure policy to eliminate per-request subprocess overhead
- **Testing**: Comprehensive manual testing completed across macOS (Apple Silicon), Windows 10, and Linux Mint platforms

## New Features

### Hardware Profile Detection

- Added VRAM detection for discrete NVIDIA GPU systems via nvidia-smi
- Hardware profile now includes `gpu_vram_total_gb` field (null on integrated/unified memory systems)
- Model recommendation engine constrains budget to min(safe_ram_budget, gpu_vram_budget) on discrete GPUs
- Backward compatible: gracefully handles systems without nvidia-smi or with integrated graphics
- API endpoint `/api/system/profile` exposes complete hardware profile with VRAM information

### Source Map Mode and Citation Persistence

- Source map mode now returns relevancy explanations for each source
- Citation blocks persist in conversation history with scores, badges, and PDF links
- Generate Bibliography button creates properly formatted APA 7 citations
- Bibliography stash filtering separates bibliography entries from regular stashed responses

### Index Safety Improvements

- Prune guard now uses `os.path.commonpath()` for robust path traversal prevention
- Replaced unsafe `startswith()` check with canonical path comparison
- Added security regression test coverage for prune operations

## Performance Improvements

- **Hardware Pressure Caching**: Hardware pressure policy (safe mode determination) now cached to avoid spawning subprocesses on every request
- **Model Metadata Caching**: Ollama model metadata cached with configurable TTL (default 60s)
- **Status Display**: Optimized status text rendering and CSS alignment for better UI responsiveness

## Bug Fixes

- Fixed model version inconsistencies in setup guides (standardized to current model tags)
- Fixed model cache path test isolation to prevent cross-test contamination
- Fixed status text separator rendering in document processing panel
- Fixed template parity between src and scripts directories
- Added `*.egg-info/` to .gitignore for cleaner repository state
- Fixed Linux evidence block in manual test plan after hardware profile changes

## Testing

- Comprehensive manual test plan executed on three platforms:
  - macOS (Mac Mini, Apple Silicon) - unified memory, null VRAM
  - Windows 10 PC - discrete NVIDIA GPU, VRAM detection validated
  - Linux Mint - discrete NVIDIA GPU, VRAM detection validated
- Added test coverage for `/api/pdf/synthesize` endpoint
- All manual test sections (A-G) passed on all platforms
- Hardware profile correctly detects VRAM on discrete GPUs and null on unified memory

## API Changes

### New Fields

**GET /api/system/profile**

```json
{
  "gpu_vram_total_gb": 12.0, // null on integrated/unified memory
  "safe_budget_gb": 12.0, // min(ram_budget, vram_budget) on discrete GPU
  "recommended_model": "gemma4:12b",
  "hardware_profile": "discrete_gpu"
}
```

## Versioning

- `pyproject.toml`: `1.0.9`
- `scripts/VERSION`: `v1.0.9`
- `src/ollama_librarian/VERSION`: `v1.0.9`

## Platform Support

Tested and verified on:

- macOS (Apple Silicon) - M1/M2/M3 with unified memory
- Windows 10/11 - discrete NVIDIA GPU systems
- Linux Mint 22 - discrete NVIDIA GPU systems

## Migration Notes

No breaking changes. Version 1.0.9 is backward compatible with 1.0.8.

### For Discrete GPU Users

- VRAM detection is automatic via nvidia-smi
- Model recommendations will now respect VRAM constraints
- If nvidia-smi is not available, falls back to RAM-only budget (previous behavior)

### For Integrated/Unified Memory Users

- No behavioral changes
- `gpu_vram_total_gb` will report null (expected)
- RAM budget applies as in previous versions

## Known Issues

None identified during testing.

## Upgrade Instructions

### macOS

```bash
./scripts/librarian-stop-macos.sh
./scripts/librarian-update-macos.sh
./scripts/librarian-start-macos.sh
```

### Windows (PowerShell)

```powershell
.\scripts\librarian-stop-windows.ps1
.\scripts\librarian-update-windows.ps1
.\scripts\librarian-start-windows.ps1
```

### Linux

```bash
./scripts/librarian-stop-linux.sh
./scripts/librarian-update-linux.sh
./scripts/librarian-start-linux.sh
```

## Contributors

- Manual testing: macOS (Apple Silicon), Windows 10 PC, Linux Mint
- Cross-platform waterfall test validation
- Security review and path traversal hardening

## Related Documentation

- [MANUAL-TEST-PLAN.md](MANUAL-TEST-PLAN.md) - Comprehensive manual test procedures
- [MACOS-TEST-REPORT-v1.0.9.md](../MACOS-TEST-REPORT-v1.0.9.md) - macOS test evidence
- [hardware.py](../src/ollama_librarian/hardware.py) - Hardware detection implementation

## Commit History

Key commits in this release:

- `ad7289f` - feat(hardware): add VRAM detection to constrain model recommendations on discrete-GPU machines
- `69a1dfa` - feat: source map mode, citation persistence, and index safety
- `bae842b` - perf: cache hardware pressure policy to avoid per-request subprocess spawning
- `bc12bd2` - fix(security): replace startswith path check with os.path.commonpath in prune guard
- `8a5354b` - test(routes): add coverage for /api/pdf/synthesize endpoint

Full changelog: https://github.com/reprahkcin/ollama-librarian/compare/v1.0.8...v1.0.9
