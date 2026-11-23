"""Build a reproducible development applicant cohort as JSON."""
import argparse
import json
from pathlib import Path

from societytwin.candidates import FIXTURE_PROGRAMS, FIXTURE_SNAPSHOT, generate, sample_preferences, validate_handoff


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--size", type=int, default=1000)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--output", required=True)
    parser.add_argument("--sample-preferences", action="store_true", help="include explicitly artificial fixture preferences")
    args = parser.parse_args()
    result = generate(args.size, args.seed)
    if args.sample_preferences:
        result["preferences"] = sample_preferences(result["candidates"])
        result["manifest"]["preference_source"] = "artificial demonstration fixture; not simulation preferences"
        result["manifest"]["registry_snapshot"] = FIXTURE_SNAPSHOT
    else:
        result["manifest"]["preference_source"] = "none"
        result["manifest"]["registry_snapshot"] = None
    validate_handoff(result["candidates"], result["preferences"], set(FIXTURE_PROGRAMS))
    path = Path(args.output)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(path), "count": len(result["candidates"]), "preferences": len(result["preferences"]), "seed": args.seed}))


if __name__ == "__main__":
    main()
