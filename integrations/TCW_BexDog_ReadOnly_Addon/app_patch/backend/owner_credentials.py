"""Owner-only cancellation credential; never exposed through the web UI."""
import csv
import hashlib
import os
import re
import subprocess
from pathlib import Path


def owner_token_path(root):
    root = Path(root).resolve()
    if os.name == "nt":
        key = hashlib.sha256(str(root).casefold().encode()).hexdigest()[:20]
        return Path(os.environ["LOCALAPPDATA"]) / "TCW" / "KnowledgeOwner" / (key + ".token")
    return root / "logs/gis-owner-token"


def write_owner_token(root, token):
    path = owner_token_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    if os.name == "nt":
        system32 = Path(os.environ["SystemRoot"]) / "System32"
        identity = subprocess.run([str(system32 / "whoami.exe"), "/user", "/fo", "csv", "/nh"],
                                  capture_output=True, text=True, check=True, timeout=10)
        row = next(csv.reader(identity.stdout.strip().splitlines()))
        sid = row[-1]
        if not re.fullmatch(r"S-1-(?:\d+-)+\d+", sid):
            raise RuntimeError("Could not establish the host owner's Windows SID.")
        # Protect the per-user directory before writing a secret to it. Do not
        # rely on chmod, which does not establish a Windows DACL.
        subprocess.run([str(system32 / "icacls.exe"), str(path.parent), "/reset"],
                       capture_output=True, text=True, check=True, timeout=10)
        subprocess.run([str(system32 / "icacls.exe"), str(path.parent), "/inheritance:r",
                        "/grant:r", "*" + sid + ":(OI)(CI)F", "*S-1-5-18:(OI)(CI)F"],
                       capture_output=True, text=True, check=True, timeout=10)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(token)
    return path
