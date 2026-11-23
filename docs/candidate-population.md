# Candidate Population Engine: development handoff

This separate synthetic cohort does not change resident generation. It is a development fixture, not a representative YKS population. The generator reuses the national engine's versioned SHA-256 counter stream; each attribute has a separate namespace. The JSON manifest records the generator and stream versions, seed, size, data version, missing evidence and assumptions. Same versions, seed and configuration reproduce the entire output. IDs are cohort-local; use the manifest to identify a cohort, not an ID alone across cohorts.

Age is uniformly sampled from 17–25; score type uniformly from SAY, EA, SOZ and DIL; and achievement is an independently sampled integer proxy from 0–10000, higher better. These are arbitrary development assumptions, not observed applicant distributions, YKS scores, ranks, or evidence of eligibility. They do not model multiple score types per applicant. Location, interests and annual budget in TRY are null, meaning unknown, not zero. Applicant age, location, financial characteristics, interests, exam outcomes, score-type distributions and their relationships all lack applicant evidence. The resident population aggregates are not applicant aggregates; program-level historical last-placed ranks are outcomes, not a distribution of applicants. Neither is used as a calibration target. The output reports observed counts and deviations from the assumed age and score-type distributions, explicitly distinguishing these from evidence-backed comparisons. No applicable applicant aggregate was found in the repository.

## Placement contract

`Candidate` and `Preference` are dataclasses serialized as JSON objects. A preference has `candidate_id`, `program_id` and a positive, contiguous one-based `position`. `program_id` is the registry's text `program_code` (including leading zeros), interpreted together with the chosen `registry_snapshot` in the handoff manifest. SQLite integer IDs are snapshot-local and unsuitable as durable identifiers. Use `registry_programs(database, snapshot_id)` to obtain the code set from the existing university SQLite registry, then `validate_handoff(candidates, preferences, codes)`. It checks known and unique candidate IDs, known program codes, unique programs and contiguous unique positions. Empty lists are valid. The registry is a snapshot, not necessarily a validated decision-time catalogue; cross-snapshot identity is unresolved. Pakhlavon owns eligibility, score-type restrictions, quotas, ties and allocation outcomes; structural validation does not implement those rules.

The optional CLI example uses only `fixture:synthetic-programs-v1` and artificial codes `000000001`, `000000002`, `000000003`. It emits two illustrative preferences for the first candidate, not modeled choices. Agree who supplies actual ranked simulation preferences and how candidate score types, real score/rank semantics, catalogue snapshot selection and decision-time information are represented before integrating placement. The JSON's empty default preferences do not imply an applicant has no real preferences.

## Reproduce

From the repository root in PowerShell, with the repository environment installed:

```powershell
$env:PYTHONPATH = 'src'
python -m societytwin.candidates --size 1000 --seed 42 --sample-preferences --output data/processed/candidates/cohort-1000.json
python -m societytwin.candidates --size 10000 --seed 42 --output data/processed/candidates/cohort-10000.json
python -m pytest tests/candidates tests/university tests/national/test_generator_and_validation.py -q
```

Generated files are ignored by Git. Do not interpret sample preferences or generated proxies as actual YKS data.
