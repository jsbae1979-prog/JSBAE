"""Pure subprocess fixture. No exec/eval, OS child, authentication or network."""
import ast
import json
from pathlib import Path

_DURATION_ASSERT = ast.dump(ast.parse("assert json.load(sys.stdin)['duration']==30").body[0])


def script_output(code):
    output, delay, check_duration = None, False, False
    for node in ast.parse(code).body:
        if isinstance(node, ast.Import):
            if any(a.name not in {'json', 'sys', 'time'} or a.asname for a in node.names):
                raise ValueError('Unsupported fixture import')
        elif isinstance(node, ast.Assert) and ast.dump(node) == _DURATION_ASSERT:
            check_duration = True
        elif isinstance(node, ast.Expr) and isinstance(node.value, ast.Call):
            call = node.value
            if (isinstance(call.func, ast.Name) and call.func.id == 'print' and len(call.args) == 1
                    and not call.keywords and isinstance(call.args[0], ast.Constant)
                    and type(call.args[0].value) is str and output is None):
                output = call.args[0].value.encode() + b'\n'
            elif ast.dump(node) == ast.dump(ast.parse('time.sleep(10)').body[0]):
                delay = True
            else:
                raise ValueError('Unsupported fixture expression')
        else:
            raise ValueError('Unsupported fixture statement')
    if (output is None) == (not delay):
        raise ValueError('Fixture needs one output or one delay')
    return output, delay, check_duration


class FixtureProcess:
    def __init__(self, code, *, stdin, stdout):
        output, delay, check_duration = script_output(code)
        self.returncode, self.kills = (None if delay else 0), 0
        if check_duration and json.load(stdin).get('duration') != 30:
            self.returncode, output = 1, b''
        if output is not None:
            stdout.write(output)
            stdout.flush()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        if self.returncode is None:
            self.kill()
        return False

    def poll(self):
        return self.returncode

    def kill(self):
        self.kills += 1
        self.returncode = -9

    def wait(self, timeout=None):
        if self.returncode is None:
            raise AssertionError('Fake process was not terminated')
        return self.returncode


def popen_for_script(code, argv, root):
    script_output(code)  # Reject unsupported programs at configuration, never execute their text.
    def fake_popen(command, **kwargs):
        assert command == argv and kwargs.get('shell') is False
        assert Path(kwargs['cwd']).resolve().is_relative_to(root.resolve())
        return FixtureProcess(code, stdin=kwargs['stdin'], stdout=kwargs['stdout'])
    return fake_popen
