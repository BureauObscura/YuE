"""Isolated runtime probe and real YuE generation. Never downloads model weights."""
from __future__ import annotations

import argparse
import importlib.metadata
import importlib.util
import json
import os
from pathlib import Path
import signal
import sys
import time


DEPENDENCIES = ("torch", "transformers", "huggingface-hub", "safetensors", "tiktoken", "numpy", "soundfile", "accelerate")


def emit(**event):
    print(json.dumps(event, ensure_ascii=False), flush=True)


def model_folder(value):
    path = Path(value).expanduser()
    if path.is_dir():
        return path.resolve()
    cache = Path(os.environ.get("HF_HUB_CACHE", Path(os.environ.get("HF_HOME", Path.home() / ".cache/huggingface")) / "hub"))
    location = cache / ("models--" + value.replace("/", "--"))
    ref = location / "refs/main"
    if ref.is_file():
        revision = ref.read_text().strip()
        if revision and "/" not in revision and "\\" not in revision:
            snapshot = location / "snapshots" / revision
            if snapshot.is_dir():
                return snapshot
    return None


def cached_model(value, tokenizer=False):
    folder = model_folder(value)
    if folder is None or not (folder / "config.json").is_file():
        return None
    if tokenizer and not (folder / "qwen.tiktoken").is_file():
        return None
    try:
        config = json.loads((folder / "config.json").read_text())
        if config.get("model_type") != ("yue2" if tokenizer else "yue2_vae"):
            return None
        index = folder / "model.safetensors.index.json"
        if index.is_file():
            names = set(json.loads(index.read_text())["weight_map"].values())
            if not names or any(Path(name).name != name or not (folder / name).is_file() or
                                (folder / name).stat().st_size < 16 for name in names):
                return None
        elif not (folder / "model.safetensors").is_file() or (folder / "model.safetensors").stat().st_size < 16:
            return None
    except (OSError, ValueError, KeyError, TypeError):
        return None
    return folder


def check(settings):
    missing = []
    for name in DEPENDENCIES:
        try:
            importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            missing.append(name)
    runtime = not missing and importlib.util.find_spec("yue2") is not None
    model = cached_model(settings["model"], tokenizer=True)
    vae = cached_model(settings["vae"])
    cached = model is not None and vae is not None
    device = settings["device"]
    result = {"ready": False, "status": "setup_needed", "python_path": settings["python_path"],
              "runtime_available": runtime, "model_cached": cached, "device": device,
              "message": "", "missing_dependencies": missing}
    if not runtime:
        result["message"] = "Install the YuE runtime in a separate Python environment, then select its Python interpreter."
        if missing:
            result["message"] += " Missing: " + ", ".join(missing) + "."
        return result
    if not cached:
        result["message"] = "The music model and audio decoder must be fully downloaded first. Studio never downloads weights automatically. Choose their local folders or cached Hugging Face model IDs."
        return result
    try:
        import torch
        cuda = torch.cuda.is_available()
        mps = hasattr(torch.backends, "mps") and torch.backends.mps.is_available()
        device = ("cuda" if cuda else "mps" if mps else "cpu") if device == "auto" else device
        result["device"] = device
        if device == "cuda" and (not cuda or not torch.cuda.is_bf16_supported()):
            result.update(status="unsupported_device", message="The CUDA engine needs an available NVIDIA GPU with BF16 support.")
        elif device == "mps" and not mps:
            result.update(status="unsupported_device", message="Apple GPU acceleration is unavailable in this Python runtime.")
        elif device == "cpu":
            result.update(status="unsupported_device", message="CPU music inference is not enabled in Studio. Select a compatible NVIDIA GPU or try the experimental Apple GPU engine.")
        else:
            message = "Model files and runtime found. A real generation is still needed to validate this machine."
            if device == "mps":
                message = "Experimental Apple GPU engine configured. Full-song generation and memory use are unverified on this Mac; generation can fail if the model exceeds available memory."
            result.update(ready=True, status="experimental" if device == "mps" else "ready", message=message)
    except Exception as exc:
        result.update(status="runtime_error", message="The selected Python runtime could not initialize PyTorch: " + str(exc)[:500])
    return result


def run(settings, request, output):
    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ["TRANSFORMERS_OFFLINE"] = "1"
    report = check(settings)
    if not report["ready"]:
        raise RuntimeError(report["message"])
    # All imports of model code occur only in this explicitly started worker.
    from yue2.pipeline import YuE2Pipeline, SongResult
    from yue2.protocol import SongRequest
    from yue2.storage import identity
    cancelled = False

    def stop(*_):
        nonlocal cancelled
        cancelled = True
        raise InterruptedError("Generation cancelled.")

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    request = SongRequest(**request)
    output = Path(output)
    if output.exists() and any(output.iterdir()):
        raise FileExistsError("Generation requires a new, empty artifact directory.")
    output.mkdir(parents=True, exist_ok=True)
    emit(stage="Loading model and verifying weights")
    started = time.perf_counter()
    pipe = YuE2Pipeline.from_pretrained(str(cached_model(settings["model"], tokenizer=True)),
                                      vae=str(cached_model(settings["vae"])),
                                      local_files_only=True, device=report["device"],
                                      memory_budget_gib=settings["memory_budget_gib"], progress=False)
    try:
        cfg = pipe.effective_config(request)
        ident = identity({"request": request.to_dict(), "config": cfg, "weights": pipe.weights})
        emit(stage="Planning score")
        plan = pipe.plan(request=request, cancelled=lambda: cancelled)
        # A checkpoint remains available after later-stage failure, separate from completed artifacts.
        plan.save(output.parent / "score-checkpoint")
        emit(stage="Generating song")
        semantic = pipe.generate_semantic(plan, cancelled=lambda: cancelled)
        emit(stage="Synthesizing audio")
        nar_started = time.perf_counter()
        latents = pipe.synthesize(semantic, cancelled=lambda: cancelled)
        nar_seconds = time.perf_counter() - nar_started
        emit(stage="Decoding audio")
        decode_started = time.perf_counter()
        audio = pipe.decode(latents)
        timing = {"abc": plan.timing, "semantic": semantic.timing, "nar_seconds": nar_seconds,
                  "vae_seconds": time.perf_counter() - decode_started, "load": dict(pipe.load_timing),
                  "e2e_seconds": time.perf_counter() - started}
        result = SongResult(audio, 48000, semantic, latents, cfg, pipe.weights, timing, ident)
        emit(stage="Saving original recording")
        receipt = result.save_artifacts(output)
        emit(status="complete", duration=receipt["audio_seconds"], truncated=any(receipt["truncated"].values()))
    finally:
        pipe.close()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--settings", required=True)
    parser.add_argument("--request")
    parser.add_argument("--output")
    args = parser.parse_args()
    settings = json.loads(args.settings) if args.check else json.loads(Path(args.settings).read_text())
    try:
        if args.check:
            emit(**check(settings))
        else:
            run(settings, json.loads(Path(args.request).read_text()), args.output)
        return 0
    except InterruptedError:
        emit(status="cancelled", error="Generation cancelled.")
        return 130
    except Exception as exc:
        emit(status="failed", error=f"{type(exc).__name__}: {exc}"[:2000])
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
