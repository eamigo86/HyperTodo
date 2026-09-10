"""Negotiated real HXML producers, XML layout metadata and strict typed schema."""

from urllib.parse import parse_qs, urlsplit
from xml.etree import ElementTree as ET

import pytest
from dj_hyperview import validate_hyperview_schema
from dj_hyperview.exceptions import TemplateValidationError
from django.test import Client

from tests.test_session_contract import _confirm, _headers
from todo.models import Category, Task

pytestmark = pytest.mark.django_db
APP = "https://hypertodo.app/components"
HV = "https://hyperview.org/hyperview"
NS = {"hv": HV, "app": APP}
RESOURCES = (
    "tasks",
    "categories",
    "ui",
    "tasks categories",
    "tasks ui",
    "categories ui",
    "tasks categories ui",
)


def request(client, method, url, data=None, *, modern=True, request_id="gate-review-1"):
    headers = {}
    if modern:
        binding, _ = _confirm(client, client.session.get("_auth_user_id") is not None)
        headers = _headers(binding)
        if request_id is not None:
            headers["X-HyperTodo-Request-ID"] = request_id
    response = getattr(client, method)(url, data or {}, headers=headers)
    assert response["Content-Type"].startswith("application/vnd.hyperview")
    validate_hyperview_schema(response.content.decode())
    return response, ET.fromstring(response.content)


@pytest.mark.parametrize("modern", (False, True))
@pytest.mark.parametrize(
    "url,mode,target,resources",
    [
        ("/hv/tasks/", "list", "task-list", "tasks categories ui"),
        ("/hv/categories/", "list", "category-list", "tasks categories ui"),
        ("/hv/dashboard/", "notice", "dashboard-screen", "tasks categories ui"),
        ("/hv/tasks/new/", "notice", "task-form-screen", "tasks categories ui"),
        ("/hv/categories/new/", "notice", "category-form-screen", "categories ui"),
        ("/hv/settings/", "notice", "settings-screen", "ui"),
        ("/hv/about/", "notice", "about-screen", "ui"),
        ("/hv/source-probe/", "notice", "filesystem-probe", "ui"),
    ],
)
def test_screen_boundary_is_negotiated_and_outside_lists(
    user, modern, url, mode, target, resources
):
    client = Client()
    client.force_login(user)
    _, root = request(client, "get", url, modern=modern)
    boundaries = root.findall(".//app:realtime", NS)
    if not modern:
        assert not boundaries and not root.findall(".//app:realtime-page", NS)
        return
    assert len(boundaries) == 1
    boundary = boundaries[0]
    assert root.find("./hv:screen/hv:body/app:realtime", NS) is boundary
    assert boundary.attrib["mode"] == mode
    assert boundary.attrib["target"] == target
    assert boundary.attrib["resources"] == resources
    assert not root.findall(".//hv:list/app:realtime", NS)
    assert root.findall(".//app:realtime-page[@request-id='gate-review-1']", NS)
    assert not root.findall(".//hv:behavior[@trigger='on-event']", NS)


@pytest.mark.parametrize(
    "url", ("/hv/login/", "/hv/dashboard/", "/hv/tasks/?status=bad")
)
def test_anonymous_and_error_screens_also_have_one_boundary(url):
    _, root = request(Client(), "get", url)
    assert len(root.findall(".//app:realtime", NS)) == 1
    assert root.find(".//app:realtime", NS).attrib["mode"] == "notice"


def test_navigator_document_does_not_invent_a_screen_boundary(user):
    client = Client()
    client.force_login(user)
    _, root = request(client, "get", "/hv/")
    assert root.find("hv:navigator", NS) is not None
    assert not root.findall(".//app:realtime", NS)


@pytest.mark.parametrize("kind", ("task", "category"))
@pytest.mark.parametrize("populated", (False, True))
def test_marker_is_inside_first_existing_item_with_unchanged_cardinality(
    user, kind, populated
):
    if populated:
        for n in range(22):
            if kind == "task":
                Task.objects.create(user=user, title=f"Task {n}")
            else:
                Category.objects.create(user=user, name=f"Category {n}", color="mint")
    client = Client()
    client.force_login(user)
    url = "/hv/tasks/" if kind == "task" else "/hv/categories/"
    for query, page in (
        ("?fragment=list", "1"),
        *(([("?fragment=items&page=2", "2")]) if populated else []),
    ):
        _, old = request(client, "get", url + query, modern=False)
        _, root = request(client, "get", url + query)
        assert not root.findall(".//app:realtime", NS)
        assert root.tag in {f"{{{HV}}}list", f"{{{HV}}}items"}
        items = root.findall("hv:item", NS)
        assert [item.attrib["key"] for item in items] == [
            item.attrib["key"] for item in old.findall("hv:item", NS)
        ]
        markers = root.findall(".//app:realtime-page", NS)
        assert len(markers) == 1
        assert items[0].find("app:realtime-page", NS) is markers[0]
        assert markers[0].attrib == {"request-id": "gate-review-1", "page": page}


def test_task_refresh_returns_filtered_page_one(user):
    category = Category.objects.create(user=user, name="Home", color="mint")
    for n in range(22):
        Task.objects.create(user=user, title=f"Task {n}", category=category)
    client = Client()
    client.force_login(user)
    _, root = request(
        client, "get", f"/hv/tasks/?status=active&category={category.pk}&page=2"
    )
    boundary = root.find(".//app:realtime", NS)
    parsed = urlsplit(boundary.attrib["refresh-href"])
    assert parsed.path == "/hv/tasks/"
    assert parse_qs(parsed.query) == {
        "status": ["active"],
        "category": [str(category.pk)],
        "fragment": ["list"],
    }
    assert root.find(".//app:realtime-page", NS).attrib["page"] == "2"


@pytest.mark.parametrize("request_id", (None, "", "<bad>", "é", "x" * 81, "good_ID-9"))
def test_only_bounded_ascii_request_id_is_reflected(user, request_id):
    client = Client()
    client.force_login(user)
    _, root = request(client, "get", "/hv/tasks/", request_id=request_id)
    marker = root.find(".//app:realtime-page", NS)
    assert marker.attrib["request-id"] == (
        "good_ID-9" if request_id == "good_ID-9" else "untracked"
    )


@pytest.mark.parametrize(
    "name,resource",
    [
        ("task_transition", "tasks"),
        ("task_list_transition", "tasks"),
        ("category_transition", "categories"),
        ("category_list_transition", "categories"),
        ("settings_transition", "ui"),
        ("preference_transition", "ui"),
    ],
)
def test_resource_producers_are_typed_and_keep_legacy_snackbar_back(
    user, name, resource
):
    from django.test import RequestFactory

    from todo.views import _template_response

    values = []
    for modern in (False, True):
        req = RequestFactory().get(
            "/hv/", headers={"X-HyperTodo-Request-ID": "gate-review-1"}
        )
        req.user = user
        req.hv_fragment = True
        req.hv_realtime_v1 = modern
        response = _template_response(
            req, f"fragments/{name}.xml", {"notice_message": "Saved < &"}
        )
        response.render()
        root = ET.fromstring(response.content)
        actions = root.findall("hv:behavior", NS)
        notifications = [
            node for node in actions if node.attrib["action"] == "notify-resources"
        ]
        assert len(notifications) == int(modern)
        if modern:
            assert notifications[0].attrib["resources"] == resource
            assert notifications[0].attrib["once"] == "true"
            assert not root.findall(".//hv:behavior[@action='dispatch-event']", NS)
        else:
            assert len(root.findall("hv:behavior[@action='dispatch-event']", NS)) == 1
        values.append(
            [
                (node.attrib["action"], node.attrib.get("message"))
                for node in actions
                if node.attrib["action"] in {"back", "show-snackbar"}
            ]
        )
    assert values[0] == values[1]


def typed_document(resources, *, behavior=False):
    content = (
        f'<behavior action="notify-resources" resources="{resources}"/>'
        if behavior
        else (
            '<app:realtime refresh-href="/hv/tasks/" target="task-list" '
            f'mode="list" resources="{resources}"/>'
        )
    )
    return (
        f'<doc xmlns="{HV}" xmlns:app="{APP}"><screen><body>'
        f"{content}</body></screen></doc>"
    )


@pytest.mark.parametrize("value", RESOURCES)
@pytest.mark.parametrize("behavior", (False, True))
def test_same_canonical_resource_sets_are_valid_for_boundary_and_behavior(
    value, behavior
):
    validate_hyperview_schema(typed_document(value, behavior=behavior))


@pytest.mark.parametrize(
    "value",
    (
        "",
        "owners",
        "tasks tasks",
        "ui tasks",
        "tasks,categories",
        "tasks  categories",
        " tasks",
    ),
)
@pytest.mark.parametrize("behavior", (False, True))
def test_resource_metadata_rejects_unknown_duplicate_noncanonical_values(
    value, behavior
):
    with pytest.raises(TemplateValidationError):
        validate_hyperview_schema(typed_document(value, behavior=behavior))


@pytest.mark.parametrize("populated", (False, True))
@pytest.mark.parametrize("modern", (False, True))
def test_all_40_sources_render_through_real_routes_under_both_contracts(
    user, monkeypatch, settings, populated, modern
):
    import tests.test_schema_corpus as corpus

    class CorpusClient(Client):
        def generic(self, method, path, *args, **kwargs):
            if modern and path.startswith("/hv/") and path != "/hv/session-state/":
                binding, _ = _confirm(
                    self, self.session.get("_auth_user_id") is not None
                )
                kwargs["headers"] = {
                    **(kwargs.get("headers") or {}),
                    **_headers(binding),
                    "X-HyperTodo-Request-ID": "gate-corpus-1",
                }
            response = super().generic(method, path, *args, **kwargs)
            if modern and response.get("Content-Type", "").startswith(
                "application/vnd.hyperview"
            ):
                root = ET.fromstring(response.content)
                boundaries = root.findall(".//app:realtime", NS)
                if root.find("hv:navigator", NS) is not None:
                    assert not boundaries
                elif root.tag == f"{{{HV}}}doc":
                    assert len(boundaries) == 1
                    assert len(root.findall(".//app:realtime-page", NS)) == 1
                else:
                    assert not boundaries
                    if root.attrib.get("id") not in {
                        "login-transition",
                        "logout-panel",
                    }:
                        markers = root.findall(".//app:realtime-page", NS)
                        assert len(markers) == 1, (path, root.tag)
                        assert markers[0].attrib["request-id"] == "gate-corpus-1"
            return response

    monkeypatch.setattr(corpus, "Client", CorpusClient)
    corpus.test_every_source_is_rendered_in_real_route_contexts(
        None, user, monkeypatch, "light", "en", "1.2.0", populated
    )


@pytest.mark.parametrize("modern", (False, True))
@pytest.mark.parametrize(
    "case", ("login", "password-invalid", "biometric-invalid", "biometric-throttled")
)
@pytest.mark.parametrize("request_id", ("gate-panel-2", None))
def test_auth_panel_root_key_tracks_only_negotiated_request(modern, case, request_id):
    client = Client()
    if case == "biometric-throttled":
        from todo.views import BIOMETRIC_ATTEMPT_LIMIT

        for _ in range(BIOMETRIC_ATTEMPT_LIMIT):
            request(
                client,
                "post",
                "/hv/biometric/login/",
                {"biometric_token": "synthetic-invalid"},
                modern=modern,
                request_id=request_id,
            )
    if case == "login":
        response, root = request(
            client, "get", "/hv/login/", modern=modern, request_id=request_id
        )
        assert response.status_code == 200
    else:
        url, data, status = (
            ("/hv/login/", {"username": "nobody", "password": "wrong"}, 422)
            if case == "password-invalid"
            else (
                "/hv/biometric/login/",
                {"biometric_token": "synthetic-invalid"},
                429 if case == "biometric-throttled" else 401,
            )
        )
        response, root = request(
            client, "post", url, data, modern=modern, request_id=request_id
        )
        assert response.status_code == status
    panel = (
        root
        if root.attrib.get("id") == "login-panel"
        else root.find(".//hv:view[@id='login-panel']", NS)
    )
    assert panel is not None
    if modern:
        assert panel.attrib["key"] == "auth-panel-" + (request_id or "untracked")
    else:
        assert "key" not in panel.attrib


@pytest.mark.parametrize(
    "body",
    (
        '<behavior action="notify-resources"/>',
        '<behavior action="notify-resources" app:resources="tasks"/>',
        '<behavior action="show-snackbar" resources="tasks"/>',
        '<app:realtime refresh-href="/hv/tasks/" target="task-list" mode="list"/>',
    ),
)
def test_typed_resources_are_required_and_not_a_namespace_or_action_escape(body):
    with pytest.raises(TemplateValidationError):
        validate_hyperview_schema(
            f'<doc xmlns="{HV}" xmlns:app="{APP}"><screen><body>'
            f"{body}</body></screen></doc>"
        )


@pytest.mark.parametrize(
    "url,data,field,value",
    (
        ("/hv/tasks/new/", {"title": "", "notes": 'Draft < &"'}, "notes", 'Draft < &"'),
        (
            "/hv/categories/new/",
            {"name": 'Draft < &"', "color": "invalid"},
            "name",
            'Draft < &"',
        ),
        (
            "/hv/settings/",
            {"first_name": 'Draft < &"', "email": "invalid"},
            "first_name",
            'Draft < &"',
        ),
    ),
)
def test_modern_validation_panels_preserve_drafts_and_do_not_reload(
    user, url, data, field, value
):
    client = Client()
    client.force_login(user)
    response, root = request(client, "post", url, data)
    assert response.status_code == 422
    assert root.find(f".//hv:text-field[@name='{field}']", NS).attrib["value"] == value
    assert not root.findall(".//app:realtime", NS)
    assert root.find("app:realtime-page", NS) is not None
    assert not root.findall(".//hv:behavior[@action='reload']", NS)
    assert not Task.objects.filter(user=user).exists()
    assert not Category.objects.filter(user=user).exists()


def test_every_refresh_metadata_href_has_a_real_shape(user):
    from tests.test_schema_compatibility import ROOT

    cases = {
        "tasks": ("/hv/tasks/?status=active", True),
        "categories": ("/hv/categories/", True),
        "dashboard": ("/hv/dashboard/", True),
        "task_form": ("/hv/tasks/new/", True),
        "category_form": ("/hv/categories/new/", True),
        "settings": ("/hv/settings/", True),
        "about": ("/hv/about/", True),
        "source_probe": ("/hv/source-probe/", True),
        "login": ("/hv/login/", False),
        "session_expired": ("/hv/dashboard/", False),
        "error": ("/hv/tasks/?status=bad", True),
    }
    assert {
        str(path.relative_to(ROOT))
        for path in ROOT.rglob("*.xml")
        if "refresh-href=" in path.read_text()
    } == {f"screens/{name}.xml" for name in cases}
    for name, (url, authenticated) in cases.items():
        client = Client()
        if authenticated:
            client.force_login(user)
        _, root = request(client, "get", url)
        boundary = root.find(".//app:realtime", NS)
        assert boundary is not None, name
        _, refreshed = request(client, "get", boundary.attrib["refresh-href"])
        if boundary.attrib["mode"] == "list":
            assert refreshed.tag == f"{{{HV}}}list"
            assert refreshed.attrib["id"] == boundary.attrib["target"]
            assert refreshed.find(".//app:realtime-page", NS).attrib["page"] == "1"
        else:
            assert boundary.attrib["mode"] == "notice"
            assert refreshed.tag == f"{{{HV}}}doc"
            assert (
                refreshed.find("hv:screen", NS).attrib["id"]
                == boundary.attrib["target"]
            )
            assert refreshed.find("hv:navigator", NS) is None


def test_modern_metadata_has_real_gate_exports_not_a_data_only_exemption():
    import re

    from tests.test_fragment_contract import DATA_ONLY_ELEMENTS, MOBILE_ROOT

    source = (MOBILE_ROOT / "src/realtime/gate.tsx").read_text()
    assert f'const NAMESPACE = "{APP}"' in source
    declared = re.search(r"const components = \[(.*?)\];", source, re.S)
    assert declared is not None
    assert set(re.findall(r'localName: "([\w-]+)"', declared.group(1))) == {
        "realtime",
        "realtime-page",
    }
    assert "renderChildren(element, stylesheets, dispatch, options)" in source
    assert re.search(r"return\s*\{\s*Root,\s*components,", source)
    assert not {"realtime", "realtime-page"} & DATA_ONLY_ELEMENTS
    # This is the exported gate catalog, NOT App wiring or an SDK/native run.
    # The existing App registration test remains separate and is not waived.
