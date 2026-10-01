# Bureau Obscura Audio Fabricator 1.0.0

> **Non-commercial art project.** This public release is an experimental art
> tool, not a commercial product or service. YuE2 model weights are included
> under CC BY-NC 4.0 and the authors' additional individual-creator permission.
> The weights are not relicensed, sold, or offered for company commercial use.

Bureau Obscura Audio Fabricator combines two fully local audio workspaces in a
single Windows application:

- **Music** — the Bureau Obscura edition of YuE Studio, powered by YuE2-3B and
  YuE2-Vae.
- **Sound** — effects, atmospheres, and environmental audio powered by Stable
  Audio 3 Small SFX.

The release includes the application, pinned source snapshots, Windows Python
runtimes, and model files. It does not contain generated takes, prompts,
credentials, browser profiles, or any other personal library data.

## Install the offline bundle

1. Download `Bureau-Obscura-Audio-Fabricator-1.0.0-Bootstrap.zip`,
   `SHA256SUMS.txt`, and **every** numbered `.7z` part.
2. Put them in one folder and extract the bootstrap ZIP there.
3. Run `Extract-Bundle.ps1`; it verifies each part before extraction.
4. Open `Bureau Obscura Audio Fabricator.exe` in the extracted application
   folder.

Microsoft Edge is used for the dedicated desktop window. YuE music generation
requires a compatible NVIDIA GPU. Stable Audio Small SFX uses its bundled
CPU-optimized TFLite/XNNPACK runtime.

## Model and third-party terms

- YuE2 model weights: CC BY-NC 4.0 plus the bundled individual-creator
  permission. Companies need a separate commercial weight license from the
  YuE2 authors.
- Stable Audio 3 model files: Stability AI Community License and current
  Acceptable Use Policy. **Powered by Stability AI.**
- T5Gemma encoder: Gemma Terms of Use and prohibited-use policy.
- YuE2 application code: Apache 2.0.
- Stable Audio 3 runtime code: MIT.

The complete terms, required notices, exact upstream revisions, and major-file
SHA-256 hashes are inside the extracted bundle and in this repository under
`packaging/windows/`.

## Privacy and lifecycle

Both services bind only to `127.0.0.1`. The launcher owns their Windows process
tree and terminates both engines when the application window closes. Music
library data is stored under `%LOCALAPPDATA%\YuE Studio` and is never bundled
or uploaded by the packaging process.
