# YuE Studio for Windows and Mac

A local music workspace with a dedicated Windows app window or a native Mac window. Write lyrics and musical direction, keep alternate takes, import recordings, play audio, create or upload cover artwork, and export a recording package.

## Install from source

Requirements: Python 3.12 and Node.js 22.12+ for a source build. Music generation additionally needs the YuE runtime, downloaded model weights, and a supported accelerator.

### Windows 11

Clone this fork, install the current runtime and official CUDA wheel, download the models, and build Studio:

```powershell
git clone https://github.com/BureauObscura/YuE.git
cd YuE
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install .
.\.venv\Scripts\python.exe -m pip install --force-reinstall --no-deps torch==2.10.0+cu130 --index-url https://download.pytorch.org/whl/cu130
.\.venv\Scripts\hf.exe download m-a-p/YuE2-3B --local-dir models\YuE2-3B
.\.venv\Scripts\hf.exe download m-a-p/YuE2-Vae --local-dir models\YuE2-Vae
cd studio\web
npm ci
npm run build
cd ..\..
powershell -ExecutionPolicy Bypass -File studio\windows\install_shortcut.ps1
```

Open **YuE Studio** from the Start menu or desktop. The shortcut starts the local service invisibly and opens a dedicated Microsoft Edge app window; closing that window stops the service and any local music worker it owns. `studio\Launch YuE Studio.cmd` is the visible-console fallback.

The CUDA command above matches YuE2 0.1.6 and the current CUDA 13.0 PyTorch wheel. Check the [official PyTorch selector](https://pytorch.org/get-started/locally/) before adapting it to a different machine.

### macOS

macOS 13 or later also requires Apple's Xcode Command Line Tools. Install those tools with `xcode-select --install`, then build the native wrapper:

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
- Playback, seeking, volume, repeat, and switching between takes. Format playback depends on the installed browser/WebKit decoder; original downloads remain available.
- ZIP exports with an unchanged original recording, cover image, frozen lyrics/request for the chosen take, and generation metadata when available.
- Optional FLUX.2 Pro artwork generation through your BFL account.

Imported recordings are identified as imports in exported metadata. The decorative record sleeve in an empty project is a placeholder, not generated cover art. There are no demo songs or fabricated generation results in the library.

## Instrumentals, duration, remix, and delivery

Open **Generation settings** on a composition to use the local arrangement controls:

- **Instrumental / no vocals** runs the supported symbolic two-stage workflow: Studio plans or accepts an ABC score, moves every sounding `Vocal` note into the instrumental voice, then renders the converted score with empty lyrics and explicit no-vocal direction. A score planning mode is required. This removes the written vocal part; it cannot prove that the rendered timbre contains no voice-like leakage, so listen to the result before delivery.
- **Approximate duration** offers Auto, 30, 60, 90, 120, and 180 seconds. A target sets the semantic codec window to 80–120 percent of the chosen time at 25 tokens per second and asks for a natural ending near the target. The model may end after the minimum or reach the maximum and truncate. This control is a target and cap, not an exact-duration edit.
- **Score-conditioned remix** rerenders a complete recording from an ABC score. A prior YuE take can supply its saved score; changing the style, lyrics, score, and remix direction creates a new take while the reference recording remains unchanged.
- **Extend an edited score** requires adding the continuation to the reference ABC in the Score tab, then renders that whole extended score as a new recording. YuE2 does not continue from an audio timestamp, preserve waveform regions, inpaint a section, or clone a singer.

Imported audio remains fully local, but raw audio by itself is not a YuE2 conditioning input. Covering or remixing an arbitrary recording first requires an audio-to-ABC transcription stage such as SheetSage2; that separate runtime and its models are not installed by Studio. Paste a reviewed ABC score before generating from an imported reference.

The selected take can be downloaded as the complete ZIP package, WAV, or MP3. Conversion runs through the installed local FFmpeg process and never uploads audio. Existing WAV/MP3 files are copied unchanged when their requested format already matches; other sources use 24-bit PCM WAV or 320 kbps MP3. The retained original recording is never modified. Generated packages also retain `studio-context.json` and, for instrumental runs, `instrumental-transfer.json` when present.

## Connect the music engine

Open **Music engine** from the sidebar or settings button. Select the Python interpreter from your YuE environment, device, memory budget, and the locations or cached Hugging Face IDs for the model and decoder.

From the repository root, install the upstream runtime separately. On Windows with an NVIDIA GPU, use the CUDA wheel shown in the Windows installation section. On macOS or Linux:

```sh
python3.12 -m venv .venv
.venv/bin/python -m pip install .
```

Download the YuE2-3B and YuE2-Vae weights separately using the [upstream generation guide](../docs/generation.md) and [model resources](https://huggingface.co/m-a-p/YuE2-3B). Studio deliberately requires already-downloaded weights. Starting the interface or checking the engine never downloads them.

Upstream documents Linux and a BF16-capable NVIDIA GPU with 24 GB VRAM. This fork also validates the native PyTorch path on Windows 11 with an RTX 5090. Apple GPU mode remains experimental. A readiness check confirms dependencies, local model files, and device availability; it does not establish sound quality or memory fit. CPU inference is not enabled by Studio.

Generation creates a new take with a frozen request. Jobs run one at a time and can be cancelled. Stage labels reflect real worker progress. Interrupted jobs are marked as interrupted on restart rather than presented as complete. A saved score checkpoint can remain after a later failure; automatic stage-by-stage resume is not implemented.

## Use a GPU machine

The remote option opens a complete Studio workspace on the GPU machine. Its library and generation jobs stay on that machine; it is not automatically synchronized with the local library.

1. Build the interface there or copy `studio/web/dist`, and configure that machine's Python environment and cached models.
2. Start its service on loopback. Explicitly allow the port your computer will forward:

   ```sh
   python3 studio/server/server.py --port 8766 --forwarded-port 8767 --no-open
   ```

3. On your local computer, open an SSH tunnel:

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

On Windows, projects live in `%LOCALAPPDATA%\YuE Studio\`. On Mac, they live in `~/Library/Application Support/YuE Studio/`. The library stores drafts, immutable take inputs, recordings, model identities, artwork, and job receipts. Back up that directory to retain your work. Deleting a composition removes its saved takes and cover from this library, after confirmation. Closing the installed app window stops local music jobs.

For tests or another workspace, use `--data-dir /absolute/path`. A process lock prevents two app instances from editing the same library simultaneously. Provider keys are excluded from persistent settings. No analytics, remote fonts, or external scripts are loaded by the interface.

## Rebuild after changes

From the repository root, with Node.js 22.12+ and Python 3.12 installed, rebuild the shared interface:

```powershell
cd studio\web
npm ci
npm run build
cd ..\..
powershell -ExecutionPolicy Bypass -File studio\windows\install_shortcut.ps1
```

For the native Mac bundle:

```sh
cd studio/web
npm ci
npm run build
cd ../..
python3.12 studio/macos/build_app.py
```

The Windows launcher uses the checked-out runtime and model folders. The Mac builder requires Apple's command-line development tools and creates a self-contained AppKit/WKWebView wrapper. See [Mac packaging details](macos/README.md).

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

Backend tests cover persistence, immutable inputs, upload signatures, path containment, session/origin validation, byte ranges, queue cancellation, failed workers, instrumental request freezing, approximate-duration bounds, score-reference guards, WAV/MP3 delivery, export integrity, artwork provenance, and mocked provider handling. They do not download model weights or submit paid generations.

Full YuE song generation on Apple silicon and a live BFL image request remain unverified. Windows runtime, CUDA, launcher, and browser workflow results are recorded in [VALIDATION.md](VALIDATION.md). YuE2 code, agent skill, and documentation are Apache 2.0. Model weights are CC BY-NC 4.0 with the repository's additional creator permission; companies should contact the authors for a commercial model-weight license. Third-party components retain their own notices.
