"""Hash-checked additive installer. Standard library only. Preview unless --apply."""
import argparse
import hashlib
import json
import os
import shutil
import sys
import time
import uuid
from pathlib import Path

BASE = Path(__file__).resolve().parent


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None


def write_atomic(path, content):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + ".tcw-install-tmp")
    temp.write_bytes(content)
    os.replace(temp, path)


def ensure_stopped(tcw):
    if (tcw / "logs/session-token").exists():
        raise ValueError("Stop the TCW app with Stop.cmd first. A session-token file is still present; do not patch a running app.")
    if os.name == "nt" and os.environ.get("LOCALAPPDATA"):
        provider = Path(os.environ["LOCALAPPDATA"]) / "TCW/BexDogReadOnlyBridge/provider.json"
        if provider.exists():
            try:
                state = json.loads(provider.read_text(encoding="utf-8"))
                if time.time() * 1000 - state["heartbeat_ms"] < 15000:
                    raise ValueError("Close ArcGIS Pro before installing or rolling back this source patch.")
            except (json.JSONDecodeError, KeyError):
                pass
        # Catches the original unpatched ArcGIS process as well.
        import subprocess
        tasks = subprocess.run([str(Path(os.environ['SystemRoot']) / 'System32/tasklist.exe'),
                                '/FI', 'IMAGENAME eq ArcGISPro.exe', '/FO', 'CSV', '/NH'],
                               capture_output=True, text=True, check=True, timeout=10)
        if '"ArcGISPro.exe"' in tasks.stdout:
            raise ValueError("Close ArcGIS Pro before installing or rolling back the SDK source patch.")


def prepare(tcw, sdk):
    manifest = json.loads((BASE / "compatibility.json").read_text())
    ensure_stopped(tcw)
    if not (tcw / 'backend/app.py').is_file() or not (sdk / 'TCW_EngineeringAssistant.csproj').is_file():
        raise ValueError("Point --tcw-root at TCW-Knowledge and --bexdog-root at the directory containing the .csproj.")
    for relative, expected in manifest["sdk_dependencies"].items():
        if sha(sdk / relative) != expected:
            raise ValueError("BexDog source differs from the reviewed 1.5.3 attachment: " + relative + ". No files were changed.")
    changes = []
    for relative, expected in manifest["original_tcw_files"].items():
        target = tcw / relative
        if sha(target) != expected:
            raise ValueError("TCW source differs from the reviewed package: " + relative + ". No files were changed.")
    for relative, expected_payload in manifest["payload_files"].items():
        source = BASE / "app_patch" / relative
        if sha(source) != expected_payload:
            raise ValueError("Patch payload failed its checksum: " + relative)
        target = tcw / relative
        if relative not in manifest["original_tcw_files"] and target.exists():
            raise ValueError("An added file already exists; refusing to overwrite it: " + relative)
        changes.append((target, source.read_bytes()))
    for relative, expected_payload in manifest["sdk_patch_files"].items():
        source = BASE / "sdk" / relative
        if sha(source) != expected_payload or (sdk / relative).exists():
            raise ValueError("SDK patch conflict or payload checksum failure: " + relative)
        changes.append((sdk / relative, source.read_bytes()))
    view = sdk / 'EngineeringAssistantDockpane.xaml.cs'
    content = view.read_bytes()
    marker = b'            InitializeComponent();'
    if content.count(marker) != 1:
        raise ValueError("The BexDog constructor no longer matches the reviewed attachment.")
    newline = b'\r\n' if b'\r\n' in content else b'\n'
    content = content.replace(marker, marker + newline + b'            InitializeTcwReadOnlyBridge();', 1)
    changes.append((view, content))
    return changes


def rollback(receipt_path):
    receipt_path = receipt_path.resolve()
    receipt = json.loads(receipt_path.read_text())
    ensure_stopped(Path(receipt['tcw_root']))
    entries = receipt['files']
    # Validate everything before touching the first file; never overwrite later edits.
    for entry in entries:
        if sha(Path(entry['target'])) != entry['installed_sha256']:
            raise ValueError('A file changed after installation; rollback stopped: ' + entry['target'])
        if entry['backup'] and sha(receipt_path.parent / entry['backup']) != entry['original_sha256']:
            raise ValueError('Backup checksum mismatch: ' + entry['target'])
    for entry in reversed(entries):
        target = Path(entry['target'])
        if entry['backup']:
            write_atomic(target, (receipt_path.parent / entry['backup']).read_bytes())
        else:
            target.unlink()
    print('Source rollback completed. Rebuild/reinstall the original BexDog add-in before reopening ArcGIS Pro.')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--tcw-root', type=Path)
    parser.add_argument('--bexdog-root', type=Path)
    parser.add_argument('--apply', action='store_true')
    parser.add_argument('--rollback', type=Path)
    args = parser.parse_args()
    try:
        if args.rollback:
            rollback(args.rollback)
            return 0
        if not args.tcw_root or not args.bexdog_root:
            parser.error('--tcw-root and --bexdog-root are required')
        tcw, sdk = args.tcw_root.resolve(), args.bexdog_root.resolve()
        changes = prepare(tcw, sdk)
        for target, _ in changes:
            print(('REPLACE ' if target.exists() else 'ADD     ') + str(target))
        if not args.apply:
            print('Preflight passed. No files changed. Add --apply to install the reviewed source patch.')
            return 0
        backup_root = BASE / 'backups' / (time.strftime('%Y%m%d-%H%M%S') + '-' + uuid.uuid4().hex[:8])
        if backup_root.is_relative_to(tcw) or backup_root.is_relative_to(sdk):
            raise ValueError('Extract this add-on outside both projects so .cs backups cannot be compiled accidentally.')
        backup_root.mkdir(parents=True)
        entries = []
        for i, (target, content) in enumerate(changes):
            backup_name = str(i) + '.original' if target.exists() else None
            entry = {'target': str(target), 'backup': backup_name, 'original_sha256': sha(target),
                     'installed_sha256': hashlib.sha256(content).hexdigest()}
            if backup_name:
                shutil.copy2(target, backup_root / backup_name)
            entries.append(entry)
        receipt_path = backup_root / 'receipt.json'
        receipt_path.write_text(json.dumps({'tcw_root': str(tcw), 'sdk_root': str(sdk), 'files': entries}, indent=2))
        applied = []
        try:
            for (target, content), entry in zip(changes, entries):
                write_atomic(target, content)
                applied.append(entry)
        except Exception:
            for entry in reversed(applied):
                if entry['backup']:
                    write_atomic(Path(entry['target']), (backup_root / entry['backup']).read_bytes())
                else:
                    Path(entry['target']).unlink(missing_ok=True)
            raise
        print('Source patch installed. Your data, index and settings were not changed.')
        print('Rollback receipt: ' + str(receipt_path))
        print('NEXT: Build/install BexDog with your existing ArcGIS Pro SDK setup, then perform the live acceptance checks.')
        return 0
    except (OSError, ValueError) as exc:
        print('INSTALL STOPPED: ' + str(exc), file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
