"""Read installed distribution METADATA only; do not import the app/packages."""
from __future__ import annotations

from collections import deque
from importlib import metadata

from packaging.requirements import Requirement
from packaging.utils import canonicalize_name


def resolve(requirements, environment, reader):
    """Resolve installed runtime closure, preserving every constraint and marker.

    Reader returns (version, Requires-Dist list, wheel tags). No pip/download/
    installation. Missing/conflicting dependencies abort instead of inventing pins.
    """
    queue = deque((value, '<project>', frozenset()) for value in requirements)
    rows, visited = {}, set()
    while queue:
        text, parent, active_extras = queue.popleft()
        requirement = Requirement(text)
        if requirement.marker and not any(requirement.marker.evaluate({**environment, 'extra': extra})
                                          for extra in active_extras | {''}):
            continue
        name = canonicalize_name(requirement.name)
        if name not in rows:
            installed, dependencies, tags = reader(name)
            rows[name] = {'name': name, 'version': installed, 'requirements': [], 'wheelTags': tags}
        row = rows[name]
        if requirement.url or not requirement.specifier.contains(row['version'], prereleases=True):
            raise ValueError('unresolved-runtime-constraint:' + name)
        edge = {'from': parent, 'requirement': text}
        if edge not in row['requirements']:
            row['requirements'].append(edge)
        extras = frozenset(requirement.extras)
        key = name, extras
        if key in visited:
            continue
        visited.add(key)
        _, dependencies, _ = reader(name)
        queue.extend((value, name, extras) for value in dependencies)
    return sorted(rows.values(), key=lambda row: row['name'])


def installed_reader(name):
    dist = metadata.distribution(name)
    wheel = dist.read_text('WHEEL') or ''
    tags = [line[5:] for line in wheel.splitlines() if line.startswith('Tag: ')]
    return dist.version, dist.requires or [], tags


def metadata_reader(paths):
    """Use one reviewed build environment; never mix arbitrary user packages."""
    distributions = {canonicalize_name(dist.metadata['Name']): dist
                     for dist in metadata.distributions(path=[str(path) for path in paths])}
    def read(name):
        if name not in distributions:
            raise metadata.PackageNotFoundError(name)
        dist = distributions[name]
        wheel = dist.read_text('WHEEL') or ''
        return dist.version, dist.requires or [], [line[5:] for line in wheel.splitlines() if line.startswith('Tag: ')]
    return read
