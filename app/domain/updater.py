#!/usr/bin/env python
"""Auto-update via GitHub Releases: check, download and apply a new build.

Flow (frozen PyInstaller onefile build):
    1. check_for_update()   -> queries the latest GitHub release
    2. download_update()    -> downloads the new exe NEXT TO the installed one
                               (<exe>.download), so the swap stays on one volume
    3. apply_update()       -> Windows can't overwrite a running exe, but it can
                               rename it: <exe> -> <exe>.old, <exe>.download -> <exe>
    4. relaunch()           -> starts the new <exe> with a clean PyInstaller
                               environment, then the caller quits
    5. on next start, cleanup_leftovers() deletes <exe>.old
"""
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Callable, Optional

from packaging.version import parse as parse_version

from app import constants
from app.domain.logging import setup_logger

logger = setup_logger(constants.LOG_FILE)

GITHUB_API_LATEST_RELEASE = (
    f"https://api.github.com/repos/{constants.GITHUB_REPO}/releases/latest"
)
USER_AGENT = "TelegramToMQL-Updater"

# Passed to the relaunched exe: path of a leftover file to delete once the
# previous process has released it.
CLEANUP_FLAG = "--cleanup-update"
# Legacy flag used by versions <= 6.4.1, which launch the new exe from %TEMP%
# and ask it to copy itself over the installed exe.
FINISH_UPDATE_FLAG = "--finish-update"

OLD_SUFFIX = ".old"
DOWNLOAD_SUFFIX = ".download"
UPDATE_STATE_FILE = constants.APPDATA_DIR / "update_state.json"


@dataclass
class UpdateInfo:
    version: str
    download_url: str
    notes: str
    size: int = 0


def is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def _read_state() -> dict:
    try:
        with open(UPDATE_STATE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def _write_state(state: dict) -> None:
    try:
        with open(UPDATE_STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(state, f, indent=4)
    except OSError as exc:
        logger.warning(f"Could not write update state: {exc}")


def check_for_update() -> Optional[UpdateInfo]:
    """Queries the GitHub Releases API. Blocking: run outside the UI thread."""
    request = urllib.request.Request(
        GITHUB_API_LATEST_RELEASE,
        headers={"User-Agent": USER_AGENT, "Accept": "application/vnd.github+json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            data = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            logger.info("No GitHub release published yet")
        else:
            logger.warning(f"Update check failed: {exc}")
        return None
    except (urllib.error.URLError, TimeoutError, ValueError) as exc:
        logger.warning(f"Update check failed: {exc}")
        return None

    remote_version = data.get("tag_name", "").lstrip("vV")
    if not remote_version:
        return None

    try:
        if parse_version(remote_version) <= parse_version(constants.APP_VERSION):
            return None
    except Exception as exc:
        logger.warning(f"Invalid version comparison ({remote_version}): {exc}")
        return None

    # Guard against an update loop: if this release was already installed but
    # the exe it shipped reports a lower APP_VERSION than its tag, don't offer
    # it again and again.
    if _read_state().get("installed_tag") == remote_version:
        logger.warning(
            f"Release {remote_version} already installed but APP_VERSION is "
            f"{constants.APP_VERSION}: tag and APP_VERSION should match"
        )
        return None

    exe_asset = next(
        (a for a in data.get("assets", []) if a.get("name", "").lower().endswith(".exe")),
        None,
    )
    if not exe_asset:
        logger.warning("Latest release has no .exe asset")
        return None

    return UpdateInfo(
        version=remote_version,
        download_url=exe_asset["browser_download_url"],
        notes=(data.get("body") or "").strip(),
        size=int(exe_asset.get("size") or 0),
    )


def download_update(
    info: UpdateInfo,
    progress_callback: Optional[Callable[[int, int], None]] = None,
) -> str:
    """Downloads the new exe next to the running one and returns its path.

    Raises if the download is incomplete, so a corrupted exe never gets
    installed and relaunched. progress_callback(downloaded, total) is called
    from the worker thread.
    """
    target = sys.executable + DOWNLOAD_SUFFIX
    request = urllib.request.Request(info.download_url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=60) as response, open(target, "wb") as out:
            expected_size = int(response.headers.get("Content-Length") or info.size or 0)
            downloaded = 0
            while True:
                chunk = response.read(256 * 1024)
                if not chunk:
                    break
                out.write(chunk)
                downloaded += len(chunk)
                if progress_callback:
                    progress_callback(downloaded, expected_size)

        if expected_size and downloaded != expected_size:
            raise IOError(
                f"Incomplete download: got {downloaded} bytes, expected {expected_size}"
            )
    except PermissionError as exc:
        _remove_quietly(target)
        raise IOError(
            f"No write access to {os.path.dirname(target)}. Move the application "
            f"to a folder you own (e.g. Documents or Desktop) and retry."
        ) from exc
    except Exception:
        _remove_quietly(target)
        raise

    return target


def apply_update(downloaded_path: str, version: str) -> str:
    """Swaps the running exe with the downloaded one, returns the exe path.

    A running exe can be renamed (not overwritten) on Windows, so the current
    exe becomes <exe>.old and the download takes its name. Rolls back if the
    second rename fails.
    """
    current = sys.executable
    old = current + OLD_SUFFIX

    # A leftover from a previous update may still exist
    _remove_quietly(old)
    os.replace(current, old)
    try:
        os.replace(downloaded_path, current)
    except OSError:
        os.replace(old, current)
        raise

    _write_state({"installed_tag": version})
    logger.info(f"Update {version} installed to {current}")
    return current


def relaunch(exe_path: str, cleanup_path: Optional[str] = None) -> None:
    """Starts exe_path as a fresh, independent process.

    PYINSTALLER_RESET_ENVIRONMENT tells the onefile bootloader that this is
    a new application instance. Without it, the child inherits the _PYI_*
    variables of this process and reuses its _MEIxxxx extraction folder,
    which is deleted as soon as this process exits -> the new exe crashes.
    """
    env = {
        k: v for k, v in os.environ.items()
        if not k.startswith("_PYI_") and k != "_MEIPASS2"
    }
    env["PYINSTALLER_RESET_ENVIRONMENT"] = "1"

    args = [exe_path]
    if cleanup_path:
        args += [CLEANUP_FLAG, cleanup_path]

    subprocess.Popen(
        args,
        cwd=os.path.dirname(exe_path),
        env=env,
        creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP,
        close_fds=True,
    )


def _get_flag_value(argv, flag) -> Optional[str]:
    if flag in argv:
        idx = argv.index(flag)
        if idx + 1 < len(argv):
            return argv[idx + 1]
    return None


def get_pending_install_target(argv) -> Optional[str]:
    """Legacy flow: target path to self-install to, if argv carries the flag."""
    return _get_flag_value(argv, FINISH_UPDATE_FLAG)


def _remove_quietly(path: str) -> bool:
    try:
        if os.path.exists(path):
            os.remove(path)
        return True
    except OSError:
        return False


def _remove_with_retries(path: str, attempts: int = 30) -> None:
    for _ in range(attempts):
        if _remove_quietly(path):
            return
        time.sleep(1)
    logger.warning(f"Could not delete leftover update file {path}")


def cleanup_leftovers(argv) -> None:
    """Deletes files left by a previous update.

    Blocking (the previous process keeps its exe locked for a moment after
    exiting, hence the retries): run in a background executor.
    """
    if not is_frozen():
        return
    paths = [sys.executable + OLD_SUFFIX, sys.executable + DOWNLOAD_SUFFIX]
    extra = _get_flag_value(argv, CLEANUP_FLAG)
    if extra:
        paths.append(extra)
    for path in paths:
        if os.path.exists(path):
            _remove_with_retries(path)


def install_self_over(target_path: str) -> bool:
    """Legacy flow: copies the running exe (in %TEMP%) over target_path.

    Same rename trick as apply_update, so it works even if the old process
    still holds its exe. Returns True on success.
    """
    if not is_frozen():
        logger.warning("install_self_over ignored: not a frozen build")
        return False

    source = sys.executable
    if os.path.abspath(source) == os.path.abspath(target_path):
        return False

    import shutil

    staged = target_path + DOWNLOAD_SUFFIX
    old = target_path + OLD_SUFFIX
    for attempt in range(1, 31):
        try:
            shutil.copy2(source, staged)
            _remove_quietly(old)
            if os.path.exists(target_path):
                os.replace(target_path, old)
            os.replace(staged, target_path)
            logger.info(f"Update installed to {target_path}")
            return True
        except OSError as exc:
            logger.info(f"Install retry {attempt}/30 for {target_path}: {exc}")
            time.sleep(1)

    _remove_quietly(staged)
    logger.warning(f"Failed to install update to {target_path} after retries")
    return False
