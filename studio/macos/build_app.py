#!/usr/bin/env python3
"""Build an ad-hoc signed, native macOS app from the local Studio assets.

This does not install packages, download models, or invoke music inference.
Run `npm run build` in studio/web before using this script.
"""
from __future__ import annotations

import argparse
from pathlib import Path
import platform
import plistlib
import shutil
import subprocess
import sys
import tempfile

HERE = Path(__file__).resolve().parent
STUDIO = HERE.parent
REPOSITORY = STUDIO.parent


def checked_run(arguments: list[str], **kwargs: object) -> None:
    subprocess.run(arguments, check=True, **kwargs)


def validate_replacement(output: Path) -> None:
    if output.is_symlink():
        raise RuntimeError(f"Refusing to replace an app symlink: {output}")
    if not output.exists():
        return
    if not output.is_dir():
        raise RuntimeError(f"Refusing to replace a non-directory app: {output}")
    try:
        previous = plistlib.loads((output / "Contents" / "Info.plist").read_bytes())
    except (OSError, plistlib.InvalidFileException) as error:
        raise RuntimeError(f"Refusing to replace an unrecognized app: {output}") from error
    if previous.get("CFBundleIdentifier") != "com.bureauobscura.yue-studio":
        raise RuntimeError(f"Refusing to replace a different app: {output}")


def build(output: Path, *, source_repository: Path, architecture: str, regenerate_icon: bool = False) -> Path:
    if sys.platform != "darwin":
        raise RuntimeError("Build YuE Studio.app on a Mac with the Xcode Command Line Tools installed.")
    if not shutil.which("xcrun"):
        raise RuntimeError("Xcode tools are missing. Run xcode-select --install, then retry.")
    web = STUDIO / "web" / "dist"
    server = STUDIO / "server"
    if not (web / "index.html").is_file():
        raise RuntimeError("Built interface not found. Run npm install and npm run build in studio/web first.")
    if not (server / "server.py").is_file():
        raise RuntimeError("studio/server/server.py is missing. Restore the Studio service files first.")
    source_repository = source_repository.expanduser().resolve()
    if not (source_repository / "src" / "yue2" / "__init__.py").is_file():
        raise RuntimeError("The YuE source package is missing from --source-repository/src/yue2.")
    required_notices = ("LICENSE", "MODEL_LICENSE", "THIRD_PARTY_NOTICES.md")
    if any(not (source_repository / name).is_file() for name in required_notices) or not (source_repository / "licenses").is_dir():
        raise RuntimeError("The source repository is missing required license notices.")
    if output.suffix != ".app":
        raise ValueError("--output must end in .app")
    output = output.expanduser().absolute()
    validate_replacement(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    # Build beside the final bundle; a failed compiler leaves the existing app intact.
    with tempfile.TemporaryDirectory(prefix=".yue-studio-build-", dir=output.parent) as work_path:
        work = Path(work_path)
        bundle = work / output.name
        contents = bundle / "Contents"
        resources = contents / "Resources"
        executables = contents / "MacOS"
        resources.mkdir(parents=True)
        executables.mkdir()
        checked_run([
            "xcrun", "swiftc", str(HERE / "main.swift"),
            "-o", str(executables / "YuEStudio"),
            "-framework", "AppKit", "-framework", "WebKit",
            "-target", f"{architecture}-apple-macos13.0",
            "-module-cache-path", str(work / "swift-cache"),
            "-O",
        ])
        if regenerate_icon or not (HERE / "Studio.icns").is_file():
            renderer = work / "render-icon"
            checked_run([
                "xcrun", "swiftc", str(HERE / "icon.swift"), "-o", str(renderer),
                "-framework", "AppKit", "-module-cache-path", str(work / "swift-cache"),
            ])
            iconset = work / "Studio.iconset"
            checked_run([str(renderer), str(iconset)])
            checked_run(["xcrun", "iconutil", "-c", "icns", str(iconset), "-o", str(resources / "Studio.icns")])
        else:
            shutil.copy2(HERE / "Studio.icns", resources / "Studio.icns")
        shutil.copytree(web, resources / "web")
        shutil.copytree(server, resources / "server", ignore=shutil.ignore_patterns("__pycache__", "*.pyc", ".DS_Store"))
        shutil.copytree(source_repository / "src" / "yue2", resources / "src" / "yue2",
                        ignore=shutil.ignore_patterns("__pycache__", "*.pyc", ".DS_Store"))
        shutil.copy2(HERE / "README.md", resources / "README.md")
        for name in required_notices:
            shutil.copy2(source_repository / name, resources / name)
        shutil.copytree(source_repository / "licenses", resources / "licenses")
        with (contents / "Info.plist").open("wb") as stream:
            plistlib.dump({
                "CFBundleName": "YuE Studio",
                "CFBundleDisplayName": "YuE Studio",
                "CFBundleIdentifier": "com.bureauobscura.yue-studio",
                "CFBundleExecutable": "YuEStudio",
                "CFBundleIconFile": "Studio.icns",
                "CFBundlePackageType": "APPL",
                "CFBundleShortVersionString": "1.0.0",
                "CFBundleVersion": "1",
                "CFBundleInfoDictionaryVersion": "6.0",
                "LSMinimumSystemVersion": "13.0",
                "NSHighResolutionCapable": True,
                "NSPrincipalClass": "NSApplication",
                "NSAppTransportSecurity": {"NSAllowsLocalNetworking": True},
                "NSHumanReadableCopyright": "YuE Studio; upstream notices are included in Resources/LICENSE.",
            }, stream)
        (contents / "PkgInfo").write_bytes(b"APPL????")
        # Local ad-hoc signing is suitable for a locally built app. Distribution needs
        # the owner's Developer ID signing and notarization, performed separately.
        checked_run(["codesign", "--force", "--sign", "-", str(bundle)])
        checked_run(["codesign", "--verify", "--deep", "--strict", str(bundle)])
        validate_replacement(output)
        backup = work / "previous.app"
        if output.exists():
            output.rename(backup)
        try:
            bundle.rename(output)
        except OSError:
            if backup.exists():
                backup.rename(output)
            raise
    return output


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=STUDIO / "dist" / "YuE Studio.app")
    parser.add_argument("--source-repository", type=Path, default=REPOSITORY,
                        help="YuE source and licenses to bundle; no models or repository path are stored in the app.")
    parser.add_argument("--architecture", choices=("arm64", "x86_64"), default=platform.machine(),
                        help="Build for Apple silicon (arm64) or Intel (x86_64). Defaults to this Mac.")
    parser.add_argument("--regenerate-icon", action="store_true", help="Re-render the included Dock icon from icon.swift.")
    args = parser.parse_args()
    try:
        result = build(args.output, source_repository=args.source_repository, architecture=args.architecture,
                       regenerate_icon=args.regenerate_icon)
    except (RuntimeError, ValueError, OSError, subprocess.CalledProcessError) as error:
        print(f"Build failed: {error}", file=sys.stderr)
        return 1
    print(f"Built {result}")
    print("Copy this app to Applications, then open it. Python 3.10+ is required separately.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
