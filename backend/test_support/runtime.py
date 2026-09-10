"""Private fixture provenance: installed artifacts or explicitly selected source."""

import base64
import hashlib
import importlib.metadata
import os
import re
import sys
import tomllib
from pathlib import Path
from types import ModuleType

SOURCE_ENV = "HYPERTODO_FIXTURE_SOURCE"
METADATA_ENV = "HYPERTODO_FIXTURE_METADATA"


def installed_distribution(module: ModuleType, name: str) -> Path:
    """Verify the selected environment's distribution, module and RECORD hashes.

    Args:
        module: Actually imported module, not a supplied source path.
        name: Distribution owning that module.

    Returns:
        Verified metadata directory within the current environment.

    Raises:
        ValueError: If origin, version or recorded content does not match.
    """
    try:
        dist = importlib.metadata.distribution(name)
        prefix = Path(sys.prefix).resolve()
        location = Path(module.__file__).resolve()
        files = dist.files
        if (
            not files
            or not location.is_relative_to(prefix)
            or dist.version != module.__version__
        ):
            raise ValueError
        found = False
        metadata = None
        for entry in files:
            path = Path(dist.locate_file(entry)).resolve()
            if not path.is_relative_to(prefix):
                raise ValueError
            if path == location:
                found = entry.hash is not None
            if str(entry).endswith(".dist-info/METADATA"):
                metadata = path.parent
            if entry.hash:
                if entry.hash.mode != "sha256":
                    raise ValueError
                actual = (
                    base64.urlsafe_b64encode(hashlib.sha256(path.read_bytes()).digest())
                    .rstrip(b"=")
                    .decode()
                )
                if actual != entry.hash.value:
                    raise ValueError
        if not found or metadata is None:
            raise ValueError
        return metadata
    except AttributeError, OSError, ValueError, importlib.metadata.PackageNotFoundError:
        raise ValueError("installed artifact provenance mismatch") from None


def verify_package() -> dict[str, str]:
    """Verify the consumer pin before fixture allocation; never fall back to source.

    Returns:
        Sanitized provenance explicitly labelled installed or source.

    Raises:
        ValueError: If package identity, mode or runtime is inconsistent.
    """
    import dj_hyperview
    import django

    dependencies = tomllib.loads(
        (Path(__file__).resolve().parents[1] / "pyproject.toml").read_text()
    )["project"]["dependencies"]
    versions = [
        match.group(1)
        for value in dependencies
        if (match := re.fullmatch(r"dj-hyperview\[[^]]+\]==([^ ;]+)", value))
    ]
    if len(versions) != 1 or dj_hyperview.__version__ != versions[0]:
        raise ValueError("package pin provenance mismatch")
    source = os.environ.get(SOURCE_ENV)
    metadata_root = os.environ.get(METADATA_ENV)
    if bool(source) != bool(metadata_root):
        raise ValueError("explicit source metadata provenance requires both paths")
    if source:
        try:
            source_path = Path(source).absolute()
            metadata_path = Path(metadata_root).absolute()
            project = tomllib.loads((source_path / "pyproject.toml").read_text())[
                "project"
            ]
            dist = importlib.metadata.distribution("dj-hyperview")
            metadata = metadata_path / f"dj_hyperview-{versions[0]}.dist-info"
            if (
                source_path.resolve() != source_path
                or metadata_path.resolve() != metadata_path
                or project["name"] != "dj-hyperview"
                or project["version"] != versions[0]
                or dist.version != versions[0]
                or Path(dist.locate_file("")).resolve() != metadata_path
                or dist.read_text("METADATA") != (metadata / "METADATA").read_text()
                or Path(dj_hyperview.__file__).resolve()
                != source_path / "src/dj_hyperview/__init__.py"
            ):
                raise ValueError
        except OSError, KeyError, TypeError, ValueError:
            raise ValueError("source metadata provenance mismatch") from None
        provenance = "source"
    else:
        metadata = installed_distribution(dj_hyperview, "dj-hyperview")
        provenance = "installed"
    if (
        sys.version_info[:2] != (3, 14)
        or (provenance == "source" and not sys.dont_write_bytecode)
        or django.get_version() != "6.1.1"
    ):
        raise ValueError("verified Python3.14 / Django6.1.1 required; source needs -B")
    return {
        "provenance": provenance,
        "source_version": versions[0],
        "source_file": dj_hyperview.__file__,
        "metadata": str(metadata),
        "django": django.get_version(),
    }
