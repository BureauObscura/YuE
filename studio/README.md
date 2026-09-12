# YuE Studio for Mac

A local music workspace with a native Mac window. Write lyrics and musical direction, keep alternate takes, import recordings, play audio, create or upload cover artwork, and export a recording package.

## Install from source

Requirements: macOS 13 or later, Python 3.10+ (3.12 preferred), Node.js 22.12+ for the build, and Apple's Xcode Command Line Tools. Install the command-line tools with `xcode-select --install` if needed. The validated build uses Apple silicon.

Clone this fork and build the app:

```sh
git clone https://github.com/BureauObscura/YuE.git
cd YuE
cd studio/web
npm ci
npm run build
cd ../..
python3.12 studio/macos/build_app.py
```

Copy **`studio/dist/YuE Studio.app`** to **`~/Applications`**, then double-click that installed copy. Create the Applications folder in your home directory if it does not exist. This repository contains the source and builder; downloading its ZIP does not include a prebuilt app. Keeping the app in Applications avoids unnecessary Documents-folder permission requests during Python startup. The built app uses your installed Python and does not require Node, a Terminal window, or the music model to open.

The app starts its own service on a free localhost port and stops that service and its music worker when you quit. The **YuE Studio** menu contains **Open Library Folder** and **Open Service Log**. Command-S saves a composition, Command-N starts another, and the Edit and View menus provide clipboard actions and zoom.

The browser fallback is **`studio/Launch YuE Studio.command`**. It uses built web assets and opens the default browser.

## What works before the model is installed

- Lyrics, section labels, title, artist, album, musical direction, and optional ABC score editing.
- Automatic local draft saving, a searchable library, and favorites.
- Import WAV, FLAC, MP3, and M4A recordings; import PNG, JPEG, and WebP covers.
- Playback, seeking, volume, repeat, and switching between takes. Format playback depends on the Mac WebKit decoder; original downloads remain available.
- ZIP exports with an unchanged original recording, cover image, frozen lyrics/request for the chosen take, and generation metadata when available.
- Optional FLUX.2 Pro artwork generation through your BFL account.

Imported recordings are identified as imports in exported metadata. The decorative record sleeve in an empty project is a placeholder, not generated cover art. There are no demo songs or fabricated generation results in the library.

## Connect the music engine

Open **Music engine** from the sidebar or settings button. Select the Python interpreter from your YuE environment, device, memory budget, and the locations or cached Hugging Face IDs for the model and decoder.

From the repository root, the upstream runtime can be installed separately:

```sh
python3.12 -m venv .venv
.venv/bin/python -m pip install .
```

Download the YuE2-3B and YuE2-Vae weights separately using the [upstream generation guide](../docs/generation.md) and [model resources](https://huggingface.co/m-a-p/YuE2-3B). Studio deliberately requires already-downloaded weights. Starting the interface or checking the engine never downloads them.

The documented generation configuration is Linux and a BF16-capable NVIDIA GPU with 24 GB VRAM. Apple GPU mode is experimental. The M2 Pro with 16 GB memory used to validate the interface has **not** been validated for full-song generation. A readiness check confirms dependencies, local model files, and device availability; it does not establish sound quality or memory fit. CPU inference is not enabled by Studio.

Generation creates a new take with a frozen request. Jobs run one at a time and can be cancelled. Stage labels reflect real worker progress. Interrupted jobs are marked as interrupted on restart rather than presented as complete. A saved score checkpoint can remain after a later failure; automatic stage-by-stage resume is not implemented.

## Use a GPU machine

The remote option opens a complete Studio workspace on the GPU machine. Its library and generation jobs stay on that machine; it is not automatically synchronized with the Mac library.

1. Build the interface there or copy `studio/web/dist`, and configure that machine's Python environment and cached models.
2. Start its service on loopback. Explicitly allow the port your Mac will forward:

   ```sh
   python3 studio/server/server.py --port 8766 --forwarded-port 8767 --no-open
   ```

3. On the Mac, open an SSH tunnel:

   ```sh
   ssh -N -L 8767:127.0.0.1:8766 user@gpu-host
   ```

4. In **Music engine → GPU machine**, save `http://127.0.0.1:8767`, then select **Open remote Studio**. In that workspace, configure the GPU machine's local engine.

The forwarded-port setting preserves exact localhost Host/Origin validation when the forwarded and destination ports differ. The service is not designed to be exposed directly to the public internet.

## Album artwork

Select **Create cover**, describe a visual direction, and enter a BFL API key. **Generate cover** submits one paid FLUX.2 Pro request for a 1024 × 1024 image. Only the visible artwork prompt is sent, without lyrics or audio. The key stays in memory and is not included in saved projects, logs, or exports. This release does not use reference-image editing or automatically generate art after each song.

Artwork runs independently of the music queue. An image failure leaves the music available. Provider submission is never retried automatically; if a network result is uncertain, inspect the BFL dashboard before another attempt.

Original audio files are never modified to add artwork. ZIP exports always include a separate cover image. If the Studio Python environment has `mutagen` installed, FLAC, MP3, and M4A exports with a PNG/JPEG cover can also include a separate tagged delivery copy. `metadata.json` states whether embedding succeeded. WAV and WebP-cover exports retain the separate image.

## Local storage

On Mac, projects live in `~/Library/Application Support/YuE Studio/`. The library stores drafts, immutable take inputs, recordings, model identities, artwork, and job receipts. Back up that directory to retain your work. Deleting a composition removes its saved takes and cover from this library, after confirmation. Closing a window quits the native app and stops local music jobs.

For tests or another workspace, use `--data-dir /absolute/path`. A process lock prevents two app instances from editing the same library simultaneously. Provider keys are excluded from persistent settings. No analytics, remote fonts, or external scripts are loaded by the interface.

## Rebuild after changes

From the repository root, with Node.js 22.12+ and Python 3.12 installed:

```sh
cd studio/web
npm ci
npm run build
cd ../..
python3.12 studio/macos/build_app.py
```

The Mac builder requires Apple's command-line development tools. It compiles the AppKit/WKWebView launcher, bundles the service, built web files, YuE source, and license notices, adds the original Dock icon, and signs the local app ad hoc. Startup uses the app's own bundled resources and Application Support directory; the source checkout is not needed to open it. This is a local build, not a notarized public distribution. See [Mac packaging details](macos/README.md).

To run the built interface in a browser:

```sh
python3.12 studio/server/server.py --port 8766
```

The default browser opens automatically. Use `--no-open` to suppress that. During frontend development, rebuild with `npm run build` and reload the service URL; the production service's strict origin policy is intentional.

## Validation

```sh
python3.12 -W error::ResourceWarning -m unittest discover -s studio/tests -p 'test_*.py'
cd studio/web && npm run build
```

The browser smoke test in `studio/tests/ui-smoke.cjs` uses an isolated library, a synthetic test tone, and a tiny test image. Set `PLAYWRIGHT_MODULE` to an installed Playwright module path when it is not available in the default Node module search path. Never run that script against a personal production library.

Backend tests cover persistence, immutable inputs, upload signatures, path containment, session/origin validation, byte ranges, queue cancellation, failed workers, export integrity, artwork provenance, and mocked provider handling. They do not download model weights or submit paid generations.

Full YuE song generation on Apple silicon and a live BFL image request remain unverified. See the [validation record](VALIDATION.md) for the tested platform and workflows. Code and model licensing remain subject to the repository's CC BY-NC 4.0 terms and third-party notices.
