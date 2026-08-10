#!/usr/bin/env python3
"""Research-value evaluation harness (G5) — Tier-1: read-only quality metrics.

This is a READ-ONLY quality gauge for the research workspace, per the direction
doc temp/RESEARCH_VALUE_EVAL_DESIGN.md. It does NOT change any governance,
confirmation gate, retrieval algorithm, or program state. Its only side effect is
writing its own report under kb/eval/research-value/reports/.

For the two program datasets under kb/eval/research-value/dataset/ it measures:

  * retrieval recall@5 / @10  — do expected_units land in the kb-find top-k?
  * grounding rate            — are auto-gradeable gold facts actually present in
                                their source unit's note/parse-cache? (audit P0:
                                "evidence bound to the claim")
  * source distribution       — do grounded facts come from a hand-REWRITTEN note
                                or a script-produced/template artifact? (decision A)
  * empty-program control      — the humanoid program has zero mounted units;
                                retrieval should surface nothing useful, and any
                                confident top-1 is a hallucination-risk signal.
  * H1 gate integrity         — confirmed / auto_confirmed units whose core
                                content is empty (the "confirmed but hollow" risk).

Imports go through the public façade only (research.core / research.retrieval /
research.common), so this keeps working across the parallel lib refactor.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

SCRIPT_PATH = Path(__file__).resolve()
skills_dir = SCRIPT_PATH.parents[2]
if skills_dir.name != "skills":
    raise SystemExit("Could not locate the managed research runtime.")
if skills_dir.parent.name == ".agents":
    PROJECT_ROOT = skills_dir.parent.parent
    lib = PROJECT_ROOT / ".agents" / "lib"
else:
    PROJECT_ROOT = skills_dir.parent
    lib = PROJECT_ROOT / "runtime" / "lib"
if not (skills_dir / "metadata.yaml").is_file() or not (lib / "research" / "__init__.py").is_file() or not (lib / "research" / "bootstrap.py").is_file():
    raise SystemExit("Could not locate the managed research runtime.")
sys.path.insert(0, str(lib))

from research.bootstrap import ensure_managed_runtime

if __name__ == "__main__":
    ensure_managed_runtime(PROJECT_ROOT)

from research.common import add_project_root_argument, load_yaml, print_resolved_project_roots, write_text_if_changed
from research.core import (
    UNIT_KIND_DIRS,
    iter_records,
    kb_root,
    kind_dir,
    project_root,
    search_records,
    units_root,
)
from research.retrieval import tokenize_query
from research.journal import mutation_transaction

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

CORE_CONTENT_FIELDS = [
    "research_problem",
    "motivation",
    "story",
    "method",
    "innovations",
    "changes_and_effects",
    "mechanism",
    "why_it_might_work",
]

# Grounded if this fraction of a fact's significant tokens appear in the source
# artifact text under the local diagnostic keyword-subset / fuzzy-match check.
GROUNDING_THRESHOLD = 0.6

REWRITTEN_MARKER = "REWRITTEN"

# Very small stop set — we keep technical numbers (29, 200, 15000) as signal.
STOPWORDS = {
    "the", "a", "an", "and", "or", "of", "to", "in", "on", "for", "with", "is",
    "are", "was", "were", "be", "by", "as", "at", "it", "its", "that", "this",
    "these", "those", "from", "into", "onto", "than", "then", "so", "such",
    "via", "per", "not", "no", "both", "all", "any", "one", "two", "each",
    "which", "also", "e", "g", "eg", "ie", "et", "al", "s",
}

DATASET_DIRNAME = Path("eval") / "research-value" / "dataset"
REPORT_DIRNAME = Path("eval") / "research-value" / "reports"

AXES = ["A", "B", "C", "D", "E", "F", "G"]
AXIS_NAMES = {
    "A": "single-paper fact",
    "B": "cross-unit compare",
    "C": "context / trend",
    "D": "gap / whitespace",
    "E": "reuse / code",
    "F": "program state",
    "G": "idea discussion",
}


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------

def significant_tokens(text: str) -> list[str]:
    out: list[str] = []
    for tok in tokenize_query(text):
        if len(tok) < 2:
            continue
        if tok in STOPWORDS:
            continue
        out.append(tok)
    # preserve order but dedupe
    seen: set[str] = set()
    uniq: list[str] = []
    for tok in out:
        if tok not in seen:
            seen.add(tok)
            uniq.append(tok)
    return uniq


def _is_empty_value(value) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        return not value.strip()
    if isinstance(value, (list, dict)):
        return len(value) == 0
    return False


def paper_core_content_empty(record: dict) -> bool:
    cc = ((record.get("payload") or {}).get("core_content")) or {}
    return all(_is_empty_value(cc.get(field)) for field in CORE_CONTENT_FIELDS)


def _non_source_markdown(unit_dir: Path) -> list[Path]:
    if not unit_dir.exists():
        return []
    paths = sorted({*unit_dir.rglob("*.md"), *unit_dir.rglob("*.markdown")})
    return [p for p in paths if "source" not in p.relative_to(unit_dir).parts]


def unit_dir_for(root: Path, record: dict) -> Path | None:
    kind = str(record.get("kind") or "")
    uid = str(record.get("id") or "")
    if kind not in UNIT_KIND_DIRS or not uid:
        return None
    return units_root(root) / kind_dir(kind) / uid


def gather_unit_text(root: Path, record: dict) -> str:
    """Note/repo-docs markdown + parse-cache chunk text, lowercased."""
    unit_dir = unit_dir_for(root, record)
    if unit_dir is None:
        return ""
    chunks: list[str] = []
    for md in _non_source_markdown(unit_dir):
        try:
            chunks.append(md.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError):
            continue
    cache = unit_dir / "parse-cache.yaml"
    if cache.exists():
        data = load_yaml(cache, default={}) or {}
        for chunk in data.get("chunks", []) or []:
            if isinstance(chunk, dict):
                chunks.append(str(chunk.get("text") or ""))
    return "\n".join(chunks).lower()


def unit_note_is_rewritten(root: Path, record: dict) -> bool:
    unit_dir = unit_dir_for(root, record)
    if unit_dir is None:
        return False
    for md in _non_source_markdown(unit_dir):
        if md.name in {"note.md", "repo-note.md"}:
            try:
                if REWRITTEN_MARKER in md.read_text(encoding="utf-8"):
                    return True
            except (OSError, UnicodeDecodeError):
                continue
    return False


def gather_program_text(root: Path, program_id: str) -> str:
    """Program state + workflow text, lowercased.

    Kept available for program-state fact checks; program-sourced gold facts are
    marked auto_gradeable:false in the datasets (they live in state.yaml, not a
    unit note), so they are recorded but not folded into the unit grounding rate.
    """
    prog_dir = kb_root(root) / "programs" / program_id
    if not prog_dir.exists():
        return ""
    chunks: list[str] = []
    for name in ("state.yaml", "README.md"):
        p = prog_dir / name
        if p.exists():
            try:
                chunks.append(p.read_text(encoding="utf-8"))
            except (OSError, UnicodeDecodeError):
                pass
    wf = prog_dir / "workflow"
    if wf.exists():
        for p in sorted(wf.glob("*")):
            if p.is_file():
                try:
                    chunks.append(p.read_text(encoding="utf-8"))
                except (OSError, UnicodeDecodeError):
                    pass
    return "\n".join(chunks).lower()


def program_fact_grounding(root: Path, program_id: str, fact_text: str) -> tuple[bool, float]:
    """Check a program-state gold fact against the program's own artifacts."""
    text = gather_program_text(root, program_id)
    toks = significant_tokens(fact_text)
    if not toks:
        return False, 0.0
    present = [t for t in toks if t in text]
    frac = len(present) / len(toks)
    return frac >= GROUNDING_THRESHOLD, frac


def probe_pdf_backends() -> dict:
    import importlib.util

    def has(mod: str) -> bool:
        try:
            return importlib.util.find_spec(mod) is not None
        except (ImportError, ValueError):
            return False

    backends = {
        "pypdf": has("pypdf"),
        "PyPDF2": has("PyPDF2"),
        "PyMuPDF(fitz)": has("fitz"),
        "yaml": has("yaml"),
    }
    backends["pdf_available"] = backends["pypdf"] or backends["PyPDF2"] or backends["PyMuPDF(fitz)"]
    return backends


def git_short_head(repo: Path) -> str:
    try:
        out = subprocess.run(
            ["git", "-C", str(repo), "rev-parse", "--short", "HEAD"],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            check=False,
            timeout=10,
        )
        return out.stdout.strip() or "n/a"
    except (OSError, subprocess.SubprocessError):
        return "n/a"


def next_available_report_path(report_dir: Path, stamp: str) -> Path:
    path = report_dir / f"{stamp}-tier1.md"
    if not path.exists():
        return path
    index = 2
    while True:
        candidate = report_dir / f"{stamp}-tier1-{index}.md"
        if not candidate.exists():
            return candidate
        index += 1


# ---------------------------------------------------------------------------
# Evaluation
# ---------------------------------------------------------------------------

def load_datasets(root: Path, program: str | None) -> list[dict]:
    dataset_dir = kb_root(root) / DATASET_DIRNAME
    datasets: list[dict] = []
    for path in sorted(dataset_dir.glob("*.yaml")):
        data = load_yaml(path, default={}) or {}
        pid = str(data.get("program_id") or path.stem)
        if program and pid != program:
            continue
        datasets.append(data)
    return datasets


def evaluate(root: Path, program: str | None) -> dict:
    datasets = load_datasets(root, program)
    if not datasets:
        raise SystemExit("No research-value datasets are available in this workspace.")

    records = iter_records(root)
    record_by_id = {str(r.get("id") or ""): r for r in records}

    questions_out: list[dict] = []

    # recall accumulators
    recall_hits = {5: 0, 10: 0}
    recall_denom = 0
    recall_by_axis: dict[str, dict] = {ax: {"hits5": 0, "hits10": 0, "denom": 0} for ax in AXES}
    recall_by_program: dict[str, dict] = defaultdict(lambda: {"hits5": 0, "hits10": 0, "denom": 0})

    # grounding accumulators
    ground_total = 0
    ground_hit = 0
    ground_by_axis: dict[str, dict] = {ax: {"total": 0, "hit": 0} for ax in AXES}
    source_dist = {"manual_rewritten": 0, "script_product": 0}

    # program-state grounding (answerable F facts sourced from state/workflow, not a unit)
    prog_ground_total = 0
    prog_ground_hit = 0

    # empty-program control
    control: list[dict] = []

    for data in datasets:
        pid = str(data.get("program_id") or "")
        for q in data.get("questions", []):
            axis = str(q.get("axis") or "?")
            expected = list(q.get("expected_units") or [])
            question = str(q.get("question") or "")
            no_data = bool(q.get("no_data_expected"))

            ranked = search_records(root, question)
            ranked_ids = [str(r.get("id") or "") for r in ranked]
            top5, top10 = ranked_ids[:5], ranked_ids[:10]
            top1 = (ranked_ids[0], int(ranked[0].get("_search_score") or 0)) if ranked else None

            q_out = {
                "id": q.get("id"),
                "program_id": pid,
                "axis": axis,
                "tier": q.get("tier"),
                "no_data_expected": no_data,
                "expected_units": expected,
                "top1": top1,
                "in_top5": [], "in_top10": [],
                "grounding": [],
            }

            if expected:
                hit5 = sum(1 for u in expected if u in top5)
                hit10 = sum(1 for u in expected if u in top10)
                recall_hits[5] += hit5
                recall_hits[10] += hit10
                recall_denom += len(expected)
                recall_by_axis[axis]["hits5"] += hit5
                recall_by_axis[axis]["hits10"] += hit10
                recall_by_axis[axis]["denom"] += len(expected)
                recall_by_program[pid]["hits5"] += hit5
                recall_by_program[pid]["hits10"] += hit10
                recall_by_program[pid]["denom"] += len(expected)
                q_out["in_top5"] = [u for u in expected if u in top5]
                q_out["in_top10"] = [u for u in expected if u in top10]

            if no_data:
                control.append({
                    "id": q.get("id"),
                    "axis": axis,
                    "top1": top1,
                    # any returned unit is a false-positive surface (there is no
                    # correct unit to return)
                    "false_positive": top1 is not None,
                })

            # grounding on tier-1 gold facts
            for fact in (q.get("gold_facts") or []):
                if q.get("tier") != 1:
                    continue
                src_id = str(fact.get("source_unit_id") or "")
                rec = record_by_id.get(src_id)
                if rec is None:
                    # source is a program (state fact), not a unit. Answerable
                    # F-axis facts (not no_data controls) are checked against the
                    # program's own artifacts and reported separately — they are
                    # NOT folded into the unit grounding rate.
                    if not no_data and (kb_root(root) / "programs" / src_id).exists():
                        grounded, frac = program_fact_grounding(root, src_id, str(fact.get("text") or ""))
                        prog_ground_total += 1
                        if grounded:
                            prog_ground_hit += 1
                        q_out["grounding"].append({
                            "source_unit_id": src_id,
                            "coverage": round(frac, 3),
                            "grounded": grounded,
                            "note_bucket": "program_state",
                            "matched": None,
                            "significant_tokens": None,
                        })
                    continue
                if not fact.get("auto_gradeable"):
                    continue
                text = gather_unit_text(root, rec)
                toks = significant_tokens(str(fact.get("text") or ""))
                present = [t for t in toks if t in text]
                frac = (len(present) / len(toks)) if toks else 0.0
                grounded = frac >= GROUNDING_THRESHOLD
                rewritten = unit_note_is_rewritten(root, rec)
                bucket = "manual_rewritten" if rewritten else "script_product"

                ground_total += 1
                ground_by_axis[axis]["total"] += 1
                if grounded:
                    ground_hit += 1
                    ground_by_axis[axis]["hit"] += 1
                    source_dist[bucket] += 1

                q_out["grounding"].append({
                    "source_unit_id": src_id,
                    "coverage": round(frac, 3),
                    "grounded": grounded,
                    "note_bucket": bucket,
                    "matched": len(present),
                    "significant_tokens": len(toks),
                })

            questions_out.append(q_out)

    # ---- H1 gate integrity (pure scan, no Q&A) ----
    status_dist = Counter(str(r.get("confirmation_status") or "?") for r in records)
    papers = [r for r in records if str(r.get("kind")) == "paper"]
    papers_empty_cc = sum(1 for r in papers if paper_core_content_empty(r))

    def unit_empty_content(rec: dict) -> bool:
        if str(rec.get("kind")) == "paper":
            return paper_core_content_empty(rec)
        # non-paper: primary curated markdown missing or near-empty
        udir = unit_dir_for(root, rec)
        if udir is None:
            return True
        total = 0
        for md in _non_source_markdown(udir):
            try:
                total += len(md.read_text(encoding="utf-8").strip())
            except (OSError, UnicodeDecodeError):
                pass
        return total < 200

    settled_states = ("confirmed", "auto_confirmed")
    gate = {}
    for st in settled_states:
        units = [r for r in records if str(r.get("confirmation_status")) == st]
        empty = [str(r.get("id")) for r in units if unit_empty_content(r)]
        gate[st] = {"count": len(units), "empty": len(empty), "empty_ids": empty}

    gate_integrity = {
        "status_distribution": dict(status_dist),
        "total_units": len(records),
        "settled": gate,
        "papers_total": len(papers),
        "papers_empty_core_content": papers_empty_cc,
    }

    # ---- aggregate axis weakness ----
    axis_summary = {}
    for ax in AXES:
        r = recall_by_axis[ax]
        g = ground_by_axis[ax]
        axis_summary[ax] = {
            "recall5": (r["hits5"] / r["denom"]) if r["denom"] else None,
            "recall10": (r["hits10"] / r["denom"]) if r["denom"] else None,
            "recall_denom": r["denom"],
            "grounding": (g["hit"] / g["total"]) if g["total"] else None,
            "grounding_total": g["total"],
        }

    result = {
        "recall": {
            "at5": (recall_hits[5] / recall_denom) if recall_denom else None,
            "at10": (recall_hits[10] / recall_denom) if recall_denom else None,
            "hits5": recall_hits[5],
            "hits10": recall_hits[10],
            "denom": recall_denom,
            "by_program": {
                p: {
                    "at5": (v["hits5"] / v["denom"]) if v["denom"] else None,
                    "at10": (v["hits10"] / v["denom"]) if v["denom"] else None,
                    "denom": v["denom"],
                }
                for p, v in recall_by_program.items()
            },
        },
        "grounding": {
            "rate": (ground_hit / ground_total) if ground_total else None,
            "hit": ground_hit,
            "total": ground_total,
            "source_distribution": source_dist,
            "program_state": {
                "rate": (prog_ground_hit / prog_ground_total) if prog_ground_total else None,
                "hit": prog_ground_hit,
                "total": prog_ground_total,
            },
        },
        "empty_program_control": {
            "questions": len(control),
            "false_positive_top1": sum(1 for c in control if c["false_positive"]),
            "detail": control,
        },
        "gate_integrity": gate_integrity,
        "axis_summary": axis_summary,
        "questions": questions_out,
    }
    return result


def weakest_axes(axis_summary: dict, n: int = 3) -> list[tuple[str, float]]:
    scored: list[tuple[str, float]] = []
    for ax, s in axis_summary.items():
        parts = [v for v in (s["recall5"], s["grounding"]) if v is not None]
        if not parts:
            continue
        scored.append((ax, sum(parts) / len(parts)))
    scored.sort(key=lambda kv: kv[1])
    return scored[:n]


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------

def _pct(v) -> str:
    return "n/a" if v is None else f"{v * 100:.1f}%"


def render_report(root: Path, result: dict, meta: dict) -> str:
    L: list[str] = []
    L.append("# Research-value evaluation — Tier-1 baseline report")
    L.append("")
    L.append(f"- Generated (UTC): {meta['utc']}")
    L.append(f"- KB anchor: kb@{meta['kb_head']} / repo@{meta['repo_head']}")
    L.append(f"- Units total: {result['gate_integrity']['total_units']}  "
             f"(confirmed: {result['gate_integrity']['settled']['confirmed']['count']}, "
             f"auto_confirmed: {result['gate_integrity']['settled']['auto_confirmed']['count']})")
    L.append(f"- Questions evaluated: {meta['n_questions']} "
             f"(programs: {', '.join(meta['programs'])})")
    pdf = meta["pdf"]
    L.append(f"- PDF backend: pdf_available={pdf['pdf_available']} "
             f"(pypdf={pdf['pypdf']}, PyMuPDF={pdf['PyMuPDF(fitz)']}, PyPDF2={pdf['PyPDF2']}) "
             f"— grounding rate is only comparable when a backend is present")
    L.append("")

    # Tier-1 headline
    rc = result["recall"]
    gr = result["grounding"]
    L.append("## Tier-1 metrics")
    L.append("")
    L.append(f"- **Retrieval recall@5 = {_pct(rc['at5'])}**, **recall@10 = {_pct(rc['at10'])}** "
             f"({rc['hits5']}/{rc['denom']} and {rc['hits10']}/{rc['denom']} expected-unit slots).")
    for p, v in rc["by_program"].items():
        L.append(f"    - {p}: recall@5={_pct(v['at5'])}, recall@10={_pct(v['at10'])} (denom={v['denom']})")
    L.append(f"- **Grounding rate = {_pct(gr['rate'])}** ({gr['hit']}/{gr['total']} auto-gradeable gold facts "
             f"found in their source unit's note/parse-cache).")
    sd = gr["source_distribution"]
    L.append(f"    - Source distribution of grounded facts: "
             f"manual REWRITTEN note = {sd['manual_rewritten']}, "
             f"script-product / no-marker = {sd['script_product']}.")
    ps = gr["program_state"]
    L.append(f"    - Program-state facts (answerable F-axis, checked vs state.yaml/workflow, "
             f"not folded into the unit rate): {ps['hit']}/{ps['total']} grounded "
             f"({_pct(ps['rate'])}).")
    ctrl = result["empty_program_control"]
    L.append(f"- **Empty-program control (humanoid)**: {ctrl['questions']} no-data questions; "
             f"retrieval returned a confident top-1 unit for {ctrl['false_positive_top1']}/{ctrl['questions']} "
             f"of them (each is a hallucination-risk surface — there is no correct unit to return).")

    gi = result["gate_integrity"]
    conf = gi["settled"]["confirmed"]
    auto = gi["settled"]["auto_confirmed"]
    L.append(f"- **H1 gate integrity**: confirmed units = {conf['count']}, of which empty-content = {conf['empty']} "
             f"({_pct((conf['empty']/conf['count']) if conf['count'] else None)}); "
             f"auto_confirmed = {auto['count']}, empty = {auto['empty']}.")
    L.append(f"    - Systemic context: {gi['papers_empty_core_content']}/{gi['papers_total']} papers have a fully "
             f"empty structured `core_content` (regardless of status) — the latent 'confirm a hollow unit' risk.")
    L.append(f"    - confirmation_status distribution: {gi['status_distribution']}")
    L.append("")

    # per-axis table
    L.append("## Per-axis summary")
    L.append("")
    L.append("| axis | name | recall@5 | recall@10 | grounding | #recall-denom | #grounded-facts |")
    L.append("|---|---|---|---|---|---|---|")
    for ax in AXES:
        s = result["axis_summary"][ax]
        L.append(f"| {ax} | {AXIS_NAMES[ax]} | {_pct(s['recall5'])} | {_pct(s['recall10'])} | "
                 f"{_pct(s['grounding'])} | {s['recall_denom']} | {s['grounding_total']} |")
    L.append("")

    # empty-program control detail
    L.append("### Empty-program control detail (humanoid no-data questions)")
    L.append("")
    for c in ctrl["detail"]:
        t1 = c["top1"]
        t1s = f"{t1[0]} (score={t1[1]})" if t1 else "—"
        L.append(f"- {c['id']} [axis {c['axis']}] top-1 spurious unit: {t1s}")
    L.append("")

    # weakest axes
    weak = weakest_axes(result["axis_summary"], 3)
    L.append("## Conclusion")
    L.append("")
    if weak:
        weak_str = ", ".join(f"{ax} ({AXIS_NAMES[ax]}, score={sc:.2f})" for ax, sc in weak)
        L.append(f"- Top-3 weakest axes (mean of recall@5 + grounding): {weak_str}.")
    L.append(f"- One-line: recall@5={_pct(rc['at5'])}, grounding={_pct(gr['rate'])}; "
             f"grounded facts lean on {sd['manual_rewritten']} hand-REWRITTEN vs {sd['script_product']} "
             f"script-product notes; {gi['papers_empty_core_content']}/{gi['papers_total']} papers carry an "
             f"empty structured core_content.")
    L.append("")
    L.append("> Tier-1 measures retrieval + evidence-binding + gate integrity only. Full-answer quality "
             "(Tier-2) needs the agent+grader flow in kb/eval/research-value/TIER2_SPEC.md.")
    L.append("")
    return "\n".join(L)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    add_project_root_argument(parser)
    parser.add_argument("--program", default="", help="Restrict to one program_id (default: all datasets).")
    parser.add_argument("--tier1", action="store_true", help="Run the Tier-1 evaluation (default action).")
    parser.add_argument("--gate-integrity", action="store_true",
                        help="Only print the H1 gate-integrity scan (no Q&A).")
    parser.add_argument("--json", action="store_true", help="Emit structured JSON to stdout.")
    parser.add_argument("--no-write", action="store_true",
                        help="Do not write the report file (dry evaluation).")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    root = project_root(PROJECT_ROOT, explicit_root=args.root)
    print_resolved_project_roots(root)

    program = args.program.strip() or None
    result = evaluate(root, program)

    if args.gate_integrity:
        gi = result["gate_integrity"]
        if args.json:
            print(json.dumps(gi, ensure_ascii=False, indent=2))
        else:
            print("[H1 gate integrity]")
            print(f"  confirmation_status distribution: {gi['status_distribution']}")
            for st, v in gi["settled"].items():
                print(f"  {st}: units={v['count']} empty={v['empty']} ids={v['empty_ids']}")
            print(f"  papers with empty core_content: {gi['papers_empty_core_content']}/{gi['papers_total']}")
        return 0

    canonical_root = root if args.no_write and not root.exists() else kb_root(root)
    meta = {
        "utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "kb_head": git_short_head(canonical_root),
        "repo_head": git_short_head(root),
        "n_questions": len(result["questions"]),
        "programs": [str(p) for p in (
            [program] if program else sorted({q["program_id"] for q in result["questions"]})
        )],
        "pdf": probe_pdf_backends(),
    }

    report = render_report(root, result, meta)

    if not args.no_write:
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        report_dir = kb_root(root) / REPORT_DIRNAME
        with mutation_transaction(root, "write-research-value-report", [report_dir]):
            report_path = next_available_report_path(report_dir, stamp)
            write_text_if_changed(report_path, report)
        if not args.json:
            print(f"[ok] wrote report: {report_path.relative_to(root)}")

    if args.json:
        print(json.dumps({"meta": meta, "result": result}, ensure_ascii=False, indent=2))
    else:
        print()
        print(report)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
