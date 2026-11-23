import argparse
from societytwin.enrichment.service import build


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Explicitly opt in to separate resident attribute sidecars.")
    parser.add_argument("--enable-enrichment", action="store_true")
    parser.add_argument("--population-root", required=True)
    parser.add_argument("--population-id", required=True)
    parser.add_argument("--output-root")
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args(argv)
    print(
        build(
            args.population_root,
            args.population_id,
            enable_enrichment=args.enable_enrichment,
            seed=args.seed,
            output_root=args.output_root,
        )
    )


if __name__ == "__main__":
    main()
