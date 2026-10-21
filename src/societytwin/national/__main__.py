"""Command line for the national pipeline.

    python -m societytwin.national build-controls
    python -m societytwin.national generate --size 10000 --seed 42 [--province 06] [--reference-year 2025]
    python -m societytwin.national list
    python -m societytwin.national validate POPULATION_ID
    python -m societytwin.national benchmark --sizes 10000 100000 [--province 06]
"""

from __future__ import annotations

import argparse
import json
try:
    import resource
except ImportError:
    resource = None
import sys
import time

from societytwin.config import load_settings


def _service():
    from societytwin.agents.matraix_runtime import MatraixRuntime
    from societytwin.national.service import NationalService
    from societytwin.registry.store import Registry

    settings = load_settings()
    settings.state_dir.mkdir(parents=True, exist_ok=True)
    return NationalService(settings, Registry(settings.registry_path), MatraixRuntime(settings))


def _config(args):
    from societytwin.national.generator import GenerationConfig

    return GenerationConfig(reference_year=args.reference_year, synthetic_size=getattr(args, "size", 1), seed=args.seed,
                            provinces=tuple(args.province) if args.province else None,
                            min_records_per_province=args.min_per_province, calibrate=not args.no_calibrate)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m societytwin.national", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("build-controls", help="Normalise available official tables into the standard control store")
    gen = sub.add_parser("generate", help="Generate (or reuse) a synthetic population and validate it")
    bench = sub.add_parser("benchmark", help="Time generation, validation, storage and queries at several sizes")
    for p in (gen, bench):
        p.add_argument("--seed", type=int, default=42)
        p.add_argument("--province", action="append", help="Plate code (repeatable); omit for every covered province")
        p.add_argument("--reference-year", type=int, default=2025)
        p.add_argument("--min-per-province", type=int, default=0)
        p.add_argument("--no-calibrate", action="store_true")
    gen.add_argument("--size", type=int, default=10_000)
    bench.add_argument("--sizes", type=int, nargs="+", default=[10_000, 100_000])
    sub.add_parser("list", help="List generated populations")
    val = sub.add_parser("validate", help="Print the source-fit validation summary of a population")
    val.add_argument("population_id")
    args = parser.parse_args(argv)
    service = _service()

    if args.command == "build-controls":
        out = service.build_controls()
        print(json.dumps(out, ensure_ascii=False, indent=2))
        return 0
    if args.command == "generate":
        out = service.generate(_config(args))
        print(json.dumps(out, ensure_ascii=False, indent=2, default=str))
        return 0
    if args.command == "list":
        for item in service.list_populations()["items"]:
            print(f"{item['population_id']}  records={item['synthetic_size']}  provinces={item['scope']['province_count']}  "
                  f"represented={item['represented_population']:.0f}  generated={item['generated_at']}")
        return 0
    if args.command == "validate":
        from societytwin.national.validation import summarize

        report = service.validation(args.population_id)
        print(json.dumps(summarize(report), indent=2))
        for scope in report["provinces"]:
            for t in scope["tables"]:
                s = t.get("summary", {})
                print(f"{scope['province_code']} {t['table_id']:<24} weighted={t.get('weighted_status', t.get('status'))} "
                      f"records={t.get('record_status', '-')} max|pp|w={s.get('max_abs_pp_error_weighted', 0):.4f} "
                      f"max|pp|r={s.get('max_abs_pp_error_records', 0):.4f} tvd_r={s.get('tvd_records', 0):.4f}")
        return 0
    if args.command == "benchmark":
        return _benchmark(service, args)
    return 1


def _benchmark(service, args) -> int:
    import dataclasses

    from societytwin.national.cohorts import CohortSampleRequest, draw
    from societytwin.national.generator import generate
    from societytwin.national.store import PopulationFilter, distribution, page
    from societytwin.national.validation import validate

    store = service.store()
    rows = []
    for size in args.sizes:
        config = dataclasses.replace(_config(args), synthetic_size=size)
        t0 = time.perf_counter()
        pop = generate(store, config)
        t1 = time.perf_counter()
        report = validate(pop.columns, pop.manifest, store)
        t2 = time.perf_counter()
        manifest, _ = service.populations.write(pop, report)
        t3 = time.perf_counter()
        service.populations._cache.clear()
        loaded = service.populations.load(manifest["population_id"])
        t4 = time.perf_counter()
        spec = PopulationFilter(adult_only=True, sexes=["female"])
        table = loaded.filtered(spec)
        for f in ("age_group", "sex", "marital_status"):
            distribution(table, f)
        t5 = time.perf_counter()
        page(table, "age", "desc", 0, 50)
        t6 = time.perf_counter()
        draw(table["synthetic_id"].to_pylist(), table["population_weight"].to_pylist(), CohortSampleRequest(size=100, seed=1))
        t7 = time.perf_counter()
        size_bytes = manifest["files"]["records.parquet"]["bytes"]
        rows.append({"size": size, "generate_s": round(t1 - t0, 3), "validate_s": round(t2 - t1, 3), "write_s": round(t3 - t2, 3),
                     "load_s": round(t4 - t3, 3), "filter_and_3_distributions_s": round(t5 - t4, 3), "sorted_page_s": round(t6 - t5, 3),
                     "pps_sample_100_s": round(t7 - t6, 3), "parquet_bytes": size_bytes, "population_id": manifest["population_id"],
                     "constraint_violations": report["constraint_violations"]})
    peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss if resource else 0
    print(json.dumps({"rows": rows, "peak_rss": peak, "peak_rss_unit": "bytes" if sys.platform == "darwin" else "kilobytes",
                      "python": sys.version.split()[0]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
