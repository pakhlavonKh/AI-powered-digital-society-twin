"""Prepare -> generate with existing components -> validate -> atomically publish."""
import json
import platform
from importlib.metadata import version
from pathlib import Path
from tempfile import TemporaryDirectory

from societytwin.common import canonical_hash, sha256_file
from societytwin.build import WORKFLOW_VERSION, MANIFEST_VERSION
from societytwin.build.config import BuildConfig, BuildError, REPO_ROOT, resolve
from societytwin.national import geography
from societytwin.national.controls import read_store
from societytwin.national.dependencies import DependencyRegistry, load_registry, compile_compatibility
from societytwin.national.generator import GenerationConfig, generate
from societytwin.national.store import PopulationStore
from societytwin.national.validation import ValidationTolerances, validate, summarize


def _write(path, payload):
    path.write_text(json.dumps(payload, sort_keys=True, ensure_ascii=False, indent=2, allow_nan=False)+'\n', encoding='utf-8')


def _inventory(directory):
    return {p.relative_to(directory).as_posix():sha256_file(p) for p in sorted(directory.rglob('*'))
            if p.is_file() and p != directory/'build-manifest.json'}


def _output(config):
    output = resolve(config.output_root)
    if not output.is_relative_to((REPO_ROOT/'data/results').resolve()):
        raise BuildError('unified output must be under ignored feature-worktree data/results')
    for parent in (output, *output.parents):
        if any((parent/name).exists() for name in ('records.parquet','households.parquet','attributes.parquet','build-manifest.json')):
            raise BuildError('unified output cannot be inside an existing artifact')
    inputs = [resolve(p) for p in config.inputs.model_dump().values()]
    if any(p.is_relative_to(output) or output.is_relative_to(p) for p in inputs):
        raise BuildError('unified output overlaps configured inputs')
    return output


def prepare(config):
    """Validate configuration and all selected source files before any generation/write."""
    config = BuildConfig.model_validate(config.model_dump(mode='json'))
    _output(config)
    controls_path = resolve(config.inputs.controls_directory)
    controls = read_store(controls_path)
    resident = load_registry(resolve(config.inputs.resident_registry))
    payload = resident.model_dump(mode='json')
    if payload.get('marital_strategy'):
        payload['marital_strategy']['enabled'] = config.marital.strategy != 'default'
    if config.marital.strategy != 'default':
        if not payload.get('marital_strategy'):
            raise BuildError('resident registry does not declare the requested marital strategy')
        payload['marital_strategy'].update(zero_variant=config.marital.sensitivity, acknowledge_unverified_rounding=True)
    resident = DependencyRegistry.model_validate(payload)
    compile_compatibility(resident)
    resident.validate_controls(controls)
    root = controls.best('population_age_sex', geography.province(config.province_code), config.reference_year)
    if root is None or (root.geo_level,root.geo_code,root.year) != ('province','06',2025):
        raise BuildError('unified Ankara build requires observed province-level 2025 age/sex root')
    registries = {'resident':resident.model_dump(mode='json')}
    prepared = {'controls':controls, 'resident':resident}
    if config.marital.strategy != 'default':
        from societytwin.national.marital import transferred_conditionals
        # Existing adapter verifies observations, universes, rounding policy and IPF feasibility.
        prepared['marital_preflight'] = transferred_conditionals(controls,geography.province('06'),root,2025,resident.marital_strategy)
    if config.resident_enrichments:
        from societytwin.enrichment.registry import load_registry as load_extension, ExtensionRegistry
        from societytwin.enrichment.evidence import load_evidence
        extension = load_extension(resolve(config.inputs.enrichment_registry)).activated()
        if extension.parent_registry_version != resident.registry_version:
            raise BuildError('enrichment registry incompatible with selected resident registry version')
        data = extension.model_dump(mode='json')
        data['attributes'] = {n:a for n,a in data['attributes'].items() if n in config.resident_enrichments}
        if set(data['attributes']) != set(config.resident_enrichments):
            raise BuildError('requested enrichment not declared in registry')
        extension = ExtensionRegistry.model_validate(data)
        prepared['extension'] = extension
        prepared['extension_evidence'] = {n:load_evidence(a,REPO_ROOT) for n,a in extension.attributes.items()}
        registries['enrichment'] = extension.model_dump(mode='json')
    if config.households.enabled:
        from societytwin.households.registry import load_registry as load_households, parent_binding
        from societytwin.households.evidence import load_evidence
        hh = load_households(resolve(config.inputs.household_registry)).activated()
        if hh.parent_registry_version != resident.registry_version:
            raise BuildError('household registry incompatible with selected resident registry version')
        parent_binding(hh)
        prepared['household'] = hh
        prepared['household_evidence'] = load_evidence(hh,REPO_ROOT)
        registries['household'] = hh.model_dump(mode='json')
        if config.households.strategy != 'size_only':
            from societytwin.households.type_size_registry import load_type_size_registry
            from societytwin.households.type_size_evidence import load_type_size_evidence
            joint = load_type_size_registry(resolve(config.inputs.household_type_registry)).activated()
            prepared['joint'] = joint
            prepared['joint_evidence'] = load_type_size_evidence(joint,hh,prepared['household_evidence'],REPO_ROOT)
            registries['household_type'] = joint.model_dump(mode='json')
    code = {p.relative_to(REPO_ROOT).as_posix():sha256_file(p) for p in sorted((REPO_ROOT/'src/societytwin').rglob('*.py'))}
    controls_manifest = json.loads((controls_path/'manifest.json').read_text(encoding='utf-8'))
    configuration = config.model_dump(mode='json', exclude={'output_root','inputs'})
    identity = {'workflow_version':WORKFLOW_VERSION,'manifest_version':MANIFEST_VERSION,'configuration':configuration,
                'registries':registries,'controls':{'fingerprint':controls.fingerprint,'files':controls_manifest['files'],
                'sources':controls.sources,'inputs':controls.inputs},'implementation_sha256':canonical_hash(code),
                'runtime':{'python':platform.python_version(),**{n:version(n) for n in ('pyarrow','pydantic','PyYAML')}}}
    # Files and source statuses are pinned, including explicit optional-source unavailability.
    if 'extension_evidence' in prepared:identity['enrichment_evidence'] = prepared['extension_evidence']
    prepared['identity'] = identity
    prepared['build_id'] = 'build-'+canonical_hash(identity)
    return prepared


def inspect_build(directory):
    """Verify a complete immutable set without needing source downloads."""
    directory = Path(directory)
    if directory.is_symlink():raise BuildError('build directory cannot be a symlink')
    manifest = json.loads((directory/'build-manifest.json').read_text(encoding='utf-8'))
    if manifest['manifest_version'] != MANIFEST_VERSION or manifest['build_id'] != 'build-'+canonical_hash(manifest['identity']):
        raise BuildError('unified manifest version/identity mismatch')
    if directory.name != manifest['build_id']:raise BuildError('unified build directory identity mismatch')
    if any(p.is_symlink() for p in directory.rglob('*')):raise BuildError('build files cannot be symlinks')
    if _inventory(directory) != manifest['files']:raise BuildError('unified build incomplete or checksums differ')
    artifacts = manifest['artifacts']
    core_id = artifacts['residents']['id']
    core = PopulationStore(directory/'residents').load(core_id)
    expected = {'residents'}
    configuration = manifest['identity']['configuration']
    if (len(core.table) != configuration['resident_sample_size'] or core.manifest['config']['seed'] != configuration['seed']
            or core.manifest['content_sha256'] != artifacts['residents']['content_sha256']):
        raise BuildError('resident artifact configuration/content mismatch')
    if configuration['resident_enrichments']:
        from societytwin.enrichment.store import ExtensionStore
        sidecar = ExtensionStore(directory/'enrichments').load(artifacts['enrichments']['id'],core)
        if sidecar.manifest['content_hash'] != artifacts['enrichments']['content_sha256']:
            raise BuildError('enrichment artifact content mismatch')
        expected.add('enrichments')
    if configuration['households']['enabled']:
        if configuration['households']['strategy'] == 'size_only':
            from societytwin.households.store import HouseholdStore as Store
        else:
            from societytwin.households.type_size_store import TypeSizeStore as Store
        household = Store(directory/'households').load(artifacts['households']['id'])
        if (len(household.records) != configuration['households']['sample_size']
                or household.manifest['content_sha256'] != artifacts['households']['content_sha256']
                or artifacts['households']['linked_residents'] != 0):
            raise BuildError('household artifact configuration/content/linkage mismatch')
        expected.add('households')
    if set(artifacts) != expected or manifest['household_person_linkage'] is not False:
        raise BuildError('unified artifact selection/linkage mismatch')
    for name,artifact in artifacts.items():
        if artifact['path'] != f"{name}/{artifact['id']}":raise BuildError('invalid artifact path')
    if json.loads((directory/'validation.json').read_text(encoding='utf-8')) != manifest['validation']:
        raise BuildError('unified validation differs from saved results')
    return manifest


def _execute(stage, config, prepared):
    resident = generate(prepared['controls'],GenerationConfig(reference_year=config.reference_year,
        synthetic_size=config.resident_sample_size,seed=config.seed,provinces=(config.province_code,)),registry=prepared['resident'])
    options = config.validation
    report = validate(resident.columns,resident.manifest,prepared['controls'],ValidationTolerances(
        calibration_relative=options.calibration_relative,familywise_alpha=options.familywise_alpha,
        min_group_records_for_noise_test=options.min_group_records_for_noise_test))
    summary = summarize(report)
    if options.fail_on_constraint_violations and summary['constraint_violations']:
        raise BuildError('resident structural constraint violations; build not published')
    if options.fail_on_unfitted_margins and summary['margins_not_calibrated']:
        raise BuildError('resident margins not calibrated; strict build not published')
    core_store = PopulationStore(stage/'residents')
    saved,_ = core_store.write(resident,report)
    core = core_store.load(saved['population_id'])
    artifacts = {'residents':{'id':core.population_id,'path':f'residents/{core.population_id}',
                              'unit':'person','content_sha256':saved['content_sha256']}}
    validation = {'residents':summary}
    if config.resident_enrichments:
        from societytwin.enrichment.engine import generate as enrich, validate as check_extension
        from societytwin.enrichment.model import EnrichmentConfig
        from societytwin.enrichment.store import ExtensionStore
        extension = enrich(core,prepared['extension'],EnrichmentConfig(seed=config.seed))
        # Reject sources changing between preflight and assignment, even for unavailable policy.
        if extension.manifest['evidence'] != prepared['extension_evidence']:
            raise BuildError('enrichment sources changed during build')
        path = ExtensionStore(stage/'enrichments').write(extension,core)
        artifacts['enrichments'] = {'id':path.name,'path':f'enrichments/{path.name}','unit':'person_sidecar',
                                   'content_sha256':extension.manifest['content_hash']}
        validation['enrichments'] = check_extension(extension,core)
    if config.households.enabled:
        from societytwin.households.model import HouseholdConfig
        hh_config = HouseholdConfig(synthetic_size=config.households.sample_size,seed=config.seed)
        if config.households.strategy == 'size_only':
            from societytwin.households.generator import generate as generate_households
            from societytwin.households.store import HouseholdStore
            households = generate_households(prepared['household_evidence'],hh_config,prepared['household'])
            store = HouseholdStore(stage/'households')
        else:
            from societytwin.households.type_size import generate_type_size
            from societytwin.households.type_size_store import TypeSizeStore
            households = generate_type_size(prepared['household_evidence'],prepared['joint_evidence'],hh_config,
                                            prepared['household'],prepared['joint'])
            store = TypeSizeStore(stage/'households')
        path = store.write(households)
        store.load(path.name)
        artifacts['households'] = {'id':path.name,'path':f'households/{path.name}','unit':'household',
                                  'linked_residents':0,'content_sha256':households.manifest['content_sha256']}
        validation['households'] = store.check(households)
    _write(stage/'validation.json',validation)
    manifest = {'manifest_version':MANIFEST_VERSION,'build_id':prepared['build_id'],'identity':prepared['identity'],
                'artifacts':artifacts,'validation':validation,'household_person_linkage':False,
                'reproducibility':'Records, weights and IDs deterministic. Existing resident timestamps/timings are operational metadata.',
                'files':_inventory(stage)}
    _write(stage/'build-manifest.json',manifest)


def build(config):
    """Publish once; errors leave no partially published bundle or existing-artifact edits."""
    prepared = prepare(config)
    output = _output(config)
    target = output/prepared['build_id']
    if target.exists():
        manifest = inspect_build(target)
        if manifest['identity'] != prepared['identity']:raise BuildError('unified build identity collision')
        return target
    output.mkdir(parents=True,exist_ok=True)
    with TemporaryDirectory(prefix='.unified-staging-',dir=output) as temporary:
        stage = Path(temporary)/prepared['build_id']
        stage.mkdir()
        _execute(stage,config,prepared)
        inspect_build(stage)
        try:
            stage.rename(target)
        except FileExistsError:
            inspect_build(target)
    return target
