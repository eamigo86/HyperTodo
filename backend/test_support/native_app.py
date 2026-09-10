"""Finite explicitly bound launcher for synthetic native-app source verification."""

import argparse
import asyncio
import json
import os
import secrets
import socket
from collections.abc import Iterator
from contextlib import contextmanager
from ipaddress import IPv4Address, IPv4Network
from pathlib import Path
from types import ModuleType

from .native_app_boundary import NativeAppBoundary
from .native_app_evidence import EvidenceCollector
from .native_app_fixture import (
    ROOT_ENV,
    SETTINGS_MODULE,
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


def initialize(
    fixture: NativeFixture,
    *,
    paginated: bool = False,
    settings_module: str = SETTINGS_MODULE,
) -> dict[str, object]:
    """Apply existing migrations and seed fictional users only in a new fixture DB."""
    if settings_module not in {SETTINGS_MODULE, "test_support.sse_demo_settings"}:
        raise ValueError("private fixture settings module required")
    if load_fixture(fixture.root) != fixture:
        raise ValueError("private fixture identity mismatch")
    import django
    from django.conf import settings

    if settings.configured or fixture.database.exists():
        raise ValueError("fresh Django process and new fixture database required")
    os.environ[ROOT_ENV] = str(fixture.root)
    os.environ["DJANGO_SETTINGS_MODULE"] = settings_module
    os.environ["TMPDIR"] = str(fixture.root / "tmp")
    if settings.DATABASES["default"]["NAME"] != fixture.database:
        raise ValueError("fixture database mismatch")
    fixture.database.touch(mode=0o600, exist_ok=False)
    django.setup()
    from django.contrib.auth import get_user_model
    from django.core.management import call_command
    from django.test.utils import override_settings

    from todo.models import Category, Task

    with override_settings(HYPERVIEW={**settings.HYPERVIEW, "REALTIME": None}):
        call_command("migrate", verbosity=0, interactive=False)
        User = get_user_model()
        credentials = {}
        for role in ("owner_a", "owner_b", "admin"):
            username, password = f"{role}_{fixture.run_id}", secrets.token_urlsafe(24)
            credentials[role] = {"username": username, "password": password}
            user = User.objects.create_user(
                username=username,
                password=password,
                is_staff=role == "admin",
                is_superuser=role == "admin",
            )
            if role != "admin":
                category = Category.objects.create(user=user, name=f"Fictional {role}")
                for index in range(1, 23 if paginated and role == "owner_a" else 3):
                    Task.objects.create(
                        user=user,
                        category=category,
                        title=f"Fictional {role} task {index}",
                    )
        with open(
            fixture.root / "credentials.json",
            "x",
            opener=lambda p, f: os.open(p, f, 0o600),
        ) as file:
            json.dump(credentials, file)
    return credentials


def apply_control(fixture: NativeFixture, command: str) -> dict[str, object]:
    """Apply a closed host-only control to owner A in the verified private DB."""
    from django.conf import settings

    if (
        not settings.configured
        or Path(settings.DATABASES["default"]["NAME"]).resolve() != fixture.database
        or load_fixture(fixture.root) != fixture
    ):
        raise ValueError("explicit fixture database required")
    if command not in {"rename-task", "revoke-session"}:
        raise ValueError("unknown fixture control")
    from django.contrib.auth import get_user_model
    from django.contrib.sessions.models import Session

    from todo.models import Task
    from todo.services import update_task

    user = (
        get_user_model()
        .objects.using("default")
        .get(username=f"owner_a_{fixture.run_id}")
    )
    affected = 0
    if command == "rename-task":
        task = Task.objects.using("default").filter(user=user).order_by("pk").first()
        if task is None:
            raise ValueError("fixture task unavailable")
        update_task(
            user=user,
            task_id=task.pk,
            title="Fictional owner_a updated task",
            notes=task.notes,
            category=task.category,
            due_at=task.due_at,
        )
        affected = 1
    else:
        for session in Session.objects.using("default").iterator(chunk_size=100):
            if session.get_decoded().get("_auth_user_id") == str(user.pk):
                session.delete(using="default")
                affected += 1
    return {"control": command, "affected": affected}


def check_fixture(
    fixture: NativeFixture, credentials: dict, *, paginated: bool = False
) -> dict[str, object]:
    """Exercise actual Django auth, CSRF and ownership without exposing auth data."""
    from django.test import Client

    from todo.models import Task

    client = Client(enforce_csrf_checks=True, HTTP_HOST=fixture.host)
    headers = {"X-HyperTodo-Client-Contract": "realtime-v1"}
    state = client.get("/hv/session-state/", headers=headers)
    expected = state.json()["binding"]
    headers["X-HyperTodo-Expected-Session"] = expected
    page = client.get("/hv/login/", headers=headers)
    if page.status_code != 200:
        raise ValueError("fixture login page failed")
    csrf = client.cookies[fixture.cookie_names[1]].value
    denied = client.post("/hv/login/", credentials["owner_a"], headers=headers)
    headers["X-CSRFToken"] = csrf
    login = client.post("/hv/login/", credentials["owner_a"], headers=headers)
    confirmed = client.get(
        "/hv/session-state/", headers={"X-HyperTodo-Client-Contract": "realtime-v1"}
    )
    headers["X-HyperTodo-Expected-Session"] = confirmed.json()["binding"]
    foreign = Task.objects.get(
        user__username=credentials["owner_b"]["username"], title__endswith="1"
    )
    hidden = client.get(f"/hv/tasks/{foreign.pk}/edit/", headers=headers)
    result = {
        "owners": 2,
        "admins": 1,
        "tasks": Task.objects.count(),
        "anonymous_state": state.status_code,
        "password_login": login.status_code,
        "authenticated_state": confirmed.json()["authenticated"],
        "foreign_task": hidden.status_code,
        "csrf_rejected": denied.status_code,
    }
    if (
        result["tasks"] != (24 if paginated else 4)
        or state.status_code != 200
        or login.status_code != 200
        or result["authenticated_state"] is not True
        or hidden.status_code != 404
        or denied.status_code != 403
    ):
        raise ValueError("fixture Django acceptance failed")
    if paginated:
        from xml.etree import ElementTree

        own = Task.objects.filter(user__username=credentials["owner_a"]["username"])
        own_keys = {f"task-{pk}" for pk in own.values_list("pk", flat=True)}
        category = own.first().category_id
        query = f"status=active&category={category}"
        pages = [
            client.get(f"/hv/tasks/?{query}", headers=headers),
            client.get(f"/hv/tasks/?{query}&fragment=items&page=2", headers=headers),
        ]
        if any(page.status_code != 200 for page in pages):
            raise ValueError("fixture pagination request failed")
        keys = [
            {
                element.attrib["key"]
                for element in ElementTree.fromstring(page.content).iter()
                if element.attrib.get("key", "").startswith("task-")
            }
            for page in pages
        ]
        result.update(
            owner_tasks=[
                own.count(),
                Task.objects.filter(
                    user__username=credentials["owner_b"]["username"]
                ).count(),
            ],
            page_items=[len(part) for part in keys],
            filtered_owner_only=(keys[0] | keys[1]) == own_keys
            and not (keys[0] & keys[1]),
        )
        if (
            result["owner_tasks"] != [22, 2]
            or result["page_items"] != [20, 2]
            or not result["filtered_owner_only"]
        ):
            raise ValueError("fixture pagination acceptance failed")
    return result


def build_application(
    fixture: NativeFixture, *, evidence: EvidenceCollector | None = None
) -> NativeAppBoundary:
    """Wrap the real conventional Django ASGI app and source static handler."""
    from django.contrib.staticfiles.handlers import ASGIStaticFilesHandler

    from config.asgi import application

    return NativeAppBoundary(
        ASGIStaticFilesHandler(application), fixture, evidence=evidence
    )


def load_runner() -> ModuleType:
    """Verify ASGI dependencies in the selected environment, without path fallback.

    Returns:
        Installed Uvicorn module with RECORD-verified h11 dependency.
    """
    import h11
    import uvicorn

    from .runtime import installed_distribution

    installed_distribution(uvicorn, "uvicorn")
    installed_distribution(h11, "h11")
    return uvicorn


def validate_listener(address: str, port: int) -> tuple[str, int]:
    """Require canonical loopback or RFC1918 IPv4 and an explicit unprivileged port."""
    try:
        ip = IPv4Address(address)
    except (ValueError, TypeError) as error:
        raise ValueError("explicit IPv4 listener required") from error
    private = any(
        ip in IPv4Network(network)
        for network in ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16")
    )
    if str(ip) != address or (address != "127.0.0.1" and not private):
        raise ValueError("listener must be loopback or RFC1918 IPv4")
    if type(port) is not int or not (
        1024 <= port <= 65535 or (address == "127.0.0.1" and port == 0)
    ):
        raise ValueError("explicit unprivileged listener port required")
    return address, port


@contextmanager
def listener_socket(address: str, port: int) -> Iterator[socket.socket]:
    """Bind exactly the chosen local interface or fail closed, always releasing it."""
    endpoint = validate_listener(address, port)
    with socket.socket() as sock:
        # The OS verifies interface availability; never retry on wildcard/loopback.
        sock.bind(endpoint)
        sock.listen(16)
        yield sock


async def serve_fixture(
    fixture: NativeFixture,
    seconds: float,
    *,
    bind: str = "127.0.0.1",
    port: int = 0,
    evidence: EvidenceCollector | None = None,
    application: NativeAppBoundary | None = None,
) -> None:
    """Run one finite explicit listener; never advertise DNS or infer native proof."""
    uvicorn = load_runner()
    app = (
        application
        if application is not None
        else build_application(fixture, evidence=evidence)
    )
    with listener_socket(bind, port) as sock:
        config = uvicorn.Config(
            app,
            loop="asyncio",
            http="h11",
            ws="none",
            lifespan="off",
            access_log=False,
            log_config=None,
            proxy_headers=False,
            workers=1,
            limit_concurrency=16,
            backlog=16,
            limit_max_requests=300,
            timeout_keep_alive=3,
            timeout_graceful_shutdown=5,
            h11_max_incomplete_event_size=16384,
        )
        server = uvicorn.Server(config)
        task = asyncio.create_task(server.serve(sockets=[sock]))
        try:
            print(
                json.dumps(
                    {
                        "stage": "loopback-listener"
                        if bind == "127.0.0.1"
                        else "private-listener",
                        "host": fixture.host,
                        "port": sock.getsockname()[1],
                    }
                ),
                flush=True,
            )
            try:
                await asyncio.wait_for(asyncio.shield(task), timeout=seconds)
            except TimeoutError:
                server.should_exit = True
                await asyncio.wait_for(task, timeout=7)
        finally:
            server.should_exit = True
            if not task.done():
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)


def main() -> None:
    """Create, verify and clean one fixture; report only sanitized outcomes."""
    parser = argparse.ArgumentParser(description=__doc__)
    add_runtime_arguments(parser)
    parser.add_argument("--parent", type=Path)
    parser.add_argument("--report", type=Path)
    parser.add_argument("--check-only", action="store_true")
    parser.add_argument("--seconds", type=float, default=60)
    parser.add_argument("--bind", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=0)
    parser.add_argument("--paginated", action="store_true")
    parser.add_argument("--events-report", type=Path)
    args = parser.parse_args()
    configure_runtime(args)
    args.parent = args.parent or workspace_root() / "runtime-private"
    if not 0 < args.seconds <= 600:
        parser.error("seconds must be within (0, 600]")
    if args.report and (
        not args.report.absolute().is_relative_to(report_root())
        or args.report.resolve() != args.report.absolute()
    ):
        raise ValueError("report must stay inside the isolated evidence directory")
    if args.events_report and (
        not args.events_report.absolute().is_relative_to(report_root())
        or args.events_report.resolve() != args.events_report.absolute()
        or args.events_report.exists()
    ):
        raise ValueError("events report must be a new isolated evidence path")
    validate_listener(args.bind, args.port)
    provenance = verify_source()
    if not args.check_only:
        load_runner()
    fixture = create_fixture(args.parent)
    result = {
        **provenance,
        "root": str(fixture.root),
        "cleaned": False,
        "passed": False,
    }
    evidence = None
    pass_key = "fixture_checks_passed" if args.events_report else "passed"
    if args.events_report:
        result.pop("passed")
        result[pass_key] = False
    try:
        credentials = initialize(fixture, paginated=args.paginated)
        if args.events_report:
            evidence = EvidenceCollector(fixture.run_id, args.events_report)
        result.update(check_fixture(fixture, credentials, paginated=args.paginated))
        if not args.check_only:
            asyncio.run(
                serve_fixture(
                    fixture,
                    args.seconds,
                    bind=args.bind,
                    port=args.port,
                    evidence=evidence,
                )
            )
        result[pass_key] = True
    finally:
        from django.db import connections

        connections.close_all()
        try:
            cleanup_fixture(fixture.root)
            result["cleaned"] = True
        finally:
            try:
                if evidence is not None:
                    evidence.close(cleanup_ok=result["cleaned"])
            finally:
                if evidence is not None:
                    result["events"] = evidence.snapshot()
                if args.report:
                    args.report.write_text(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
