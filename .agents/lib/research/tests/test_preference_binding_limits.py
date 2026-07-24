from __future__ import annotations

import hashlib
import os
from pathlib import Path

import pytest

import research.preference_selection as preferences


def test_regular_file_binding_streams_exact_bytes(tmp_path: Path) -> None:
    artifact = tmp_path / "artifact.bin"
    payload = b"abc" * 4097
    artifact.write_bytes(payload)

    binding = preferences.regular_file_binding(
        artifact,
        logical_identity="artifact.bin",
        trusted_root=tmp_path,
    )

    assert binding["bytes_digest"] == hashlib.sha256(payload).hexdigest()
    assert len(binding["identity_digest"]) == 64


def test_tree_binding_rejects_per_file_budget_without_partial_result(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tree = tmp_path / "tree"
    tree.mkdir()
    (tree / "large.bin").write_bytes(b"x" * 9)
    monkeypatch.setattr(preferences, "MAX_BINDING_FILE_BYTES", 8)

    with pytest.raises(ValueError, match="byte budget"):
        preferences.regular_tree_binding(tree, logical_identity="tree", trusted_root=tmp_path)


def test_tree_binding_rejects_total_byte_entry_and_depth_budgets(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    byte_tree = tmp_path / "bytes"
    byte_tree.mkdir()
    (byte_tree / "a").write_bytes(b"a" * 7)
    (byte_tree / "b").write_bytes(b"b" * 7)
    monkeypatch.setattr(preferences, "MAX_BINDING_FILE_BYTES", 10)
    monkeypatch.setattr(preferences, "MAX_BINDING_TREE_BYTES", 12)
    with pytest.raises(ValueError, match="byte budget"):
        preferences.regular_tree_binding(
            byte_tree,
            logical_identity="bytes",
            trusted_root=tmp_path,
        )

    entry_tree = tmp_path / "entries"
    entry_tree.mkdir()
    for name in ("a", "b", "c"):
        (entry_tree / name).write_text(name, encoding="utf-8")
    monkeypatch.setattr(preferences, "MAX_BINDING_TREE_BYTES", 100)
    monkeypatch.setattr(preferences, "MAX_BINDING_TREE_ENTRIES", 2)
    with pytest.raises(ValueError, match="entry budget"):
        preferences.regular_tree_binding(
            entry_tree,
            logical_identity="entries",
            trusted_root=tmp_path,
        )

    depth_tree = tmp_path / "depth"
    (depth_tree / "one" / "two").mkdir(parents=True)
    (depth_tree / "one" / "two" / "leaf").write_text("leaf", encoding="utf-8")
    monkeypatch.setattr(preferences, "MAX_BINDING_TREE_ENTRIES", 20)
    monkeypatch.setattr(preferences, "MAX_BINDING_TREE_DEPTH", 2)
    with pytest.raises(ValueError, match="depth budget"):
        preferences.regular_tree_binding(
            depth_tree,
            logical_identity="depth",
            trusted_root=tmp_path,
        )


def test_stream_hash_contract_does_not_return_file_bytes(tmp_path: Path) -> None:
    artifact = tmp_path / "artifact.bin"
    artifact.write_bytes(b"z" * (2 * 1024 * 1024 + 17))
    descriptor = os.open(tmp_path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        digest, metadata, byte_count = preferences._hash_regular_file_at(
            descriptor,
            artifact.name,
        )
    finally:
        os.close(descriptor)

    assert digest == hashlib.sha256(artifact.read_bytes()).hexdigest()
    assert byte_count == metadata.st_size
    assert isinstance(digest, str)


def test_stream_hash_rejects_same_path_inode_replacement(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    artifact = tmp_path / "artifact.bin"
    artifact.write_bytes(b"original")
    descriptor = os.open(tmp_path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    original_read = os.read
    replaced = False

    def replacing_read(file_descriptor: int, count: int) -> bytes:
        nonlocal replaced
        chunk = original_read(file_descriptor, count)
        if chunk and not replaced:
            replacement = tmp_path / "replacement.bin"
            replacement.write_bytes(b"original")
            os.replace(replacement, artifact)
            replaced = True
        return chunk

    monkeypatch.setattr(preferences.os, "read", replacing_read)
    try:
        with pytest.raises(ValueError, match="changed while it was read"):
            preferences._hash_regular_file_at(descriptor, artifact.name)
    finally:
        os.close(descriptor)


def test_tree_binding_rejects_directory_entry_race(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tree = tmp_path / "tree"
    tree.mkdir()
    (tree / "first").write_text("first", encoding="utf-8")
    original_hash = preferences._hash_regular_file_at
    mutated = False

    def mutating_hash(*args: object, **kwargs: object) -> tuple[str, os.stat_result, int]:
        nonlocal mutated
        result = original_hash(*args, **kwargs)
        if not mutated:
            (tree / "inserted").write_text("inserted", encoding="utf-8")
            mutated = True
        return result

    monkeypatch.setattr(preferences, "_hash_regular_file_at", mutating_hash)
    with pytest.raises(ValueError, match="tree changed while it was read"):
        preferences.regular_tree_binding(tree, logical_identity="tree", trusted_root=tmp_path)
