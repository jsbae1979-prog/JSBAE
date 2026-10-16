from pathlib import Path

import pytest
from packaging.specifiers import SpecifierSet

from newsflow.python_policy import installation_fingerprint, supported


@pytest.mark.parametrize(('version', 'allowed'), [
    ((3, 11, 9), False), ((3, 12, 10), True), ((3, 13, 1), False),
    ((3, 14, 7), True), ((3, 15, 0), False),
])
def test_metadata_and_runtime_agree(version, allowed):
    import tomllib

    metadata = tomllib.loads((Path(__file__).parents[1] / 'pyproject.toml').read_text())
    assert supported(version) is allowed
    assert ('.'.join(map(str, version)) in SpecifierSet(metadata['project']['requires-python'])) is allowed


def test_fingerprints_separate_versions_and_dependency_changes(tmp_path):
    for name in ('pyproject.toml', 'requirements-dev.lock'):
        (tmp_path / name).write_bytes(b'original')
    first = installation_fingerprint(tmp_path, (3, 12))
    assert first != installation_fingerprint(tmp_path, (3, 14))
    assert first == installation_fingerprint(tmp_path, (3, 12, 10))
    (tmp_path / 'requirements-dev.lock').write_bytes(b'changed')
    assert first != installation_fingerprint(tmp_path, (3, 12))
    with pytest.raises(ValueError, match='unsupported'):
        installation_fingerprint(tmp_path, (3, 13))
