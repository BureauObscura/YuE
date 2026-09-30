# Validation record

## Windows 11

Validated locally on September 30, 2026, on Windows 11 Home build 26200 with an NVIDIA GeForce RTX 5090 (31.82 GiB), Python 3.12.10, Node.js 24.19.0, and FFmpeg 9.0.2.

- YuE2 0.1.6 at upstream commit `18a07bb` is installed in `C:\Bureau\YuE\.venv` with PyTorch 2.10.0+cu130. CUDA 13.0, BF16 support, and compute capability 12.0 are detected.
- Official model revisions are `m-a-p/YuE2-3B@c044757a011169583f363168348ae380946efff8` and `m-a-p/YuE2-Vae@152733a19ad43aa67e367f9b5503ef8075bb5126`. Studio uses the fully local folders and offline generation mode.
- The official Windows PyTorch wheel does not compile the native Flash Attention operator. CUDA-graph backend selection now checks PyTorch's compiled-capability flag and selects cuDNN attention on this machine instead of failing at the first generated token.
- A real offline generation completed in 43.161 seconds. It produced a 59.4387-second, stereo, 48 kHz FLAC with SHA-256 `9f5025baed5221684e8e1e404f2d62a2be95e77330e532bfc42ea566bba68c8c`; symbolic and semantic streams both ended normally without truncation. This verifies the technical generation path, not artistic or sensory quality.
- A second real generation submitted through Studio's own HTTP queue completed all visible stages and produced a 71.6787-second, stereo, 48 kHz FLAC with SHA-256 `84dc00dad91768a16ba4dd8ff23b616917e497420305fdc13fc1c97e062b465e`. Its worker receipt records 42.245 seconds end to end, cuDNN CUDA graphs for both generation phases, and no truncation.
- Production React/TypeScript build passes with Vite 8.3.0. All 37 Python backend/security tests pass with ResourceWarnings treated as errors.
- The Microsoft Edge browser workflow passes: Windows labels and shortcuts, draft autosave, real imported-audio playback, cover upload, ZIP download, missing-runtime presentation, artwork submission disabled without credentials, search, favorites, persistence after reload, mobile layout overflow check, and no JavaScript page errors.
- `%LOCALAPPDATA%\YuE Studio` is selected as the default Windows library. A real default-path bootstrap reports the installed Python environment, both local models, and CUDA as ready.
- Start-menu and desktop shortcuts target the hidden `pythonw.exe` launcher. The launcher owns a loopback-only service on a free port and opens Studio in a dedicated Edge app window.

No live paid BFL request was performed. Browser artwork tests use a tiny local fixture, and the generation result was not assigned a listening score or other fabricated sensory observation.

## macOS

Validated locally on September 12, 2026, on Apple M2 Pro / 16 GB / macOS 26.5.

- Production React/TypeScript build passes with Vite 8.3.0.
- Dependency audit reports zero known vulnerabilities at build time.
- 36 Python tests pass with ResourceWarnings treated as errors.
- Browser workflow passes: draft autosave, real imported-audio playback, seeking metadata, cover upload, ZIP download, missing-runtime presentation, artwork submission disabled without credentials, search, favorites, persistence after reload, mobile layout overflow check, and no JavaScript page errors.
- ZIP inspection confirms unchanged source audio, standalone cover, and lyrics frozen at the selected take's recording time.
- Native Apple-silicon AppKit/WKWebView build compiles and passes strict local code-signature verification.
- Installed app in `~/Applications/YuE Studio.app` visibly opens the complete interface. Native audio file picker opens and cancels normally. Quitting stops the owned Python service; reopening starts a fresh local service and loads the interface successfully.
- Mac startup initially encountered Documents-folder privacy access because of the checkout-based Python import path. The final app bundles YuE source and licenses, uses Application Support as its working directory, and has no source-checkout dependency. The installed build starts without that access.

No full YuE inference, model-weight download, or live paid BFL call was performed. Provider tests use mocked HTTP responses. Browser audio tests use a synthetic tone and a test image in an isolated temporary library. Embedded-cover export depends on the optional Mutagen package and a supported format; the tested WAV package used a standalone cover.

The interface and its Mac packaging are validated on the platform above. Full-song generation on Apple silicon and provider account access remain separate runtime checks.
