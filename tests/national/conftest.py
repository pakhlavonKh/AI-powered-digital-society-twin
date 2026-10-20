"""Fixtures for the national pipeline. Everything runs on the ARTIFICIAL long-format package."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
PACKAGE = FIXTURES / "artificial_tuik_package"
MAPPING = FIXTURES / "artificial_tuik_package_mapping.yaml"


@pytest.fixture
def national_settings(make_settings, tmp_path):
    package = tmp_path / "data" / "raw" / "tuik_package"
    shutil.copytree(PACKAGE, package)
    return make_settings(tuik_package_dir=package, tuik_mapping_path=MAPPING)


@pytest.fixture
def store(national_settings):
    from societytwin.national.controls import read_store, write_store
    from societytwin.national.sources import build_controls

    built, _ = build_controls(national_settings)
    write_store(national_settings.national_controls_dir, built)
    return read_store(national_settings.national_controls_dir)


@pytest.fixture
def generated(store):
    from societytwin.national.generator import GenerationConfig, generate

    return generate(store, GenerationConfig(synthetic_size=5000, seed=42))


@pytest.fixture
def national_client(national_settings):
    from tests.conftest import make_client

    with make_client(national_settings) as c:
        assert c.post("/api/v2/controls/build").status_code == 200
        yield c


@pytest.fixture
def population_id(national_client) -> str:
    r = national_client.post("/api/v2/populations", json={"synthetic_size": 3000, "seed": 42})
    assert r.status_code == 201, r.text
    return r.json()["population"]["population_id"]
