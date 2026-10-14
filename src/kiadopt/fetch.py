from __future__ import annotations

import subprocess
import urllib.request

TIMEOUT = 30


def fetch(url: str) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": "kiadopt"})
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
            data: bytes = response.read()
            return data
    except OSError:
        # python.org builds on macOS often have no CA certificates; curl uses the system ones.
        return _curl(url)


def _curl(url: str) -> bytes:
    result = subprocess.run(
        [
            "curl",
            "--fail",
            "--silent",
            "--show-error",
            "--location",
            "--max-time",
            str(TIMEOUT),
            url,
        ],
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        message = result.stderr.decode(errors="replace").strip()
        raise OSError(message or f"curl exited with {result.returncode}")
    return result.stdout
