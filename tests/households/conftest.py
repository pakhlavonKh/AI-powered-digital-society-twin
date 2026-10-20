"""Household tests use invented source counts, never ignored official observations."""
import csv

import pytest

from societytwin.common import sha256_file
from societytwin.households.evidence import load_evidence
from societytwin.households.registry import CLASSES, HouseholdRegistry, load_registry
from tests.national.conftest import national_settings, store  # noqa: F401 - shared artificial resident fixtures


@pytest.fixture
def registry(tmp_path):
    path=tmp_path/'artificial-households.csv'
    with path.open('w',newline='',encoding='utf-8') as f:
        writer=csv.writer(f)
        writer.writerow(['province_code','reference_year','household_size_class','households'])
        writer.writerows(('06',2025,c,v) for c,v in zip(CLASSES,range(100,0,-10)))
    payload=load_registry().model_dump(mode='json')
    payload['source'].update(source_version='ARTIFICIAL-household-counts-v1',title='ARTIFICIAL invented counts',
        source_file=str(path),sha256=sha256_file(path),expected_total=550)
    return HouseholdRegistry.model_validate(payload).activated()


@pytest.fixture
def evidence(registry,tmp_path):
    return load_evidence(registry,tmp_path)
