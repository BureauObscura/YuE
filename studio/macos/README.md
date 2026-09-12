# YuE Studio for Mac

The native app wraps the local Studio interface in an AppKit window with WebKit. It launches its own Python service on an available `127.0.0.1` port, waits until the service responds, and opens the bundled interface. It does not require a development server or an internet connection to manage a local library.

## Open the app

First build the app using the [source installation guide](../README.md#install-from-source). The source ZIP does not include `studio/dist` or a prebuilt app.

Copy `studio/dist/YuE Studio.app` into your Applications folder, then double-click the installed app. Running the app directly from a protected Documents folder can trigger a macOS folder-access request for its Python service. No broad privacy permission is needed for an ordinary Applications installation. Python 3.10 or newer must already be installed; Python 3.12 is preferred. The app checks common Homebrew and python.org installation paths, then the inherited `PATH`. It shows a setup message if Python is missing. It never installs Python, dependencies, or model weights automatically.

The locally built app is ad-hoc signed for use on the Mac where you build it. A public installer release would need Developer ID signing and notarization for standard Gatekeeper approval. A Mac receiving an unsigned or unnotarized downloaded copy may show a Gatekeeper warning.

Your library is stored separately from the app:

```text
~/Library/Application Support/YuE Studio
```

The app menu includes **Open Library Folder** and **Open Service Log**. Each launch writes a separate log in the library's `Logs` folder. Closing the window or choosing **Quit YuE Studio** stops the app's own local service. The service stops its own active generation worker. Quit can interrupt an active generation, so finish or cancel it first when possible. Exported files and saved library entries remain on disk.

Music generation requires a separately configured YuE runtime. The app includes the YuE Python source and its license notices, but contains neither music models nor GPU dependencies. Choose the runtime interpreter and cached model folders in Studio settings. The installed app is independent of the original Git checkout and uses Application Support as its working directory. Moving the app itself does not change the library location. Apple GPU inference remains experimental and is distinct from the Mac interface working.

## Build

Build the web interface first, then package it:

```bash
cd studio/web
npm ci
npm run build
cd ../..
python3 studio/macos/build_app.py
```

Requirements: macOS 13+, Python 3.10+, Node.js 22.12+, and Xcode or Xcode Command Line Tools with a working Swift compiler. Node is needed only to build the web interface, not to open the packaged app. The builder copies all service files and the compiled interface into the app, compiles the native wrapper, and verifies the local code signature. It does not modify the source YuE code.

The default build targets the Mac running the builder. Use `--architecture x86_64` for an Intel build or `--architecture arm64` for Apple silicon. These are separate builds, not a universal binary.

```bash
python3 studio/macos/build_app.py --output '/path/with spaces/YuE Studio.app'
```

Optional `--source-repository /path/to/YuE` chooses which YuE source and license notices to bundle. This build path is not recorded in the installed app. A failed build leaves the existing app in place. The builder replaces an existing app only if its bundle identifier matches YuE Studio.

The bundled Dock icon matches the interface mark. Its vector source is `icon.swift`; `--regenerate-icon` rebuilds it using AppKit and Apple's `iconutil`.

## Browser fallback

Double-click `studio/Launch YuE Studio.command` to open the same interface in your default browser. Keep its Terminal window open while using Studio. Press Control-C to stop its service. This fallback requires the repository's `studio/web/dist` and `studio/server` files.

## Native behavior

- Standard Mac window controls, a light title bar matching the interface, and a minimum 1000 × 720 window.
- Edit menu with Undo, Redo, Cut, Copy, Paste, and Select All.
- Command-R to reload; Command-plus/minus to zoom; Command-0 for actual size.
- System file picker for audio and cover imports.
- System save dialog for exports. Downloads finish in a temporary file before replacing the selected destination, preserving an existing file if download fails.
- External links open in the default browser. The app window stays on its own local service.
- No persistent WebKit browsing storage. The service owns persistent library data.

## Validation scope

Successful compilation and packaging establish that the native launcher builds. Full validation also requires opening the app, checking the interface, testing native import/export dialogs, and confirming that quitting removes its local service process. Music generation and artwork provider calls require their own runtime or credentials and must be tested separately.
