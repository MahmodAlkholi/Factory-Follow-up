"""
The deployment path.

These tests guard the things that only break *after* the app is packaged and
deployed - a broken static build, a gunicorn that listens on the wrong port,
a vendored asset that points at a file we do not ship.
"""

import importlib.util
import os
import subprocess
import sys
from pathlib import Path

import pytest

BASE_DIR = Path(__file__).resolve().parent.parent
GUNICORN_CONF = BASE_DIR / "deploy" / "gunicorn.conf.py"


def load_gunicorn_conf(monkeypatch, **env):
    """Import deploy/gunicorn.conf.py with a controlled environment."""
    for name, value in env.items():
        if value is None:
            monkeypatch.delenv(name, raising=False)
        else:
            monkeypatch.setenv(name, value)
    spec = importlib.util.spec_from_file_location("gunicorn_conf_under_test", GUNICORN_CONF)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_gunicorn_follows_the_platform_port(monkeypatch):
    """Cloud Run, Render, Heroku and HF Spaces tell the process via $PORT."""
    conf = load_gunicorn_conf(monkeypatch, PORT="8080", GUNICORN_BIND=None)
    assert conf.bind == "0.0.0.0:8080"


def test_gunicorn_bind_can_be_overridden(monkeypatch):
    conf = load_gunicorn_conf(monkeypatch, PORT="8080", GUNICORN_BIND="0.0.0.0:9000")
    assert conf.bind == "0.0.0.0:9000"


def test_gunicorn_defaults_to_port_8000(monkeypatch):
    conf = load_gunicorn_conf(monkeypatch, PORT=None, GUNICORN_BIND=None)
    assert conf.bind == "0.0.0.0:8000"


def test_vendored_assets_have_no_broken_source_map_references():
    """A missing .map file aborts the whole production static build."""
    vendor = BASE_DIR / "static" / "vendor"
    stale = []
    for path in sorted(vendor.iterdir()):
        if path.is_file() and path.suffix in {".js", ".css"}:
            if b"sourceMappingURL" in path.read_bytes():
                stale.append(path.name)
    assert not stale, f"sourceMappingURL references to missing files: {stale}"


@pytest.mark.slow
def test_collectstatic_succeeds_in_production_mode(tmp_path):
    """
    The production static build must not fail.

    ``ManifestStaticFilesStorage`` follows every reference in the CSS and JS,
    so a single missing file (a source map, a font, an image) breaks
    ``collectstatic`` - and with it the whole deployment.
    """
    env = os.environ.copy()
    env["DJANGO_DEBUG"] = "False"
    env["DJANGO_STATIC_ROOT"] = str(tmp_path)
    result = subprocess.run(
        [sys.executable, "manage.py", "collectstatic", "--noinput"],
        cwd=str(BASE_DIR),
        env=env,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr[-3000:]
    assert (tmp_path / "staticfiles.json").exists(), "no manifest was written"
