"""The installed command names and the functions they run."""

from pathlib import Path
import tomllib

PYPROJECT = Path(__file__).resolve().parents[2] / 'pyproject.toml'


def scripts():
    with PYPROJECT.open('rb') as f:
        return tomllib.load(f)['project']['scripts']


def test_commands_have_boilerio_names():
    assert scripts() == {
        'boilerio-controller': 'boilerio.controller:main',
        'boilerio-danfoss-bridge': 'boilerio.danfoss_bridge:main',
        'boilersim': 'boilerio.boilersim:main',
    }


def test_command_targets_exist():
    import importlib
    for target in scripts().values():
        module, function = target.split(':')
        assert callable(getattr(importlib.import_module(module), function))
