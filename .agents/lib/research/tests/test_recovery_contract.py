from pathlib import Path

import pytest

from research import yaml_io


def test_atomic_write_failure_does_not_clobber_existing_target(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = tmp_path / "record.yaml"
    target.write_text("original\n", encoding="utf-8")

    def fail_replace(source: Path, destination: Path) -> None:
        raise OSError("simulated interruption")

    monkeypatch.setattr(yaml_io.os, "replace", fail_replace)

    with pytest.raises(OSError, match="simulated interruption"):
        yaml_io.write_text_if_changed(target, "replacement\n")

    assert target.read_text(encoding="utf-8") == "original\n"
    assert list(tmp_path.glob(".record.yaml.*.tmp")) == []
