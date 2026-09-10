# Negotiated realtime HXML

Modern requests now receive typed resource hints and real XML layout metadata.
App now registers the gate components and connects authenticated SSE to its
resource coordinator. Backend rendering tests alone are not native delivery
evidence. Requests without the client contract retain legacy
behaviors, forms, styles and response shapes.

For the negotiated `changes-v2` form/readonly modes, entity dependencies and bounded
full-document pages1–N refresh, see [contextual changes](realtime-changes.md).
The list/notice rules below describe the preserved v1 fallback, not the new v2
policy. Neither backend rendering result is new native acceptance.

## Version-one contract

The existing session guard must accept `X-HyperTodo-Client-Contract: realtime-v1`
and the expected session binding first. Rendering uses its request-owned marker,
not a version guess or template-supplied authentication claim. Session/Auth/CSRF
and final mandatory XSD validation remain authoritative.

Modern success producers emit:

```xml
<behavior trigger="load" action="notify-resources" resources="tasks" once="true" />
```

`resources` is **unqualified**, on both the behavior and the custom boundary. Its
required finite enum is identical in the application descriptor and XSD:
`tasks`, `categories`, `ui`, `tasks categories`, `tasks ui`, `categories ui`,
`tasks categories ui`. Unknown tokens, duplicates, spacing variants and reordered
sets are invalid. The current public extension API accepts unqualified custom
attributes; an `app:resources` descriptor is not supported. No package API changed.

Task success emits `tasks`, category success emits `categories`, preferences and
settings emit `ui`. Snackbar/back behavior is preserved. Login/logout transitions
are unchanged: generic `session-changed` is **not** a modern auth signal. Modern
screens no longer register the legacy singleton event listeners.

## Screen dependencies and layout

`app` means `https://hypertodo.app/components`. Every rendered screen has exactly
one `app:realtime` inside its existing body, outside FlatList. The navigator-only
root has none. The registered component uses public `renderChildren`, without a
new native wrapper View. No fragment introduces another boundary.

| Screens | resources | mode / target |
| --- | --- | --- |
| Tasks | tasks categories ui | list / task-list |
| Categories | tasks categories ui | list / category-list |
| Dashboard | tasks categories ui | notice / dashboard-screen |
| Task form | tasks categories ui | notice / task-form-screen |
| Category form | categories ui | notice / category-form-screen |
| Settings, login, about, errors, session-expired, source probe | ui | notice / existing screen ID |

These are dependencies, not exclusive route names: Categories displays task
counts. A `tasks` hint therefore concerns its boundary too. Form modes never
request automatic replacement or submission of a draft.

List `refresh-href` selects page 1, preserving validated task status/category
filters. The page marker is inside the **first existing item**, including the
existing empty item; pagination adds no new row or sibling. XML page markers
remain independent of native list virtualization. Multiple loaded pages require
the manual **Actualizar** policy, not reconstruction of scroll or ranges.

Categories and UI changes can affect Tasks' filter chips and styles outside
`task-list`: the resource coordinator reloads the complete canonical document,
not just the list. Focused ready lists on exactly page 1 refresh automatically;
forms and multipage lists show a persistent accessible translated notice. A hint
preserves an unsaved draft, but deliberate **Actualizar** reloads its GET document
and can discard that draft; it is not a merge or automatic save.

## Correlation is not an acknowledgement

The server echoes `X-HyperTodo-Request-ID` only when it fully matches ASCII
`[A-Za-z0-9_-]{1,80}`. Missing or invalid values become the inert literal
`untracked`, with normal Django escaping. The client generates only
`gate-{instance}-{epoch}-{sequence}`, so `untracked` cannot own a pending request.
No new HTTP error, token, topic, user ID or authentication capability is created.

Notice screens and actual panel responses carry `app:realtime-page` inside their
existing root. Included panels do not add duplicate markers. Only the client's
correlated XML layout commit may acknowledge work—not an HTTP response or marker
string by itself. Existing auth transitions retain their separate typed outcome
settlement; they do not acquire a fake page acknowledgement.

The modern `login-panel` root additionally has
`key="auth-panel-{{ realtime_request_id }}"`. This uses the existing public `key`
attribute to remount only the panel after replacement; real SDK tests found its
cached behavior otherwise retained the removed source node. No new behavior IDs,
private normalizer or liveness bypass is used. Legacy panels have no new key.

## Verification and limits

`tests/test_realtime_templates.py` exercises all 39 sources through real Django
routes in legacy and negotiated contexts, with mandatory XSD, populated/empty
lists, page 2, exact DOM placement, resource enums and required attributes,
request-ID bounds, auth-panel status/key branches and preserved invalid drafts.
Existing schema, context-free Admin, session, CSRF and UI tests remain in place.
The resource producer unit and login-panel key each have recorded permanent RED
before implementation; evidence is under `evidence/gate0-mobile/c3-templates-*`.

These backend tests do not exercise React Native layout, SSE transport or native
authentication transitions. The final App-registration regression now verifies
the explicit `AppSessionSurface` composition of `gate.components`; it remains a
separate guarantee from the source catalog. See the mobile resource/App tests and
the separately scoped [normal-App SSE demo](sse-demo-fixture.md). Historical C3
RED checkpoints remain evidence, not the current App integration status.
