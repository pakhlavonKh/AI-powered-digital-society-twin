"""Internal household-only entry point; no national service/API/settings changes."""
from pathlib import Path

from societytwin.common import is_within
from societytwin.households.evidence import load_evidence
from societytwin.households.generator import generate
from societytwin.households.model import HouseholdConfig
from societytwin.households.registry import REPO_ROOT, HouseholdError, load_registry
from societytwin.households.store import HouseholdStore


def build(config: HouseholdConfig, *, enable_households: bool = False, output_root: Path | None = None,
          registry_path: Path | None = None, repo_root: Path = REPO_ROOT,
          type_size: bool = False, type_size_registry_path: Path | None = None) -> Path:
    if enable_households is not True:
        raise HouseholdError("household module disabled by default; pass enable_households=True explicitly")
    root = (output_root or repo_root/"data/households").resolve()
    allowed = [repo_root/"data/households",repo_root/"data/results"]
    if not any(is_within(root,p) for p in allowed) or any((p/"records.parquet").exists() for p in [root,*root.parents]):
        raise HouseholdError("household outputs must be separate, under data/households or disposable data/results")
    registry = load_registry(registry_path).activated()
    if type_size:
        from societytwin.households.type_size import generate_type_size
        from societytwin.households.type_size_evidence import load_type_size_evidence
        from societytwin.households.type_size_registry import load_type_size_registry
        from societytwin.households.type_size_store import TypeSizeStore
        optional=load_type_size_registry(type_size_registry_path).activated()
        evidence=load_evidence(registry,repo_root)
        joint=load_type_size_evidence(optional,registry,evidence,repo_root)
        return TypeSizeStore(root).write(generate_type_size(evidence,joint,config,registry,optional))
    population = generate(load_evidence(registry,repo_root),config,registry)
    return HouseholdStore(root).write(population)
