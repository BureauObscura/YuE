"""One explicitly requested BFL cover generation, with no persisted credentials.

API contract verified 2026-09-11 against primary BFL documentation:
https://docs.bfl.ai/api-reference/models/generate-or-edit-an-image-with-flux2-%5Bpro%5D
https://docs.bfl.ai/api-reference/utility/get-result
https://docs.bfl.ai/api_integration/integration_guidelines

The stable FLUX.2 Pro snapshot produces a square PNG. The returned polling URL
is used as documented. Delivery URLs expire after ten minutes, so the caller
receives downloaded bytes and must save them promptly. Never persist provider
responses, signed URLs, or the API key. No automatic submission retries: a lost
response may still correspond to a charged generation.
"""

from __future__ import annotations

import hashlib
import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone


MODEL = "flux-2-pro"
API_URL = "https://api.bfl.ai/v1/" + MODEL
MAX_PROMPT_CHARS = 6000
MAX_IMAGE_BYTES = 12 * 1024 * 1024
MAX_JSON_BYTES = 256 * 1024
TOTAL_TIMEOUT_SECONDS = 180
SOCKET_TIMEOUT_SECONDS = 15
POLL_INTERVAL_SECONDS = 1


class ArtworkError(Exception):
    """Safe message suitable for showing to the user; no provider payload."""


class ArtworkCancelled(ArtworkError):
    """Stops waiting locally; a submitted provider job may still incur cost."""


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        # A redirect must never forward an API key or reach another host.
        raise ArtworkError("BFL returned an unexpected redirect. No request was retried.")


def _validate_url(url, *, delivery=False):
    message = "BFL returned an untrusted image URL." if delivery else "BFL returned an untrusted polling URL."
    if not isinstance(url, str) or len(url) > 8192 or any(ord(c) < 33 for c in url):
        raise ArtworkError(message)
    try:
        parsed = urllib.parse.urlsplit(url)
        host = parsed.hostname or ""
        if (parsed.scheme != "https" or parsed.username is not None
                or parsed.password is not None or parsed.port not in (None, 443)
                or parsed.fragment):
            raise ValueError
    except ValueError:
        raise ArtworkError(message) from None
    # BFL documents variable regional delivery.*.bfl.ai hosts. Keep API keys
    # restricted to API hosts, and never send them on an image download.
    pattern = r"delivery\.[a-z0-9-]+(?:\.[a-z0-9-]+)*\.bfl\.ai" if delivery else r"api(?:\.[a-z0-9-]+)*\.bfl\.ai"
    if not re.fullmatch(pattern, host):
        raise ArtworkError(message)
    if not delivery and parsed.path != "/v1/get_result":
        raise ArtworkError(message)
    return url


def _check_pending(cancelled, deadline):
    stopped = cancelled() if callable(cancelled) else cancelled is not None and cancelled.is_set()
    if stopped:
        raise ArtworkCancelled("Stopped waiting for artwork. A submitted BFL job may still finish and incur a charge.")
    if time.monotonic() >= deadline:
        raise ArtworkError("Artwork timed out. Check your BFL dashboard before starting another generation; no request was retried.")


def _http_error_message(code):
    if code in (401, 403):
        return "BFL rejected the API key. Check the key and its permissions."
    if code == 402:
        return "BFL needs an available credit balance to generate artwork."
    if code == 429:
        return "BFL is limiting requests. Wait before trying again; no request was retried."
    if code == 422:
        return "BFL could not accept this artwork request. Review the prompt and try again."
    return "BFL could not complete the artwork request. Check your BFL dashboard before starting another generation."


def _request_bytes(url, *, api_key=None, payload=None, limit, deadline, cancelled):
    _check_pending(cancelled, deadline)
    headers = {"Accept": "application/json" if api_key else "image/png,image/jpeg,image/webp", "User-Agent": "YuE-Studio/1.0"}
    if api_key:
        headers["x-key"] = api_key
    body = None
    if payload is not None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(url, data=body, headers=headers)
    # Do not read environment proxy settings, which could route credentials
    # through an unrelated proxy. HTTPS retains normal certificate validation.
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), _NoRedirect())
    try:
        with opener.open(request, timeout=min(SOCKET_TIMEOUT_SECONDS, max(0.1, deadline - time.monotonic()))) as response:
            length = response.headers.get("Content-Length")
            if length is not None:
                try:
                    too_large = int(length) > limit or int(length) < 0
                except ValueError:
                    raise ArtworkError("BFL returned an invalid response size.") from None
                if too_large:
                    raise ArtworkError("BFL returned a response larger than the studio allows.")
            chunks, size = [], 0
            while True:
                _check_pending(cancelled, deadline)
                # One socket read per loop: read(n) could keep waiting for a
                # slowly trickling body until n bytes fill, bypassing deadline
                # checks even while each individual socket read succeeds.
                chunk = response.read1(min(64 * 1024, limit - size + 1))
                if not chunk:
                    break
                size += len(chunk)
                if size > limit:
                    raise ArtworkError("BFL returned a response larger than the studio allows.")
                chunks.append(chunk)
            _check_pending(cancelled, deadline)
            return b"".join(chunks)
    except urllib.error.HTTPError as exc:
        # Never read, log, retain, or display provider error bodies/URLs.
        code = exc.code
        exc.close()
        raise ArtworkError(_http_error_message(code)) from None
    except (urllib.error.URLError, TimeoutError, OSError, ValueError):
        raise ArtworkError("Could not reach BFL or download its result. Check your BFL dashboard before starting another generation; no request was retried.") from None


def _request_json(url, *, api_key, payload=None, deadline, cancelled):
    raw = _request_bytes(url, api_key=api_key, payload=payload, limit=MAX_JSON_BYTES, deadline=deadline, cancelled=cancelled)
    try:
        result = json.loads(raw)
    except (ValueError, UnicodeError):
        raise ArtworkError("BFL returned an unreadable response. Check your BFL dashboard before generating again.") from None
    if not isinstance(result, dict):
        raise ArtworkError("BFL returned an unexpected response. Check your BFL dashboard before generating again.")
    return result


def image_mime(data):
    """Recognize accepted binary signatures rather than trusting MIME headers."""
    if not data or len(data) > MAX_IMAGE_BYTES:
        raise ArtworkError("Cover images must be no larger than 12 MiB.")
    if len(data) >= 33 and data.startswith(b"\x89PNG\r\n\x1a\n") and data[12:16] == b"IHDR":
        return "image/png"
    if len(data) >= 4 and data.startswith(b"\xff\xd8\xff") and data.endswith(b"\xff\xd9"):
        return "image/jpeg"
    if len(data) >= 20 and data[:4] == b"RIFF" and data[8:12] == b"WEBP" and data[12:16] in (b"VP8 ", b"VP8L", b"VP8X"):
        return "image/webp"
    raise ArtworkError("BFL did not return a supported PNG, JPEG, or WebP image.")


def generate_artwork(prompt, api_key, cancelled=None):
    """Return (image_bytes, MIME type, safe metadata) for one requested cover.

    ``cancelled`` may be a no-argument predicate or a threading.Event. This
    synchronous callable belongs in its own worker, never a song worker. The
    caller owns saving the result and reporting status. No credentials, URLs,
    logs, or files are written here.
    """
    if not isinstance(prompt, str) or not prompt.strip() or len(prompt) > MAX_PROMPT_CHARS:
        raise ArtworkError("Write an artwork prompt of 1 to 6,000 characters.")
    if not isinstance(api_key, str) or not api_key or len(api_key) > 512 or any(ord(c) < 33 or ord(c) > 126 for c in api_key):
        raise ArtworkError("Enter a valid BFL API key to generate artwork.")
    prompt = prompt.strip()
    deadline = time.monotonic() + TOTAL_TIMEOUT_SECONDS
    payload = {"prompt": prompt, "width": 1024, "height": 1024, "output_format": "png", "disable_pup": True}
    result = _request_json(API_URL, api_key=api_key, payload=payload, deadline=deadline, cancelled=cancelled)
    polling_url = _validate_url(result.get("polling_url"))
    request_id = result.get("id")
    if not isinstance(request_id, str) or not re.fullmatch(r"[a-zA-Z0-9_-]{1,128}", request_id) or api_key in request_id:
        raise ArtworkError("BFL returned an invalid job identifier. Check your BFL dashboard before generating again.")
    while True:
        _check_pending(cancelled, deadline)
        result = _request_json(polling_url, api_key=api_key, deadline=deadline, cancelled=cancelled)
        status = result.get("status")
        if status == "Ready":
            output = result.get("result")
            sample = output.get("sample") if isinstance(output, dict) else None
            sample_url = _validate_url(sample, delivery=True)
            image = _request_bytes(sample_url, limit=MAX_IMAGE_BYTES, deadline=deadline, cancelled=cancelled)
            mime = image_mime(image)
            metadata = {
                "provider": "Black Forest Labs", "model": MODEL, "request_id": request_id,
                "width": 1024, "height": 1024, "prompt": prompt, "prompt_upsampling": False,
                "mime": mime, "sha256": hashlib.sha256(image).hexdigest(),
                "created_at": datetime.now(timezone.utc).isoformat(),
            }
            return image, mime, metadata
        if status in ("Request Moderated", "Content Moderated"):
            raise ArtworkError("BFL declined this artwork request under its content policy. Revise the prompt before trying again.")
        if status in ("Error", "Failed", "Task not found"):
            raise ArtworkError("BFL could not finish this artwork job. Check your BFL dashboard before starting another generation.")
        if status != "Pending":
            raise ArtworkError("BFL returned an unknown job status. Check your BFL dashboard before starting another generation.")
        # Short slices keep cancellation responsive between network calls.
        pause_until = min(deadline, time.monotonic() + POLL_INTERVAL_SECONDS)
        while time.monotonic() < pause_until:
            _check_pending(cancelled, deadline)
            time.sleep(min(0.1, max(0, pause_until - time.monotonic())))
