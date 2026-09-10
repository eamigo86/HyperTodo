"""No-fallback installed/source fixture authority and portable private roots."""

import importlib.metadata
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import dj_hyperview
import pytest

from test_support import native_app_fixture as fixture

BACKEND = Path(__file__).resolve().parents[1]


def test_installed_package_is_verified_against_the_current_pin_and_record():
    result = fixture.verify_source()
    assert result["provenance"] == "installed"
    assert result["source_version"] == importlib.metadata.version("dj-hyperview")
    assert Path(result["source_file"]).is_relative_to(Path(sys.prefix))
    assert Path(result["metadata"]).is_relative_to(Path(sys.prefix))


def test_installed_verification_works_in_ordinary_python_without_lab_flags(tmp_path):
    env = dict(os.environ)
    for key in (
        "PYTHONPATH",
        "PYTHONDONTWRITEBYTECODE",
        "HYPERTODO_FIXTURE_SOURCE",
        "HYPERTODO_FIXTURE_METADATA",
    ):
        env.pop(key, None)
    env["PYTHONPYCACHEPREFIX"] = str(tmp_path / "bytecode")
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "from test_support.native_app_fixture import verify_source; "
                "assert verify_source()['provenance'] == 'installed'"
            ),
        ],
        cwd=BACKEND,
        env=env,
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert result.returncode == 0, result.stderr


def test_shadowed_import_is_not_an_installed_artifact(tmp_path, monkeypatch):
    monkeypatch.setattr(dj_hyperview, "__file__", str(tmp_path / "__init__.py"))
    with pytest.raises(ValueError, match="provenance"):
        fixture.verify_source()


def test_wrong_installed_version_is_rejected(monkeypatch):
    original = importlib.metadata.distribution

    class WrongVersion:
        version = "0.0.0"

        def __getattr__(self, key):
            return getattr(original("dj-hyperview"), key)

    monkeypatch.setattr(importlib.metadata, "distribution", lambda name: WrongVersion())
    with pytest.raises(ValueError, match="provenance"):
        fixture.verify_source()


def test_distribution_without_record_is_not_accepted(monkeypatch):
    original = importlib.metadata.distribution

    class MissingRecord:
        files = None

        def __getattr__(self, key):
            return getattr(original("dj-hyperview"), key)

    monkeypatch.setattr(
        importlib.metadata, "distribution", lambda name: MissingRecord()
    )
    with pytest.raises(ValueError, match="provenance"):
        fixture.verify_source()


def source_layout(tmp_path):
    source = tmp_path / "package-source"
    metadata = tmp_path / "source-metadata"
    version = importlib.metadata.version("dj-hyperview")
    shutil.copytree(
        Path(dj_hyperview.__file__).parent,
        source / "src/dj_hyperview",
        ignore=shutil.ignore_patterns("__pycache__"),
    )
    (source / "pyproject.toml").write_text(
        f'[project]\nname = "dj-hyperview"\nversion = "{version}"\n'
    )
    info = metadata / f"dj_hyperview-{version}.dist-info"
    info.mkdir(parents=True)
    (info / "METADATA").write_text(
        f"Metadata-Version: 2.1\nName: dj-hyperview\nVersion: {version}\n"
    )
    return source, metadata


@pytest.mark.parametrize("explicit", [False, True])
def test_source_requires_explicit_mode_and_reports_no_artifact_acceptance(
    tmp_path, explicit
):
    source, metadata = source_layout(tmp_path)
    env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}
    env["PYTHONPATH"] = os.pathsep.join(
        [str(source / "src"), str(metadata), str(BACKEND)]
    )
    env.pop("HYPERTODO_FIXTURE_SOURCE", None)
    env.pop("HYPERTODO_FIXTURE_METADATA", None)
    if explicit:
        env["HYPERTODO_FIXTURE_SOURCE"] = str(source)
        env["HYPERTODO_FIXTURE_METADATA"] = str(metadata)
    result = subprocess.run(
        [
            sys.executable,
            "-B",
            "-c",
            "import json; from test_support.native_app_fixture import verify_source; "
            "print(json.dumps(verify_source()))",
        ],
        env=env,
        capture_output=True,
        text=True,
        timeout=15,
    )
    if explicit:
        assert result.returncode == 0, result.stderr
        assert json.loads(result.stdout)["provenance"] == "source"
    else:
        assert result.returncode != 0
        assert "provenance" in result.stderr


def test_incomplete_source_configuration_never_falls_back(tmp_path, monkeypatch):
    monkeypatch.setenv("HYPERTODO_FIXTURE_SOURCE", str(tmp_path))
    monkeypatch.delenv("HYPERTODO_FIXTURE_METADATA", raising=False)
    with pytest.raises(ValueError, match="source.*provenance"):
        fixture.verify_source()


def test_explicit_workspace_is_portable_but_stays_private(tmp_path, monkeypatch):
    workspace = tmp_path / "private-workspace"
    workspace.mkdir(mode=0o700)
    monkeypatch.setenv("HYPERTODO_FIXTURE_WORKSPACE", str(workspace))
    monkeypatch.setattr(fixture, "WORK_ROOT", tmp_path / "unrelated-source-parent")
    made = fixture.create_fixture(workspace)
    try:
        assert made.root.parent == workspace
        assert fixture.load_fixture(made.root) == made
        with pytest.raises(ValueError, match="work"):
            fixture.create_fixture(tmp_path)
    finally:
        fixture.cleanup_fixture(made.root)


@pytest.mark.parametrize("kind", ["public-mode", "symlink"])
def test_explicit_workspace_rejects_unsafe_ownership(tmp_path, monkeypatch, kind):
    workspace = tmp_path / "private-workspace"
    workspace.mkdir(mode=0o700)
    if kind == "public-mode":
        workspace.chmod(0o755)
    else:
        link = tmp_path / "alias"
        link.symlink_to(workspace, target_is_directory=True)
        workspace = link
    monkeypatch.setenv("HYPERTODO_FIXTURE_WORKSPACE", str(workspace))
    with pytest.raises(ValueError, match="work|private|symlink"):
        fixture.create_fixture(workspace)
