"""Exercise the pure CLI fixture and its boundaries, without launching a child."""
import io
import json

import pytest
from cli_process_fixture import FixtureProcess, popen_for_script, script_output


@pytest.mark.parametrize('code', [
    "import os\nprint('x')", "__import__('os').system('whoami')", "open('outside','w')",
    "import time\ntime.sleep(1)", "print('x')\nprint('y')", "print('x')\ntime.sleep(10)",
])
def test_unsupported_fixture_programs_are_rejected_without_execution(code):
    with pytest.raises(ValueError):
        script_output(code)


def test_fixture_output_preserves_payload_assertion_and_never_executes():
    code = "import json,sys\nassert json.load(sys.stdin)['duration']==30\nprint('{\"structured_output\": {}}')"
    output = io.BytesIO()
    process = FixtureProcess(code, stdin=io.BytesIO(b'{"duration":30}'), stdout=output)
    assert process.poll() == 0
    assert json.loads(output.getvalue()) == {'structured_output': {}}
    bad = io.BytesIO()
    assert FixtureProcess(code, stdin=io.BytesIO(b'{"duration":45}'), stdout=bad).returncode == 1
    assert bad.getvalue() == b''


def test_delayed_fake_requires_cleanup_and_tracks_termination():
    process = FixtureProcess('import time\ntime.sleep(10)', stdin=io.BytesIO(), stdout=io.BytesIO())
    assert process.poll() is None
    with pytest.raises(AssertionError):
        process.wait(timeout=1)
    process.kill()
    assert process.wait(timeout=10) == -9 and process.kills == 1


def test_stub_is_scoped_to_the_expected_argv_and_never_accepts_shell(tmp_path):
    argv = ['synthetic-python', 'fake_cli.py']
    factory = popen_for_script("print('ok')", argv, tmp_path)
    kwargs = {'cwd': tmp_path, 'shell': False, 'stdin': io.BytesIO(b'{}'), 'stdout': io.BytesIO()}
    assert factory(argv, **kwargs).poll() == 0
    with pytest.raises(AssertionError):
        factory(['other-program'], **kwargs)
    with pytest.raises(AssertionError):
        factory(argv, **{**kwargs, 'shell': True})
    with pytest.raises(AssertionError):
        factory(argv, **{**kwargs, 'cwd': tmp_path.parent})
