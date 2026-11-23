"""Synthetic applicant generation and structural placement handoff."""
from __future__ import annotations

from collections import Counter, defaultdict
from contextlib import closing
from dataclasses import asdict, dataclass

from societytwin.national.rng import MAX_SEED, STREAM_VERSION, Stream
from societytwin.university import connect

VERSION = "candidate-development-v1"
FIXTURE_SNAPSHOT = "fixture:synthetic-programs-v1"
FIXTURE_PROGRAMS = ("000000001", "000000002", "000000003")


@dataclass(frozen=True)
class Candidate:
    candidate_id: str
    age: int
    home_location: str | None
    score_type: str | None
    achievement: dict | None
    educational_interests: list[str] | None
    annual_budget_try: int | None


@dataclass(frozen=True)
class Preference:
    candidate_id: str
    program_id: str  # Registry program_code, not SQLite's snapshot-local integer row ID.
    position: int


def registry_programs(database: str, snapshot_id: str) -> set[str]:
    """Read program codes for one explicitly selected registry snapshot."""
    # Refuse missing databases: sqlite connect normally creates a new empty file.
    from pathlib import Path
    if not Path(database).is_file():
        raise ValueError("registry database does not exist")
    with closing(connect(database)) as conn:
        if not conn.execute("SELECT 1 FROM source_snapshots WHERE snapshot_id=?", (snapshot_id,)).fetchone():
            raise ValueError("unknown registry snapshot")
        return {row[0] for row in conn.execute("SELECT program_code FROM programs WHERE snapshot_id=?", (snapshot_id,))}


def generate(size: int, seed: int) -> dict:
    if type(size) is not int or size < 1:
        raise ValueError("size must be a positive integer")
    if type(seed) is not int or not 0 <= seed <= MAX_SEED:
        raise ValueError("invalid seed")
    ages = Stream("candidate:age:v1", seed)
    types = Stream("candidate:score-type:v1", seed)
    proxies = Stream("candidate:achievement:v1", seed)
    score_types = ("SAY", "EA", "SOZ", "DIL")
    candidates = [Candidate(
        candidate_id=f"candidate-{i + 1:08d}", age=17 + ages.below(9), home_location=None,
        score_type=score_types[types.below(len(score_types))],
        achievement={"kind": "synthetic_proxy", "value": proxies.below(10001),
                     "scale": "integer 0..10000; higher is better; not a YKS score or rank"},
        educational_interests=None, annual_budget_try=None,
    ) for i in range(size)]
    age_counts = Counter(c.age for c in candidates)
    type_counts = Counter(c.score_type for c in candidates)
    return {"manifest": {
        "generator_version": VERSION, "stream_version": STREAM_VERSION,
        "configuration": {"size": size, "seed": seed}, "data_versions": {"applicant_data": None},
        "evidence": {"applicant_distributions": "none available; no empirical applicant calibration"},
        "assumptions": {
            "age": "development assumption: uniform integers 17..25 inclusive",
            "score_type": "development assumption: uniform SAY, EA, SOZ, DIL labels; not a statement of eligibility",
            "achievement": "development assumption: independent uniform synthetic proxy 0..10000, higher better; not a score or rank",
            "relationships": "independent draws; joint relationships are unsupported",
            "unknowns": "home location, educational interests and annual budget are unknown (null)",
        },
    }, "candidates": [asdict(c) for c in candidates], "preferences": [],
        "validation": {"count": size, "unique_candidate_ids": len({c.candidate_id for c in candidates}),
            "distribution_comparison": {"status": "no relevant applicant aggregate available; not calibrated",
                "age_vs_assumption": {str(a): {"observed_count": age_counts[a], "expected_count": size / 9,
                    "difference_count": age_counts[a] - size / 9} for a in range(17, 26)},
                "score_type_vs_assumption": {t: {"observed_count": type_counts[t], "expected_count": size / 4,
                    "difference_count": type_counts[t] - size / 4} for t in score_types}}}}


def validate_handoff(candidates: list[dict], preferences: list[dict], program_ids: set[str]) -> None:
    ids = [c.get("candidate_id") for c in candidates]
    if any(not isinstance(i, str) or not i.strip() for i in ids) or len(set(ids)) != len(ids):
        raise ValueError("candidate IDs must be unique nonempty strings")
    known = set(ids)
    positions = defaultdict(set)
    programs = defaultdict(set)
    for p in preferences:
        cid, program, position = p.get("candidate_id"), p.get("program_id"), p.get("position")
        if cid not in known or program not in program_ids:
            raise ValueError("unknown candidate or program ID")
        if type(position) is not int or position < 1:
            raise ValueError("preference positions must be positive integers")
        if position in positions[cid] or program in programs[cid]:
            raise ValueError("duplicate position or program")
        positions[cid].add(position)
        programs[cid].add(program)
    for values in positions.values():
        if values != set(range(1, len(values) + 1)):
            raise ValueError("preference positions must be contiguous from 1")


def sample_preferences(candidates: list[dict]) -> list[dict]:
    """Artificial demonstration only, never a behavioral model."""
    if not candidates:
        return []
    return [asdict(Preference(candidates[0]["candidate_id"], code, pos))
            for pos, code in enumerate(FIXTURE_PROGRAMS[:2], 1)]
