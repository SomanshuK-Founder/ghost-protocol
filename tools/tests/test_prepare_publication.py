import hashlib
import importlib.util
import json
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location(
    "publication", Path(__file__).resolve().parents[1] / "prepare_publication.py"
)
publication = importlib.util.module_from_spec(spec)
spec.loader.exec_module(publication)


def source(tmp_path):
    root = tmp_path / "source"
    root.mkdir()
    (root / "README.md").write_text("Synthetic release source")
    manifest = root / publication.MANIFEST
    manifest.parent.mkdir(parents=True)
    manifest.write_text(
        json.dumps(
            {
                "files": [
                    {
                        "path": "README.md",
                        "sha256": hashlib.sha256((root / "README.md").read_bytes()).hexdigest(),
                    }
                ]
            }
        )
    )
    return root


def test_export_copies_only_verified_files_and_preserves_unknown_files(tmp_path):
    root = source(tmp_path)
    (root / ".env").write_text("synthetic-private-data")
    target = tmp_path / "candidate"
    assert publication.export(root, target) == 2
    assert (target / "README.md").read_bytes() == (root / "README.md").read_bytes()
    assert not (target / ".env").exists()
    assert (root / ".env").is_file()
    with pytest.raises(ValueError):
        publication.export(root, target)


def test_changed_source_fails_before_creating_destination(tmp_path):
    root = source(tmp_path)
    (root / "README.md").write_text("changed after review")
    target = tmp_path / "candidate"
    with pytest.raises(ValueError):
        publication.export(root, target)
    assert not target.exists()


@pytest.mark.parametrize("name", ["../private", "/private", "C:/private", "..\\private"])
def test_paths_cannot_escape_the_reviewed_directory(tmp_path, name):
    with pytest.raises(ValueError):
        publication.relative_file(tmp_path, name)
