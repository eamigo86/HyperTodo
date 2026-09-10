"""Private resources for the temporary native-app source fixture, never deployment."""

import json
import os
import secrets
import shutil
import tempfile
import uuid
from argparse import ArgumentParser, Namespace
from dataclasses import dataclass
from pathlib import Path

WORK_ROOT = Path(__file__).resolve().parents[3]
ROOT_ENV = "HYPERTODO_NATIVE_APP_ROOT"
SETTINGS_MODULE = "test_support.native_app_settings"
WORKSPACE_ENV = "HYPERTODO_FIXTURE_WORKSPACE"


@dataclass(frozen=True)
class NativeFixture:
    """Immutable identity of one newly allocated private fixture directory."""

    root: Path
    run_id: str
    secret: str

    @property
    def host(self) -> str:
        """Return the fresh canonical hostname."""
        return f"hvt-{self.run_id}.local"

    @property
    def database(self) -> Path:
        """Return only this fixture's SQLite path."""
        return self.root / "fixture.sqlite3"

    @property
    def config_file(self) -> Path:
        """Return the private fixture configuration path."""
        return self.root / "fixture.json"

    @property
    def cookie_names(self) -> tuple[str, str, str]:
        """Return names reserved to this run, not the original app."""
        return tuple(
            f"hvt_{kind}_{self.run_id}" for kind in ("session", "csrf", "language")
        )


def _private(path: Path, mode: int) -> None:
    if path.is_symlink() or path.resolve() != path:
        raise ValueError("symlink fixture resources are forbidden")
    stat = path.stat()
    if stat.st_mode & 0o777 != mode or stat.st_uid != os.getuid():
        raise ValueError("fixture resources must be private and owned")


def create_fixture(parent: Path) -> NativeFixture:
    """Allocate new resources under the isolated work area, never an existing DB."""
    parent = Path(parent).absolute()
    if not parent.is_relative_to(workspace_root()) or parent.resolve() != parent:
        raise ValueError("fixture parent must be within the isolated work area")
    parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    root = Path(tempfile.mkdtemp(prefix="native-app-", dir=parent))
    fixture = NativeFixture(root, uuid.uuid4().hex, secrets.token_urlsafe(48))
    try:
        with open(
            fixture.config_file, "x", opener=lambda p, f: os.open(p, f, 0o600)
        ) as file:
            json.dump({"run_id": fixture.run_id, "secret": fixture.secret}, file)
        for name in ("media", "uploads", "tmp"):
            (root / name).mkdir(mode=0o700)
    except BaseException:
        shutil.rmtree(root)
        raise
    return fixture


def load_fixture(root: Path | None = None) -> NativeFixture:
    """Load only explicit, owned, private configuration without environment fallback."""
    supplied = root or os.environ.get(ROOT_ENV)
    if not supplied:
        raise ValueError("explicit fixture root is required")
    path = Path(supplied).absolute()
    if path.is_symlink():
        raise ValueError("symlink fixture resources are forbidden")
    if not path.is_relative_to(workspace_root()) or not path.name.startswith(
        "native-app-"
    ):
        raise ValueError("unowned fixture root")
    _private(path, 0o700)
    config = path / "fixture.json"
    _private(config, 0o600)
    data = json.loads(config.read_text())
    if (
        set(data) != {"run_id", "secret"}
        or not isinstance(data["run_id"], str)
        or len(data["run_id"]) != 32
        or any(c not in "0123456789abcdef" for c in data["run_id"])
        or not isinstance(data["secret"], str)
        or len(data["secret"]) < 48
    ):
        raise ValueError("invalid fixture configuration")
    fixture = NativeFixture(path, data["run_id"], data["secret"])
    for name in ("media", "uploads", "tmp"):
        _private(path / name, 0o700)
    if fixture.database.exists() or fixture.database.is_symlink():
        _private(fixture.database, 0o600)
    return fixture


def cleanup_fixture(root: Path) -> None:
    """Remove only a validated owned fixture tree, never a caller's parent."""
    fixture = load_fixture(root)
    shutil.rmtree(fixture.root)


def settings_overrides(fixture: NativeFixture) -> dict[str, object]:
    """Return synthetic resources while retaining Django security middleware."""
    from config import settings as base

    result = {
        "HYPERVIEW": {**base.HYPERVIEW, "REALTIME": None},
        "SECRET_KEY": fixture.secret,
        "SECRET_KEY_FALLBACKS": [],
        "DEBUG": False,
        "ALLOWED_HOSTS": [fixture.host],
        "CSRF_TRUSTED_ORIGINS": [],
        "DATABASES": {
            "default": {
                "ENGINE": "django.db.backends.sqlite3",
                "NAME": fixture.database,
            }
        },
        "CACHES": {
            "default": {
                "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
                "LOCATION": fixture.run_id,
            }
        },
        "MEDIA_ROOT": fixture.root / "media",
        "STATIC_URL": "/static/",
        "FILE_UPLOAD_TEMP_DIR": fixture.root / "uploads",
        "DATA_UPLOAD_MAX_MEMORY_SIZE": 65536,
        "DATA_UPLOAD_MAX_NUMBER_FIELDS": 100,
        "SESSION_ENGINE": "django.contrib.sessions.backends.db",
        "SESSION_COOKIE_HTTPONLY": True,
        "SESSION_COOKIE_SECURE": False,
        "CSRF_COOKIE_SECURE": False,
        "SESSION_COOKIE_AGE": 600,
        "CSRF_COOKIE_AGE": 600,
        "LANGUAGE_COOKIE_AGE": 600,
        "SESSION_COOKIE_SAMESITE": "Lax",
        "CSRF_COOKIE_SAMESITE": "Lax",
        "MAILERS": {
            "default": {"BACKEND": "django.core.mail.backends.locmem.EmailBackend"}
        },
        "ASGI_APPLICATION": "config.asgi.application",
        "LOGGING": {"version": 1, "disable_existing_loggers": True},
    }
    for kind, name in zip(
        ("SESSION", "CSRF", "LANGUAGE"), fixture.cookie_names, strict=True
    ):
        result.update(
            {
                f"{kind}_COOKIE_NAME": name,
                f"{kind}_COOKIE_DOMAIN": None,
                f"{kind}_COOKIE_PATH": "/",
            }
        )
    return result


def verify_source() -> dict[str, str]:
    """Verify installed provenance by default, or explicitly configured source.

    Returns:
        Tagged package provenance, before allocating a fixture or loading Django.
    """
    from .runtime import verify_package

    return verify_package()


def workspace_root() -> Path:
    """Return the explicit private workspace, or the existing source-workspace default.

    Returns:
        Canonical owned workspace; explicit workspaces must have mode 0700.
    """
    supplied = os.environ.get(WORKSPACE_ENV)
    if not supplied:
        return WORK_ROOT
    path = Path(supplied).absolute()
    _private(path, 0o700)
    return path


def report_root() -> Path:
    """Return the only permitted report area for the selected fixture workspace."""
    root = workspace_root()
    return root if os.environ.get(WORKSPACE_ENV) else root / "evidence"


def add_runtime_arguments(parser: ArgumentParser) -> None:
    """Add explicit private fixture workspace and source-verification paths.

    Args:
        parser: Fixture-only argument parser, not application settings.
    """
    parser.add_argument("--workspace", type=Path)
    parser.add_argument("--source-root", type=Path)
    parser.add_argument("--source-metadata", type=Path)


def configure_runtime(args: Namespace) -> None:
    """Select explicit test paths without modifying Python's import path.

    Args:
        args: Parsed fixture CLI arguments.
    """
    from .runtime import METADATA_ENV, SOURCE_ENV

    if args.workspace is not None:
        os.environ[WORKSPACE_ENV] = str(args.workspace)
    workspace_root()
    if args.source_root is not None or args.source_metadata is not None:
        if args.source_root is None or args.source_metadata is None:
            raise ValueError("source metadata provenance requires both paths")
        os.environ[SOURCE_ENV] = str(args.source_root)
        os.environ[METADATA_ENV] = str(args.source_metadata)
