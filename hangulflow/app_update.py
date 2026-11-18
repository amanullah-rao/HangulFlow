"""Optional app updates from the project's GitHub releases.

Once a day (with the word-list check) HangulFlow asks GitHub for the latest
release. If it is newer than the running version, the learner is told and can
install it with one click: the installer is downloaded to a temporary folder,
its SHA-256 is compared with the hash GitHub publishes for it, and only then is
it run (silently, so it reopens HangulFlow when done). Nothing about the learner
is sent.
"""

from __future__ import annotations

import hashlib
import json
import logging
import subprocess
import sys
import tempfile
import threading
import urllib.request
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path

from PySide6.QtCore import QObject, Signal

from . import __version__
from .repository import VocabRepository, from_iso, to_iso, utc_now
from .updater import TIMEOUT_SECONDS, describe_error

log = logging.getLogger(__name__)

RELEASE_URL = "https://api.github.com/repos/amanullah-rao/HangulFlow/releases/latest"
CHECK_EVERY = timedelta(days=1)
MAX_INSTALLER_BYTES = 200_000_000
# /SILENT shows only a progress bar; the installer's [Run] entry restarts the app.
INSTALLER_ARGS = ("/SILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/CLOSEAPPLICATIONS")


@dataclass(frozen=True)
class Release:
    version: str
    page_url: str
    installer_url: str = ""
    installer_name: str = ""
    sha256: str = ""  # lowercase hex, "" if GitHub gave none (then we only open the page)
    size: int = 0


def version_tuple(text: str) -> tuple[int, ...]:
    """'v0.10.2' -> (0, 10, 2); anything unreadable counts as 0."""
    parts = []
    for piece in text.strip().lstrip("vV").split("."):
        digits = "".join(ch for ch in piece if ch.isdigit())
        parts.append(int(digits) if digits else 0)
    return tuple(parts)


def is_newer(candidate: str, current: str = __version__) -> bool:
    return version_tuple(candidate) > version_tuple(current)


def parse_release(raw: bytes) -> Release:
    """Read GitHub's 'latest release' JSON. Raises ValueError if it is not usable."""
    data = json.loads(raw.decode("utf-8"))
    if not isinstance(data, dict) or not data.get("tag_name"):
        raise ValueError("not a GitHub release")
    release = Release(version=str(data["tag_name"]).lstrip("vV"), page_url=str(data.get("html_url", "")))
    for asset in data.get("assets") or []:
        name = str(asset.get("name", ""))
        if name.lower().startswith("hangulflow-setup") and name.lower().endswith(".exe"):
            digest = str(asset.get("digest") or "")
            sha = digest.split(":", 1)[1].lower() if digest.lower().startswith("sha256:") else ""
            return Release(
                version=release.version, page_url=release.page_url,
                installer_url=str(asset.get("browser_download_url", "")), installer_name=name,
                sha256=sha, size=int(asset.get("size") or 0),
            )
    return release


def fetch_latest(url: str = RELEASE_URL) -> Release:
    request = urllib.request.Request(
        url, headers={"User-Agent": f"HangulFlow/{__version__}", "Accept": "application/vnd.github+json"}
    )
    with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
        return parse_release(response.read(1_000_000))


def download_installer(release: Release, folder: Path) -> Path:
    """Download the installer and check its SHA-256. Raises ValueError on a mismatch."""
    if not (release.installer_url and release.sha256):
        raise ValueError("this release has no verifiable installer")
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / Path(release.installer_name).name
    digest = hashlib.sha256()
    total = 0
    request = urllib.request.Request(release.installer_url, headers={"User-Agent": f"HangulFlow/{__version__}"})
    with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS * 3) as response, target.open("wb") as out:
        while chunk := response.read(1 << 16):
            total += len(chunk)
            if total > MAX_INSTALLER_BYTES:
                raise ValueError("installer is too large")
            digest.update(chunk)
            out.write(chunk)
    if digest.hexdigest() != release.sha256:
        target.unlink(missing_ok=True)
        raise ValueError("the downloaded installer did not match its published SHA-256")
    return target


def can_self_install() -> bool:
    """Only the installed app (a PyInstaller build on Windows) can replace itself."""
    return sys.platform == "win32" and bool(getattr(sys, "frozen", False))


class AppUpdater(QObject):
    """Checks and downloads in a background thread; signals arrive on the GUI thread."""

    checked = Signal(object, str)      # Release if a newer one exists (else None), error text
    ready = Signal(str, str)           # installer path ("" on failure), error text
    _checked = Signal(object, str)
    _ready = Signal(str, str)

    def __init__(self, repo: VocabRepository, url: str = RELEASE_URL) -> None:
        super().__init__()
        self._repo = repo
        self._url = url
        self._busy = False
        self.available: Release | None = None
        self._checked.connect(self._on_checked)  # queued: emitted from the worker thread
        self._ready.connect(self._on_ready)

    @property
    def busy(self) -> bool:
        return self._busy

    def check(self, force: bool = False) -> bool:
        if self._busy:
            return False
        if not force:
            last = from_iso(self._repo.meta("last_app_check"))
            if last is not None and utc_now() - last < CHECK_EVERY:
                return False
        self._busy = True
        threading.Thread(target=self._check_work, name="app-update-check", daemon=True).start()
        return True

    def _check_work(self) -> None:
        try:
            self._checked.emit(fetch_latest(self._url), "")
        except Exception as exc:  # offline, rate limit, bad JSON ... all non-fatal
            log.info("App update check failed: %r", exc)
            self._checked.emit(None, describe_error(exc).replace("online word list", "update information"))

    def _on_checked(self, release: Release | None, error: str) -> None:
        self._busy = False
        if release is not None:
            self._repo.set_meta("last_app_check", to_iso(utc_now()))
            log.info("Latest release on GitHub: %s (running %s).", release.version, __version__)
        self.available = release if release is not None and is_newer(release.version) else None
        self.checked.emit(self.available, error)

    def download(self) -> bool:
        """Fetch the available installer in the background; `ready` reports the result."""
        if self._busy or self.available is None:
            return False
        self._busy = True
        release = self.available
        threading.Thread(target=self._download_work, args=(release,), name="app-update-download", daemon=True).start()
        return True

    def _download_work(self, release: Release) -> None:
        try:
            folder = Path(tempfile.gettempdir()) / "HangulFlow-update"
            self._ready.emit(str(download_installer(release, folder)), "")
        except Exception as exc:
            log.warning("App update download failed: %r", exc)
            text = str(exc) if isinstance(exc, ValueError) else describe_error(exc)
            self._ready.emit("", text.replace("online word list", "update"))

    def _on_ready(self, path: str, error: str) -> None:
        self._busy = False
        self.ready.emit(path, error)

    @staticmethod
    def launch_installer(path: str) -> None:
        """Start the verified installer detached; the caller then quits the app."""
        log.info("Starting installer %s", path)
        flags = getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        subprocess.Popen([path, *INSTALLER_ARGS], creationflags=flags, close_fds=True)
