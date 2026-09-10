# After-commit realtime notifications

**Configured Task, Category and profile presentation changes publish private invalidations after commit.**
Normal ORM/Admin changes use the public package `RedisBroker`; disabled settings
leave notification observers inactive. Mandatory HXML validation, authorization and existing responses
are unchanged. No Redis import or connection occurs during application startup.

## Configuration and delivery boundary

Default `HYPERVIEW["REALTIME"] = None` (or omission) disables these observers without
additional owner queries. The central package mapping requires **both** `REDIS_URL`
(`redis://`, `rediss://` or a supported local `unix://` URL) and `NAMESPACE`
(1–64 lowercase ASCII letters/digits/underscore/hyphen,
starting with a letter/digit). Use an app/environment-specific namespace; Redis
PubSub is **not isolated by Redis database number**. This mapping is separate
from `HYPERVIEW["CACHE"]` and never disables schema validation. Keep existing
`SOURCES`, `EXTRA_SCHEMAS` and `SCHEMA_EXTENSIONS` when changing this section.
The app reads the frozen `get_settings().realtime` snapshot; it does not duplicate
the package's Redis configuration parser or import a broker during startup.
Invalid central configuration is reported by package check `dj_hyperview.E022`.
The removed top-level `HYPERTODO_REALTIME`, including `None`, raises an explicit
migration error: remove it and use only `HYPERVIEW["REALTIME"]`. Enabled transport
still requires database sessions as an app policy, not a generic package rule.

The private adapter lazily constructs `RedisBroker` and calls its public
`publish_after_commit(envelope, topics, using=...)` with the captured alias.
No Redis import or connection is needed during startup. Delivery failures use
closed diagnostic codes, never credentials, owner IDs or payloads; committed
business writes remain committed, without automatic publication retry. The
[authenticated SSE endpoint](realtime-stream.md) owns delivery to current sessions.
Invalidations are hints, not durable events: reconnect/resync reconciles state.

## Mutation coverage

| Mutation | Recipients | Resources |
|---|---|---|
| Task create/save/delete, including ordinary services and Admin | Persisted old/new owner on actual database alias | `tasks` |
| Category create/save, including Admin ownership transfer | Persisted old/new category owner and existing referenced Task owners | `categories` |
| Category delete, including Admin delete-selected | Category owner and referenced Task owners captured **before** `SET_NULL` | `tasks`, `categories` |
| User first/last name/email and Profile theme/language/avatar persisted changes | Only actual old/new profile owner; no auth-only hints | `ui` |
| Public package `TemplateInvalidation` after commit | Server-selected shared UI topic for `event.using` | `ui` |

`update_fields`, including generators normalized by Django, never promotes an
unsaved in-memory owner. Deletion captures ownership before Django clears the
primary key. Aliases and primary keys use separate base64url topic components;
topics never come from client parameters or enter the public event payload.
Category ownership transfer does not repair existing Task ownership or change
Admin behavior. `SET_NULL` does not emit Task-save signals, so it is observed at
the Category boundary. No automatic coverage is promised for direct SQL,
`QuerySet.update`, `bulk_create`, `bulk_update`, or raw fixture imports.

## Transaction and public-data contract

Mutation callbacks capture immutable recipients/resources and register on the
actual `using` transaction. Rollbacks and rolled-back savepoints emit nothing.
Package template events are already after commit and are consumed directly;
this works with package cache disabled. Registration is idempotent and does not
require the optional database-template application when it is not installed.

Legacy public payloads contain only `{"version":1,"resources":[...]}` in canonical
`tasks`, `categories`, `ui` order. The pinned a22 package adds negotiated
opaque origin/entity metadata with explicit v1 projection at the endpoint; see
[contextual changes](realtime-changes.md) for exact fields and deployment limits. Internal database routing, primary keys,
template names/content and Redis configuration never enter those payloads.
The broker and [SSE controller](realtime-stream.md) own authentication, subscription
ACK, limits, reconnect/resync and transport cleanup. Exactly one initial resync
comes from the broker after all subscription acknowledgements.

## Verification

`tests/test_realtime_notifications.py` exercises actual Django services, Admin
POSTs/delete-selected, package signals, transaction/savepoint rollback and two
independent in-memory SQLite databases. Publisher injection verifies intent
ownership independently of transport. `tests/test_realtime_redis.py` adds real
Redis coverage: Admin rename delivers only to owner A, not B or a foreign namespace;
rollback emits no hint; the normal mandatory-XSD Tasks response reflects the write.
A real Django ASGI stream receives resync then the Admin invalidation and releases
its admission on disconnect. Ordered resync barriers test isolation without sleeps.

Run Redis acceptance explicitly with `HYPERTODO_REDIS_INTEGRATION=1` and
`HYPERTODO_REDIS_TEST_URL=redis://127.0.0.1:6379/14`. Tests generate unique namespaces,
close subscriptions and never flush Redis. SQLite is test-owned; no live database,
data migration, package installation or native run is involved. The historical focused
checkpoint was 44 passes (42 intent controls and 2 real-Redis tests), not a full matrix.
