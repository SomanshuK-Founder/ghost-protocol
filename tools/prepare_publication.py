"""Validate or copy the reviewed source manifest; never copy Git history or delete state."""

import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath

MANIFEST = "docs/release/phase5d-staging-files.json"


def relative_file(root, name):
    path = PurePosixPath(name)
    if path.is_absolute() or ".." in path.parts or "\\" in name or ":" in name:
        raise ValueError("Manifest paths must be relative and contained")
    result = root.joinpath(*path.parts)
    if not result.resolve().is_relative_to(root.resolve()):
        raise ValueError("Manifest path escapes the source directory")
    if any(part.is_symlink() for part in [result, *result.parents] if part != root.parent):
        raise ValueError("Symlinks are excluded from publication")
    return result


def validated_files(root):
    manifest = json.loads((root / MANIFEST).read_text(encoding="utf-8"))
    targets = {MANIFEST}
    files = []
    for entry in manifest["files"]:
        name = entry["path"]
        if name in targets:
            raise ValueError("Duplicate publication path")
        targets.add(name)
        source = relative_file(root, name)
        parts = PurePosixPath(name).parts
        if any(part in {".git", ".venv", "node_modules", ".next", "out"} for part in parts):
            raise ValueError("Private/generated directories cannot be published")
        if source.name.startswith(".env") and source.name != ".env.example":
            raise ValueError("Private environment files cannot be published")
        if hashlib.sha256(source.read_bytes()).hexdigest() != entry["sha256"]:
            raise ValueError(f"Publication source changed: {name}")
        files.append((source, name, entry["sha256"]))
    return files


def export(root, destination):
    files = validated_files(root)
    destination = destination.resolve()
    if destination.exists() or destination.is_relative_to(root) or root.is_relative_to(destination):
        raise ValueError("Use a fresh destination outside the working repository")
    destination.mkdir(parents=True)
    for source, name, digest in files:
        data = source.read_bytes()
        if hashlib.sha256(data).hexdigest() != digest:
            raise ValueError("Source changed during publication preparation")
        target = relative_file(destination, name)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
    target = destination / MANIFEST
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes((root / MANIFEST).read_bytes())
    return len(files) + 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--check", action="store_true")
    group.add_argument("--directory", type=Path)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    if args.check:
        print(f"Validated {len(validated_files(root))} publication files plus the manifest")
    else:
        print(f"Prepared {export(root, args.directory)} files; no Git operation or publication")


if __name__ == "__main__":
    main()
