# Validation record

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
