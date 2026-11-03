"""CLI portability: missing Unix telemetry must not block population commands."""
import json
import os
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

import pytest

from societytwin.national import __main__ as cli


def test_help_without_resource():
    # Exercise module import as well as argparse, including on Unix CI.
    code = """
import builtins, runpy, sys
original = builtins.__import__
def without_resource(name, *args, **kwargs):
    if name == 'resource':
        raise ModuleNotFoundError("No module named 'resource'", name='resource')
    return original(name, *args, **kwargs)
builtins.__import__ = without_resource
sys.argv = ['societytwin.national', '--help']
runpy.run_module('societytwin.national', run_name='__main__')
"""
    env = dict(os.environ, PYTHONPATH=str(Path(__file__).resolve().parents[2] / "src"))
    result = subprocess.run([sys.executable, "-B", "-c", code], capture_output=True, text=True, env=env)
    assert result.returncode == 0, result.stderr
    assert "build-controls" in result.stdout and "validate" in result.stdout


def test_missing_peak_memory_is_explicit(monkeypatch):
    monkeypatch.setattr(cli, "resource", None)
    report = cli._peak_memory()
    assert report["peak_rss"] is None and report["peak_rss_unit"] is None
    assert "unavailable" in report["peak_rss_note"]


@pytest.mark.parametrize("platform,unit", [("linux", "kilobytes"), ("darwin", "bytes")])
def test_unix_peak_memory_is_preserved(monkeypatch, platform, unit):
    calls = []

    def getrusage(who):
        calls.append(who)
        return SimpleNamespace(ru_maxrss=1234)

    monkeypatch.setattr(cli, "resource", SimpleNamespace(RUSAGE_SELF=0, getrusage=getrusage))
    monkeypatch.setattr(cli.sys, "platform", platform)
    assert cli._peak_memory() == {"peak_rss": 1234, "peak_rss_unit": unit}
    assert calls == [0]


def test_list_and_validate_without_resource(monkeypatch, capsys):
    from societytwin.national.validation import summarize

    report = {"constraint_violations": 0, "provinces": [], "calibration": []}
    service = SimpleNamespace(list_populations=lambda: {"items": []}, validation=lambda pid: report)
    monkeypatch.setattr(cli, "resource", None)
    monkeypatch.setattr(cli, "_service", lambda: service)
    assert cli.main(["list"]) == 0
    assert cli.main(["validate", "saved-population"]) == 0
    assert json.loads(capsys.readouterr().out) == summarize(report)
