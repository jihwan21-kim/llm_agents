"""Resolve user-maintained local recording folders for the browser inbox.

Only relative paths under this repository's recordings/ tree are accepted.
The JSON manifest itself contains no replay data, secrets, or machine paths.
"""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent
CONFIG = ROOT / "mailbox-recordings.json"


def load_recording_directories(config_path=CONFIG, root=ROOT):
    """Return one latest bundle directory per configured relative folder.

    A configured path may directly contain bundle.json or may contain multiple
    dated run directories, of which the newest is used. Missing entries are
    reported and skipped so one unfinished recording cannot hide the others.
    """
    root = Path(root).resolve(strict=True)
    path = Path(config_path)
    if not path.is_absolute():
        path = root / path
    if path.is_symlink():
        raise ValueError("Mailbox configuration cannot be a symlink")
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or set(data) != {"recordings"}:
        raise ValueError("Mailbox config must contain only a 'recordings' array")
    values = data["recordings"]
    if not isinstance(values, list) or len(values) > 30:
        raise ValueError("Mailbox recordings must be an array of at most 30 folders")
    recordings_root = root / "recordings"
    selected, seen = [], set()
    for entry in values:
        if not isinstance(entry, str) or len(entry) > 260:
            raise ValueError("Each mailbox recording must be a folder path string")
        # Git-tracked paths must be portable; absolute or parent-relative paths
        # could otherwise expose arbitrary local files through the proxy.
        parts = entry.replace("\\", "/").split("/")
        if (len(parts) < 2 or parts[0] != "recordings"
                or any(p in {"", ".", ".."} or ":" in p for p in parts)):
            raise ValueError(f"Invalid local recordings path: {entry!r}")
        base = root.joinpath(*parts)
        if not base.resolve().is_relative_to(recordings_root.resolve()):
            raise ValueError(f"Recordings path escapes recordings/: {entry!r}")
        if not base.is_dir():
            print(f"Mailbox recording skipped (folder absent): {entry}", flush=True)
            continue
        direct = base / "bundle.json"
        if direct.is_file():
            candidates = [base]
        else:
            candidates = [
                child for child in base.iterdir()
                if child.is_dir() and not child.is_symlink()
                and (child / "bundle.json").is_file()
                and child.resolve().is_relative_to(recordings_root.resolve())
            ]
        if not candidates:
            print(f"Mailbox recording skipped (no bundle.json): {entry}", flush=True)
            continue
        folder = max(candidates, key=lambda p: (p.stat().st_mtime, p.name))
        resolved = folder.resolve(strict=True)
        if resolved not in seen:
            selected.append(resolved)
            seen.add(resolved)
    return selected
