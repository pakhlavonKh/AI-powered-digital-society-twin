"""Local opt-in CLI, separate from the resident CLI and public API."""
import argparse
from pathlib import Path

from societytwin.households.model import HouseholdConfig
from societytwin.households.registry import HouseholdError
from societytwin.households.service import build


def main():
    parser=argparse.ArgumentParser(description="Generate unlinked Ankara household representatives, not resident families.")
    parser.add_argument("--enable-households",action="store_true")
    parser.add_argument("--size",type=int,default=1000)
    parser.add_argument("--seed",type=int,default=42)
    parser.add_argument("--output-root",type=Path)
    parser.add_argument("--registry",type=Path)
    parser.add_argument("--type-size",action="store_true",help="Opt in to national type-size transfer and explicit within-7+ exchangeability assumption")
    parser.add_argument("--type-size-registry",type=Path)
    args=parser.parse_args()
    try:
        path=build(HouseholdConfig(synthetic_size=args.size,seed=args.seed),enable_households=args.enable_households,
                   output_root=args.output_root,registry_path=args.registry,
                   type_size=args.type_size,type_size_registry_path=args.type_size_registry)
    except (HouseholdError,ValueError) as exc:
        parser.error(str(exc))
    print(path)


if __name__ == "__main__":
    main()
