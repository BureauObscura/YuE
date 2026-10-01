# Bureau Obscura Audio Fabricator — Windows release

This directory contains the reproducible Windows launcher and offline-bundle
tooling for the Bureau Obscura-branded YuE Studio + Stable Audio 3 Small SFX
desktop application.

The packaged layout is portable:

```text
Bureau Obscura Audio Fabricator/
  Bureau Obscura Audio Fabricator.exe
  engines/yue/
  engines/stable-audio-3/
  runtimes/yue-python/
  runtimes/stable-python/
  licenses/
```

The launcher starts both loopback-only services, waits for their health
checks, opens the application in a dedicated Microsoft Edge window, and owns
the complete process tree through a Windows Job Object. Closing the app window
shuts down both generation engines.

## Build

Run `build-offline-bundle.ps1` on Windows with the pinned YuE and Stable Audio
source trees and already-downloaded model files. It builds the web interface
and launcher, creates relocatable Python runtimes, copies only release files,
records exact model revisions and hashes, and performs portable-runtime import
checks.

Run `make-release-assets.ps1` afterward to create a small bootstrap ZIP plus
split 7-Zip volumes below GitHub's 2 GiB per-asset limit.

Generated builds, Python environments, models, browser profiles, user takes,
and credentials are excluded from Git. Generated music libraries remain under
`%LOCALAPPDATA%\YuE Studio` and are never included in a release.

## Licensing

Read `MODEL_TERMS.md` before distributing model bundles. In particular, YuE2
weights are non-commercial for companies unless the authors grant a separate
license. Source code and model weights intentionally retain separate terms.
