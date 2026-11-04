"""Verify installed Python sources against wheel RECORD and reviewed overlays."""

import argparse
import base64
import hashlib
from importlib.metadata import PackageNotFoundError, distribution
import json
from pathlib import Path, PurePosixPath
import re


def _valid_manifest(root, entries):
    if not isinstance(entries, dict):
        return False
    for name, digest in entries.items():
        if not isinstance(name, str) or "\\" in name:
            return False
        path = PurePosixPath(name)
        if path.is_absolute() or ".." in path.parts or path.suffix != ".py":
            return False
        if not isinstance(digest, str) or re.fullmatch(r"[0-9a-f]{64}", digest) is None:
            return False
        if not (root / name).resolve().is_relative_to(root):
            return False
    return True


def verify_sources(root, records, overlays):
    root = Path(root).resolve()
    if (
        not records
        or not _valid_manifest(root, records)
        or not _valid_manifest(root, overlays)
    ):
        return {"status": "blocked_invalid_source_manifest"}
    for path in root.rglob("*"):
        if path.is_symlink():
            return {"status": "blocked_invalid_source_manifest"}
    for name, digest in records.items():
        if name in overlays:
            continue
        path = root / name
        if not path.is_file():
            return {"status": "blocked_missing_recorded_source"}
        if hashlib.sha256(path.read_bytes()).hexdigest() != digest:
            return {"status": "blocked_recorded_source_mismatch"}
    for name, digest in overlays.items():
        path = root / name
        if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != digest:
            return {"status": "blocked_overlay_source_mismatch"}
    actual = {path.relative_to(root).as_posix() for path in root.rglob("*.py")}
    if actual - records.keys() - overlays.keys():
        return {"status": "blocked_undeclared_python_source"}
    return {
        "status": "pilot_source_integrity_verified",
        "recorded_python_files": len(records),
        "declared_overlays": len(overlays),
    }


def inspect_installed(root, manifest):
    package = distribution("pipecat-ai")
    if package.version != "1.5.0" or manifest.get("package_version") != "1.5.0":
        return {"status": "blocked_unpinned_version"}
    if Path(package.locate_file("pipecat")).resolve() != Path(root).resolve():
        return {"status": "blocked_wrong_distribution_root"}
    records = {}
    for entry in package.files or []:
        name = str(entry)
        if not name.startswith("pipecat/") or not name.endswith(".py"):
            continue
        if not entry.hash or entry.hash.mode != "sha256":
            return {"status": "blocked_invalid_source_manifest"}
        digest = base64.urlsafe_b64decode(entry.hash.value + "==").hex()
        records[name[len("pipecat/"):]] = digest
    return verify_sources(root, records, manifest.get("overlays"))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--package-root", required=True, type=Path)
    parser.add_argument("--manifest", required=True, type=Path)
    args = parser.parse_args()
    try:
        manifest = json.loads(args.manifest.read_text())
        if not isinstance(manifest, dict):
            raise ValueError("invalid manifest")
        result = inspect_installed(args.package_root, manifest)
    except (ValueError, OSError, PackageNotFoundError):
        result = {"status": "blocked_invalid_source_manifest"}
    print(json.dumps(result, sort_keys=True))
    return 0 if result["status"] == "pilot_source_integrity_verified" else 2


if __name__ == "__main__":
    raise SystemExit(main())
