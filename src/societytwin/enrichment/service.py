"""Internal opt-in entry point; no public API or default pipeline integration."""
from pathlib import Path

from societytwin.enrichment.engine import generate
from societytwin.enrichment.model import EnrichmentConfig
from societytwin.enrichment.registry import EnrichmentError, REPO_ROOT, load_registry
from societytwin.enrichment.store import ExtensionStore
from societytwin.national.store import PopulationStore


def build(population_root,population_id,*,enable_enrichment=False,seed=42,registry_path=None,output_root=None):
    if not enable_enrichment:raise EnrichmentError('optional resident enrichment disabled; explicit opt-in required')
    output=Path(output_root or REPO_ROOT/'data/results/resident_extensions').resolve()
    allowed=(REPO_ROOT/'data/results').resolve()
    if not output.is_relative_to(allowed):raise EnrichmentError('sidecar output must use a separate ignored data/results directory')
    if output.is_relative_to(Path(population_root).resolve()) or Path(population_root).resolve().is_relative_to(output):
        raise EnrichmentError('resident and sidecar storage roots must be separate')
    registry=load_registry(registry_path).activated()
    core=PopulationStore(Path(population_root)).load(population_id)
    extension=generate(core,registry,EnrichmentConfig(seed=seed))
    return ExtensionStore(output).write(extension,core)
