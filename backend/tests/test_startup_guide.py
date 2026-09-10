"""Keep the README's copyable Expo Go path on the actual safe Make targets."""

import os
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def section(text, heading):
    body = text.split(heading + "\n", 1)[1]
    return re.split(r"\n#{2,3} ", body, maxsplit=1)[0]


def console_commands(text):
    return "\n".join(re.findall(r"```console\n(.*?)\n```", text, re.DOTALL))


def test_sse_quick_start_precedes_reference_and_screenshots():
    readme = (ROOT / "README.md").read_text()
    quick = readme.index("## Quick start: SSE with Expo Go")
    assert quick < readme.index("## Screenshots")
    assert quick < readme.index("## Realtime configuration")
    assert "No native build" in readme[: readme.index("## Realtime configuration")]


def test_fresh_setup_is_separate_from_existing_database_upgrade():
    readme = (ROOT / "README.md").read_text()
    fresh = section(readme, "### 2. Prepare a new demo database (fresh checkout only)")
    existing = section(readme, "### Existing database: update without seeding")
    assert "make backend-seed" in console_commands(fresh)
    assert "make backend-seed" not in console_commands(existing)
    assert "Do not run `make backend-seed`" in existing
    assert "backup" in existing and "migration" in existing


def test_documented_sse_and_go_commands_expand_without_starting_services():
    readme = (ROOT / "README.md").read_text()
    backend = section(readme, "### 3. Start Redis and the SSE backend")
    mobile = section(readme, "### 4. Open Expo Go")
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
    readme = (ROOT / "README.md").read_text()
    example = section(readme, "### 5. Check Admin → Tasks updates")
    assert "http://192.168.1.20:8000/admin/" in example
    assert "owner" in example and "without" in example and "refresh" in example
    assert "same device" in example and "another device" in example
    assert "discard" in example and "draft" in example
    assert "native" in example.lower() and "not" in example.lower()
