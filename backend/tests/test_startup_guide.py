"""Keep the concise landing page and linked startup guide safe and executable."""

import os
import re
import subprocess
from pathlib import Path

from config.schema import schema_extensions

ROOT = Path(__file__).resolve().parents[2]
GUIDE = ROOT / "backend/docs/installed-adoption.md"


def section(text, heading):
    body = text.split(heading + "\n", 1)[1]
    return re.split(r"\n#{2,3} ", body, maxsplit=1)[0]


def console_commands(text):
    return "\n".join(re.findall(r"```console\n(.*?)\n```", text, re.DOTALL))


def test_readme_is_a_short_landing_page_with_ordered_sections():
    readme = (ROOT / "README.md").read_text()
    headings = [
        "## What HyperTodo tests",
        "## Repository layout",
        "## Makefile commands",
        "## Screenshots",
        "## Custom components and behaviors",
        "## Database-backed templates",
        "## Automatic HXML validation",
        "## Realtime SSE",
        "## Quality checks",
        "## License",
    ]
    positions = [readme.index(heading) for heading in headings]
    assert positions == sorted(positions)
    assert len(readme.split()) <= 2200
    assert "(backend/docs/installed-adoption.md)" in readme
    assert "Realtime Gate 0" not in readme and "../evidence/" not in readme


def test_fresh_setup_is_separate_from_existing_database_upgrade():
    guide = GUIDE.read_text()
    fresh = section(guide, "### New disposable database")
    existing = section(guide, "### Existing database")
    assert "make backend-seed" in console_commands(fresh)
    assert "make backend-seed" not in console_commands(existing)
    assert "Do not run `make backend-seed`" in existing
    assert "backup" in existing and "migration" in existing


def test_documented_sse_and_go_commands_expand_without_starting_services():
    guide = GUIDE.read_text()
    backend = section(guide, "### Backend terminal")
    mobile = section(guide, "### Expo Go terminal")
    assert "LAN_IP=192.168.1.20 make backend-run-sse" in console_commands(backend)
    assert "LAN_IP=192.168.1.20 make mobile-start-go" in console_commands(mobile)
    env = {**os.environ, "LAN_IP": "192.168.1.20"}
    result = subprocess.run(
        ["make", "--no-print-directory", "-n", "backend-run-sse", "mobile-start-go"],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=10,
        check=True,
    )
    assert "DJANGO_SETTINGS_MODULE=config.settings_sse" in result.stdout
    assert "uvicorn config.asgi:application" in result.stdout
    assert '--host "192.168.1.20" --port 8000' in result.stdout
    assert "EXPO_PUBLIC_ALLOW_LOCAL_API=1" in result.stdout
    assert 'EXPO_PUBLIC_API_URL="http://192.168.1.20:8000/hv/"' in result.stdout
    assert "start:go" in result.stdout
    assert all(
        word not in result.stdout for word in ("runserver", "seed_demo", "migrate")
    )


def test_admin_example_checks_real_owner_refresh_and_draft_protection():
    example = section(GUIDE.read_text(), "## Check a real Admin update")
    assert "http://192.168.1.20:8000/admin/" in example
    assert "owner" in example and "without" in example and "refresh" in example
    assert "same device" in example and "another device" in example
    assert "discard" in example and "draft" in example
    assert "native" in example.lower() and "not" in example.lower()


def test_custom_inventory_matches_native_registration_and_backend_schema():
    readme = (ROOT / "README.md").read_text()
    components = section(readme, "### HXML components")
    sources = (
        "mobile/src/components/AnimatedSideMenu.tsx",
        "mobile/src/components/EdgeMenuOpener.tsx",
        "mobile/src/components/SwipeRow.tsx",
        "mobile/src/realtime/gate.tsx",
    )
    registered = {
        "app:" + name
        for source in sources
        for name in re.findall(r'localName:\s*"([^"]+)"', (ROOT / source).read_text())
    }
    documented = set(re.findall(r"^\| \[`(app:[^`]+)`\]", components, re.MULTILINE))
    assert len(registered) == 5 and documented == registered
    assert "not a sixth component" in components
    actions = section(readme, "### Behavior actions")
    documented_actions = set(re.findall(r"^\| `([^`]+)` \|", actions, re.MULTILINE))
    native = (ROOT / "mobile/src/behaviors/owned.ts").read_text()
    native_actions = set(re.findall(r'callback\("([^"]+)"', native))
    assert len(native_actions) == 6
    assert documented_actions == native_actions == set(schema_extensions()["BEHAVIORS"])


def test_readme_keeps_the_mobile_gallery_and_existing_admin_asset_path():
    readme = (ROOT / "README.md").read_text()
    gallery = re.findall(r'<img src="([^"]+)"', section(readme, "## Screenshots"))
    expected = {
        f".github/assets/screenshots/{name}.png"
        for name in (
            "login",
            "dashboard-light",
            "dashboard-dark",
            "task-swipe-actions",
            "task-edit",
            "categories",
            "settings",
            "side-menu",
            "about",
        )
    }
    assert len(gallery) == 9 and set(gallery) == expected
    admin = ".github/assets/screenshots/django-admin-hxml-editor.png"
    assert f"]({admin})" in readme
    for target in (*gallery, admin):
        assert (ROOT / target).read_bytes().startswith(b"\x89PNG\r\n\x1a\n")
