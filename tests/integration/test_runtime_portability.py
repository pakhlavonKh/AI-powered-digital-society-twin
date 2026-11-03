"""Native runtime isolation must preserve Unicode and Windows system imports."""
import json
import os
import sys
from pathlib import Path

from societytwin.agents.matraix_runtime import CLOSED_PROXY, MatraixRuntime


def test_offline_runtime_environment_stays_minimal(settings, monkeypatch):
    monkeypatch.setenv('UNRELATED_SECRET', 'must-not-leak')
    monkeypatch.setenv('PYTHONPATH', 'must-not-leak')
    env = MatraixRuntime(settings)._env(allow_network=False)
    assert 'UNRELATED_SECRET' not in env and 'PYTHONPATH' not in env
    assert env['HTTPS_PROXY'] == CLOSED_PROXY and env['NO_PROXY'] == ''
    if os.name == 'nt':
        assert env['SystemRoot'] == os.environ['SystemRoot']
        assert env['USERPROFILE'] == env['TEMP'] == env['TMP'] == str(settings.runtime_home)


def test_isolated_child_can_import_asyncio_and_read_utf8(settings):
    settings.state_dir.mkdir(parents=True, exist_ok=True)
    path = settings.state_dir / 'unicode.json'
    payload = {'text': 'Ankara / Şanlıurfa / 65–69 / Hiç evlenmedi'}
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding='utf-8')
    code = '''
import asyncio,json,sys,tempfile
from pathlib import Path
assert sys.flags.isolated and sys.flags.dont_write_bytecode and sys.flags.utf8_mode
assert asyncio.run(asyncio.sleep(0, result=42)) == 42
assert Path('~').expanduser() == Path(sys.argv[2])
if sys.platform == 'win32':
    assert Path(tempfile.gettempdir()) == Path(sys.argv[2])
print(json.dumps(json.loads(Path(sys.argv[1]).read_text()),ensure_ascii=False))
'''
    log = settings.state_dir / 'portability.log'
    result = MatraixRuntime(settings)._invoke(['-c', code, str(path), str(settings.runtime_home)], log_path=log,
                                            allow_network=False, python=Path(sys.executable))
    assert result.ok, result.error_tail
    output = log.read_text(encoding='utf-8').split('--- stdout ---\n', 1)[1].split('\n--- stderr ---', 1)[0]
    assert json.loads(output) == payload
