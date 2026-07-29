"""Bounded, factual experiment-export parsing for experiment-workbench.

This module deliberately does not write project state or infer diagnoses.  It
turns a stable, project-contained export snapshot into normalized run facts;
the owner skill supplies identity, transaction, checkpoint, and reporting
semantics.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import math
import os
import re
import stat
from pathlib import Path
from typing import Any


MAX_IMPORT_FILE_BYTES = 16 * 1024 * 1024
MAX_IMPORT_TOTAL_BYTES = 128 * 1024 * 1024
MAX_IMPORT_RUNS = 1000
IMPORT_DIRECTORY_RE = re.compile(r"run-[A-Za-z0-9._-]+\.json")
METRIC_DIRECTIONS = {"higher-better", "lower-better", "neutral", "unknown"}
OUTCOMES = {"success", "partial", "failed", "blocked", "inconclusive"}
CLASSIFICATIONS = {
    "method", "implementation", "data", "evaluation", "resource",
    "environment", "process", "unknown",
}
TAGS = {"baseline", "milestone"}
STATE_OUTCOME = {
    "success": "success",
    "succeeded": "success",
    "completed": "success",
    "finished": "success",
    "partial": "partial",
    "failed": "failed",
    "failure": "failed",
    "crashed": "failed",
    "blocked": "blocked",
    "cancelled": "blocked",
    "canceled": "blocked",
    "killed": "blocked",
    "pending": "inconclusive",
    "queued": "inconclusive",
    "running": "inconclusive",
    "unknown": "inconclusive",
    "inconclusive": "inconclusive",
}


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _digest_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _digest_value(value: Any) -> str:
    return _digest_bytes(_canonical_bytes(value))


def _reject_nonfinite(token: str) -> None:
    raise ValueError(f"non-finite JSON number is not allowed: {token}")


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    payload: dict[str, Any] = {}
    for key, value in pairs:
        if key in payload:
            raise ValueError(f"duplicate JSON field is not allowed: {key}")
        payload[key] = value
    return payload


def _json_loads(raw: bytes, *, locator: str) -> Any:
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError(f"import source is not valid UTF-8: {locator}") from exc
    try:
        return json.loads(
            text,
            parse_constant=_reject_nonfinite,
            object_pairs_hook=_unique_object,
        )
    except (json.JSONDecodeError, ValueError) as exc:
        raise ValueError(f"invalid JSON import source {locator}: {exc}") from exc


def _project_relative_source(root: Path, source: str) -> tuple[Path, str]:
    project = root.resolve()
    requested = Path(source).expanduser()
    candidate = requested if requested.is_absolute() else project / requested
    try:
        relative = candidate.relative_to(project)
    except ValueError as exc:
        raise ValueError("experiment import source must remain inside the project workspace") from exc
    if not relative.parts or any(part in {"", ".", ".."} for part in relative.parts):
        raise ValueError("experiment import source has an unsafe project-relative path")
    cursor = project
    for part in relative.parts:
        cursor = cursor / part
        try:
            metadata = cursor.lstat()
        except FileNotFoundError as exc:
            raise ValueError(f"experiment import source does not exist: {relative.as_posix()}") from exc
        if stat.S_ISLNK(metadata.st_mode):
            raise ValueError("experiment import source must not contain symlink components")
    return candidate, relative.as_posix()


def _read_regular_file(path: Path, *, locator: str) -> bytes:
    try:
        expected = path.lstat()
    except FileNotFoundError as exc:
        raise ValueError(f"experiment import source disappeared: {locator}") from exc
    if not stat.S_ISREG(expected.st_mode):
        raise ValueError(f"experiment import source entry must be a regular file: {locator}")
    if expected.st_size > MAX_IMPORT_FILE_BYTES:
        raise ValueError(f"experiment import source exceeds 16 MiB: {locator}")
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        raise ValueError(f"experiment import source could not be opened safely: {locator}") from exc
    try:
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode):
            raise ValueError(f"experiment import source entry must be a regular file: {locator}")
        chunks: list[bytes] = []
        total = 0
        while True:
            chunk = os.read(descriptor, 1024 * 1024)
            if not chunk:
                break
            total += len(chunk)
            if total > MAX_IMPORT_FILE_BYTES:
                raise ValueError(f"experiment import source exceeds 16 MiB: {locator}")
            chunks.append(chunk)
        after = os.fstat(descriptor)
    finally:
        os.close(descriptor)
    identity = lambda item: (item.st_dev, item.st_ino, item.st_mode, item.st_size, item.st_mtime_ns, item.st_ctime_ns)
    if identity(expected) != identity(before) or identity(before) != identity(after):
        raise ValueError(f"experiment import source changed while being read: {locator}")
    return b"".join(chunks)


def _source_files_once(root: Path, source: str) -> tuple[str, str, list[dict[str, Any]]]:
    path, source_identity = _project_relative_source(root, source)
    metadata = path.lstat()
    files: list[dict[str, Any]] = []
    if stat.S_ISREG(metadata.st_mode):
        suffix = path.suffix.lower()
        if suffix not in {".json", ".csv"}:
            raise ValueError("experiment import file must use .json or .csv")
        raw = _read_regular_file(path, locator=source_identity)
        files.append({"name": path.name, "source_locator": source_identity, "bytes": raw})
        source_format = "csv" if suffix == ".csv" else "wandb-json"
    elif stat.S_ISDIR(metadata.st_mode):
        names = sorted(os.listdir(path))
        if not names:
            raise ValueError("experiment import directory is empty")
        for name in names:
            if not IMPORT_DIRECTORY_RE.fullmatch(name):
                raise ValueError("experiment import directory may contain only single-level run-*.json files")
            raw = _read_regular_file(path / name, locator=f"{source_identity}/{name}")
            files.append({"name": name, "source_locator": f"{source_identity}/{name}", "bytes": raw})
        source_format = "json-directory"
    else:
        raise ValueError("experiment import source must be a regular file or directory")
    total = sum(len(item["bytes"]) for item in files)
    if total > MAX_IMPORT_TOTAL_BYTES:
        raise ValueError("experiment import batch exceeds 128 MiB")
    return source_identity, source_format, files


def _source_fact(source_identity: str, source_format: str, files: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "source_identity": source_identity,
        "format": source_format,
        "files": [
            {
                "name": item["name"],
                "source_locator": item["source_locator"],
                "size": len(item["bytes"]),
                "sha256": _digest_bytes(item["bytes"]),
            }
            for item in files
        ],
    }


def _clean_text(value: Any, *, field: str, required: bool = False, limit: int = 8192) -> str:
    if value is None:
        text = ""
    elif isinstance(value, (str, int, float)) and not isinstance(value, bool):
        text = str(value).strip()
    else:
        raise ValueError(f"{field} must be scalar text")
    if any(ord(char) < 32 and char not in {"\t"} for char in text) or "\n" in text or "\r" in text:
        raise ValueError(f"{field} must be single-line text")
    if required and not text:
        raise ValueError(f"{field} must not be empty")
    if len(text.encode("utf-8")) > limit:
        raise ValueError(f"{field} exceeds its safe text limit")
    return " ".join(text.split())


def _list_value(value: Any, *, field: str, allowed: set[str] | None = None) -> list[str]:
    if value in (None, ""):
        return []
    raw = value
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return []
        if text.startswith("["):
            try:
                raw = json.loads(text, parse_constant=_reject_nonfinite)
            except (json.JSONDecodeError, ValueError) as exc:
                raise ValueError(f"{field} contains invalid JSON list") from exc
        else:
            raw = [item for item in text.split("|")]
    if not isinstance(raw, list):
        raise ValueError(f"{field} must be a list or | separated text")
    result: list[str] = []
    for index, item in enumerate(raw):
        text = _clean_text(item, field=f"{field}[{index}]", required=True, limit=1024)
        if allowed is not None and text not in allowed:
            raise ValueError(f"{field}[{index}] has unsupported value: {text}")
        if text not in result:
            result.append(text)
    return result


def _seed(value: Any) -> int | None:
    if value in (None, ""):
        return None
    if isinstance(value, bool):
        raise ValueError("seed must be an integer")
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("seed must be an integer") from exc
    if str(value).strip() not in {str(parsed), f"+{parsed}"} and not isinstance(value, int):
        raise ValueError("seed must be an integer")
    return parsed


def _metric(name: str, value: Any, *, unit: Any = "", direction: Any = "unknown") -> dict[str, Any]:
    metric_name = _clean_text(name, field="metric name", required=True, limit=256)
    if not isinstance(value, (int, float)) or isinstance(value, bool) or not math.isfinite(float(value)):
        raise ValueError(f"metric {metric_name} must have a finite numeric value")
    metric_direction = _clean_text(direction or "unknown", field=f"metric {metric_name} direction", required=True)
    if metric_direction not in METRIC_DIRECTIONS:
        raise ValueError(f"metric {metric_name} has unsupported direction: {metric_direction}")
    return {
        "name": metric_name,
        "value": value,
        "unit": _clean_text(unit, field=f"metric {metric_name} unit", limit=256),
        "direction": metric_direction,
    }


def _metrics_from_object(raw: Any, *, field: str) -> dict[str, dict[str, Any]]:
    if raw in (None, ""):
        return {}
    if not isinstance(raw, dict):
        raise ValueError(f"{field} must be an object")
    metrics: dict[str, dict[str, Any]] = {}
    for raw_name, raw_metric in raw.items():
        name = _clean_text(raw_name, field=f"{field} metric name", required=True, limit=256)
        if name in metrics:
            raise ValueError(f"duplicate metric identity: {name}")
        if isinstance(raw_metric, dict):
            extra = set(raw_metric) - {"value", "unit", "direction", "name"}
            if extra:
                raise ValueError(f"metric {name} has unsupported fields: {', '.join(sorted(extra))}")
            metrics[name] = _metric(
                name,
                raw_metric.get("value"),
                unit=raw_metric.get("unit", ""),
                direction=raw_metric.get("direction", "unknown"),
            )
        else:
            metrics[name] = _metric(name, raw_metric)
    return metrics


def _csv_rows(raw: bytes, *, locator: str) -> list[tuple[dict[str, str], str]]:
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError(f"import source is not valid UTF-8: {locator}") from exc
    try:
        rows = list(csv.reader(io.StringIO(text), strict=True))
    except csv.Error as exc:
        raise ValueError(f"invalid CSV import source {locator}: {exc}") from exc
    if not rows or not rows[0]:
        raise ValueError("CSV import requires a non-empty header")
    header = [_clean_text(item, field="CSV header", required=True, limit=256) for item in rows[0]]
    if len(header) != len(set(header)):
        raise ValueError("CSV import contains duplicate columns")
    result: list[tuple[dict[str, str], str]] = []
    for row_number, values in enumerate(rows[1:], start=2):
        if not values or all(not item.strip() for item in values):
            continue
        if len(values) != len(header):
            raise ValueError(f"CSV row {row_number} does not match the stable header")
        result.append((dict(zip(header, values)), f"row:{row_number}"))
    return result


def _source_objects(source_format: str, files: list[dict[str, Any]]) -> list[tuple[dict[str, Any], str, str]]:
    objects: list[tuple[dict[str, Any], str, str]] = []
    if source_format == "csv":
        for raw, locator in _csv_rows(files[0]["bytes"], locator=files[0]["source_locator"]):
            objects.append((raw, locator, files[0]["name"]))
    elif source_format == "wandb-json":
        parsed = _json_loads(files[0]["bytes"], locator=files[0]["source_locator"])
        if isinstance(parsed, dict):
            if set(parsed) != {"runs"} or not isinstance(parsed["runs"], list):
                raise ValueError("W&B JSON object must have the exact shape {runs: [...]}")
            parsed = parsed["runs"]
        if not isinstance(parsed, list):
            raise ValueError("W&B JSON must be a top-level list or exact {runs: [...]} object")
        for index, raw in enumerate(parsed, start=1):
            if not isinstance(raw, dict):
                raise ValueError(f"W&B JSON run {index} must be an object")
            objects.append((raw, f"item:{index}", files[0]["name"]))
    else:
        for item in files:
            raw = _json_loads(item["bytes"], locator=item["source_locator"])
            if not isinstance(raw, dict):
                raise ValueError(f"directory import entry must contain one object: {item['name']}")
            objects.append((raw, item["name"], item["name"]))
    if not objects:
        raise ValueError("experiment import contains no runs")
    if len(objects) > MAX_IMPORT_RUNS:
        raise ValueError("experiment import exceeds 1000 runs")
    return objects


def _normalize_run(raw: dict[str, Any], *, source_format: str, locator: str, file_name: str) -> dict[str, Any]:
    item_digest = _digest_value(raw)
    external_id = _clean_text(
        raw.get("external_id", raw.get("id", raw.get("run_id", raw.get("name", "")))),
        field="external run id",
        limit=512,
    )
    config = raw.get("config", {})
    if config in (None, ""):
        config = {}
    elif source_format == "csv" and isinstance(config, str):
        config = _json_loads(config.encode("utf-8"), locator=f"{locator}:config")
    if not isinstance(config, dict):
        raise ValueError("config must be an object")
    config_revision = _clean_text(
        raw.get("config_revision", raw.get("config-revision", "")),
        field="config revision",
        limit=512,
    ) or f"config-sha256:{_digest_value(config)}"

    metrics: dict[str, dict[str, Any]] = {}
    if source_format == "csv":
        metric_values: dict[str, Any] = {}
        metric_units: dict[str, Any] = {}
        metric_directions: dict[str, Any] = {}
        for key, value in raw.items():
            if not key.startswith("metric.") or value == "":
                continue
            suffix = key[len("metric."):]
            if suffix.endswith(".unit"):
                metric_units[suffix[:-5]] = value
            elif suffix.endswith(".direction"):
                metric_directions[suffix[:-10]] = value
            else:
                metric_values[suffix] = value
        orphan = (set(metric_units) | set(metric_directions)) - set(metric_values)
        if orphan:
            raise ValueError(f"CSV metric metadata has no value column: {', '.join(sorted(orphan))}")
        for name, value in metric_values.items():
            try:
                numeric = float(value)
            except ValueError as exc:
                raise ValueError(f"CSV metric {name} must be numeric") from exc
            metrics[name] = _metric(name, numeric, unit=metric_units.get(name, ""), direction=metric_directions.get(name, "unknown"))
    else:
        metrics.update(_metrics_from_object(raw.get("metrics"), field="metrics"))
        summary = raw.get("summary")
        if isinstance(summary, dict):
            for name, value in summary.items():
                if isinstance(value, (int, float)) and not isinstance(value, bool):
                    clean_name = _clean_text(name, field="summary metric name", required=True, limit=256)
                    if clean_name in metrics:
                        raise ValueError(f"duplicate metric identity: {clean_name}")
                    metrics[clean_name] = _metric(clean_name, value)

    state = _clean_text(raw.get("state", raw.get("status", "")), field="run state", limit=128).lower()
    explicit_outcome = _clean_text(raw.get("outcome", ""), field="outcome", limit=128).lower()
    if explicit_outcome and explicit_outcome not in OUTCOMES:
        raise ValueError(f"unsupported explicit outcome: {explicit_outcome}")
    outcome = explicit_outcome or STATE_OUTCOME.get(state, "inconclusive")
    raw_summary = raw.get("result_summary", raw.get("summary_text", ""))
    if not raw_summary and isinstance(raw.get("summary"), str):
        raw_summary = raw["summary"]
    result_summary = _clean_text(raw_summary, field="result summary", limit=8192)
    if not result_summary:
        identity = external_id or item_digest[:12]
        result_summary = f"Imported run {identity}" + (f" with state {state}." if state else ".")

    known_csv = {
        "external_id", "id", "run_id", "name", "seed", "config_revision", "config-revision",
        "tested_hypothesis", "hypothesis", "changes", "change", "result_summary", "summary_text",
        "summary", "state", "status", "outcome", "classifications", "classification", "tags", "tag",
        "artifacts", "artifact", "next_actions", "next_action", "why_this_run", "config",
    }
    if source_format == "csv":
        unsupported = [key for key in raw if key not in known_csv and not key.startswith("metric.")]
        if unsupported:
            raise ValueError(f"CSV contains unsupported columns: {', '.join(sorted(unsupported))}")

    classifications = _list_value(raw.get("classifications", raw.get("classification")), field="classifications", allowed=CLASSIFICATIONS)
    tags = _list_value(raw.get("tags", raw.get("tag")), field="tags", allowed=TAGS)
    return {
        "item_digest": item_digest,
        "external_id": external_id,
        "source_locator": locator,
        "source_file": file_name,
        "seed": _seed(raw.get("seed")),
        "config_revision": config_revision,
        "tested_hypothesis": _clean_text(raw.get("tested_hypothesis", raw.get("hypothesis", "")), field="tested hypothesis", limit=8192),
        "changes": _list_value(raw.get("changes", raw.get("change")), field="changes"),
        "metrics": metrics,
        "result_summary": result_summary,
        "outcome": outcome,
        "classifications": classifications or ["unknown"],
        "artifacts": _list_value(raw.get("artifacts", raw.get("artifact")), field="artifacts"),
        "next_actions": _list_value(raw.get("next_actions", raw.get("next_action")), field="next actions"),
        "why_this_run": _clean_text(raw.get("why_this_run", ""), field="why this run", limit=8192),
        "tags": tags,
    }


def load_import_batch(root: Path, source: str) -> dict[str, Any]:
    """Return a two-pass stable import batch with raw bytes and normalized facts."""
    first_identity, first_format, first_files = _source_files_once(root, source)
    second_identity, second_format, second_files = _source_files_once(root, source)
    first_fact = _source_fact(first_identity, first_format, first_files)
    second_fact = _source_fact(second_identity, second_format, second_files)
    if first_fact != second_fact:
        raise ValueError("experiment import source changed while it was inspected; retry")
    objects = _source_objects(second_format, second_files)
    runs = [
        _normalize_run(raw, source_format=second_format, locator=locator, file_name=file_name)
        for raw, locator, file_name in objects
    ]
    item_digests = [item["item_digest"] for item in runs]
    batch_digest = _digest_value({"source": second_fact, "item_digests": item_digests})
    return {
        "schema_version": "experiment-import/v1",
        "source_fact": second_fact,
        "source_files": second_files,
        "format": second_format,
        "batch_digest": batch_digest,
        "runs": runs,
    }


def require_current_import_batch(root: Path, source: str, expected: dict[str, Any]) -> dict[str, Any]:
    current = load_import_batch(root, source)
    if current["source_fact"] != expected.get("source_fact") or current["batch_digest"] != expected.get("batch_digest"):
        raise ValueError("experiment import source changed before commit; retry")
    return current
