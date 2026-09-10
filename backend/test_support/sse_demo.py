"""Finite disposable normal HyperTodo/Admin demo, without Gate0 UI or collectors."""

import argparse
import asyncio
import json
from pathlib import Path

from .native_app import (
    check_fixture,
    initialize,
    load_runner,
    serve_fixture,
    validate_listener,
)
from .native_app_boundary import NativeAppBoundary
from .native_app_fixture import (
    NativeFixture,
    add_runtime_arguments,
    cleanup_fixture,
    configure_runtime,
    create_fixture,
    load_fixture,
    report_root,
    verify_source,
    workspace_root,
)

SETTINGS_MODULE = "test_support.sse_demo_settings"


def public_details(fixture: NativeFixture, port: int) -> dict[str, str]:
    """Expose only nonsecret run/origin for the separately owned Metro launcher."""
    validate_listener("127.0.0.1", port)
    if port == 0:
        raise ValueError("explicit demo port required")
    return {"run": fixture.run_id, "apiOrigin": f"http://{fixture.host}:{port}"}


def build_application(fixture: NativeFixture) -> NativeAppBoundary:
    """Use real Django auth/ASGI with only the exact SSE response budget extended."""
    from django.conf import settings
    from django.contrib.staticfiles.handlers import ASGIStaticFilesHandler

    from config.asgi import application

    if (
        settings.SETTINGS_MODULE != SETTINGS_MODULE
        or load_fixture() != fixture
        or Path(settings.DATABASES["default"]["NAME"]) != fixture.database
        or settings.HYPERVIEW.get("REALTIME")
        != {
            "REDIS_URL": "redis://127.0.0.1:6379/14",
            "NAMESPACE": "hypertodo-demo-" + fixture.run_id,
        }
    ):
        raise ValueError("explicit disposable SSE settings required")
    return NativeAppBoundary(
        ASGIStaticFilesHandler(application),
        fixture,
        sse_response_timeout=70,
    )


def main(argv: list[str] | None = None) -> None:
    """Allocate, verify, serve and clean owned resources; never print credentials."""
    parser = argparse.ArgumentParser(description=__doc__)
    add_runtime_arguments(parser)
    parser.add_argument("--parent", type=Path)
    parser.add_argument("--report", type=Path)
    parser.add_argument("--check-only", action="store_true")
    parser.add_argument("--seconds", type=float, default=600)
    parser.add_argument("--bind", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8788)
    parser.add_argument("--paginated", action="store_true")
    args = parser.parse_args(argv)
    configure_runtime(args)
    args.parent = args.parent or workspace_root() / "runtime-private"
    if not 0 < args.seconds <= 600:
        parser.error("seconds must be within (0, 600]")
    validate_listener(args.bind, args.port)
    if args.port == 0:
        parser.error("explicit demo port required")
    if args.report and (
        not args.report.absolute().is_relative_to(report_root())
        or args.report.resolve() != args.report.absolute()
        or args.report.exists()
    ):
        raise ValueError("report must be a new isolated evidence path")
    provenance = verify_source()
    if not args.check_only:
        load_runner()
    fixture = create_fixture(args.parent)
    result = {
        **provenance,
        **public_details(fixture, args.port),
        "root": str(fixture.root),
        "cleaned": False,
        "fixture_checks_passed": False,
        "native_accepted": False,
    }
    try:
        credentials = initialize(
            fixture,
            paginated=args.paginated,
            settings_module=SETTINGS_MODULE,
        )
        result.update(check_fixture(fixture, credentials, paginated=args.paginated))
        from django.conf import settings

        credential_mode = (fixture.root / "credentials.json").stat().st_mode & 0o777
        result.update(
            settings_module=SETTINGS_MODULE,
            namespace=settings.HYPERVIEW["REALTIME"]["NAMESPACE"],
            redis_url=settings.HYPERVIEW["REALTIME"]["REDIS_URL"],
            credential_mode=f"{credential_mode:04o}",
            database_mode=f"{fixture.database.stat().st_mode & 0o777:04o}",
        )
        if not args.check_only:
            application = build_application(fixture)
            print(
                json.dumps(
                    {"stage": "demo-prepared", **public_details(fixture, args.port)}
                ),
                flush=True,
            )
            asyncio.run(
                serve_fixture(
                    fixture,
                    args.seconds,
                    bind=args.bind,
                    port=args.port,
                    application=application,
                )
            )
        result["fixture_checks_passed"] = True
    finally:
        from django.db import connections

        try:
            connections.close_all()
        finally:
            try:
                cleanup_fixture(fixture.root)
                result["cleaned"] = True
            finally:
                if args.report:
                    args.report.write_text(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
