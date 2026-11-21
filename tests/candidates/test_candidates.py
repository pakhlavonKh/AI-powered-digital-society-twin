import pytest

from societytwin.candidates import FIXTURE_PROGRAMS, generate, registry_programs, sample_preferences, validate_handoff
from societytwin.university import connect, initialize_database


def test_reproducible_and_varies():
    a = generate(1000, 42)
    assert a == generate(1000, 42)
    assert len(a["candidates"]) == len({c["candidate_id"] for c in a["candidates"]}) == 1000
    assert a["candidates"] != generate(1000, 43)["candidates"]
    assert a["candidates"][0]["achievement"]["kind"] == "synthetic_proxy"
    assert a["preferences"] == []


def test_fixture_handoff_and_invalid_lists():
    candidates = generate(2, 42)["candidates"]
    prefs = sample_preferences(candidates)
    validate_handoff(candidates, prefs, set(FIXTURE_PROGRAMS))
    bad = [
        [{**prefs[0], "candidate_id": "missing"}],
        [{**prefs[0], "program_id": "missing"}],
        [prefs[0], {**prefs[1], "program_id": prefs[0]["program_id"]}],
        [prefs[0], {**prefs[1], "position": 1}],
        [{**prefs[0], "position": 2}],
        [{**prefs[0], "position": True}],
    ]
    for records in bad:
        with pytest.raises(ValueError):
            validate_handoff(candidates, records, set(FIXTURE_PROGRAMS))
    with pytest.raises(ValueError):
        validate_handoff(candidates + candidates[:1], [], set())


def test_registry_snapshot_and_codes(tmp_path):
    path = tmp_path / "registry.sqlite3"
    initialize_database(path)
    with connect(path) as conn:
        conn.execute("INSERT INTO source_snapshots (snapshot_id, source_filename, file_sha256, imported_at, importer_version) VALUES ('s1', 'fixture', ?, '2026', 'test')", ('a' * 64,))
        conn.execute("INSERT INTO universities (university_id, snapshot_id, university_key, name_original, name_normalized) VALUES (1, 's1', 'u', 'U', 'U')")
        conn.execute("INSERT INTO programs (snapshot_id, university_id, program_code, name_original, source_sheet, source_row) VALUES ('s1', 1, '00123', 'Test', 'fixture', 1)")
    codes = registry_programs(str(path), 's1')
    assert codes == {'00123'}
    validate_handoff(generate(1, 1)['candidates'], [{'candidate_id': 'candidate-00000001', 'program_id': '00123', 'position': 1}], codes)
    with pytest.raises(ValueError):
        registry_programs(str(path), 'missing')
    with pytest.raises(ValueError):
        registry_programs(str(tmp_path / 'missing'), 's1')


@pytest.mark.parametrize('size,seed', [(0, 1), (-1, 1), (1, -1), (1, True)])
def test_invalid_config(size, seed):
    with pytest.raises(ValueError):
        generate(size, seed)
