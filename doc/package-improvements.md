# dj-hyperview improvement candidates

This document records package-level opportunities revealed by HyperTodo. It is a
candidate backlog, not a promise that every item belongs in dj-hyperview. Each item
must be reproduced and specified in the package repository before implementation.

## Recommended next investigation

Start with response-shape primitives. The most repeated integration failure was a
valid full `doc` being returned to an in-place replacement that required a fragment.
The package already validates XML and provides template responses, so it is the
natural layer to make that distinction explicit.

## Candidate backlog

| Priority | Candidate | Evidence from HyperTodo | Proposed package direction |
| --- | --- | --- | --- |
| P1 | Explicit document and fragment responses | Several mutations produced `XMLRestrictedElementFound` after returning `doc` to a replacement target. Version 0.1.0a7 recognizes fragment requests in middleware but exports only document-default response classes. | Add `HYPERVIEW_FRAGMENT_MEDIA_TYPE` plus explicit fragment response/template response classes with fragment-root validation. Keep the existing document response backward compatible. |
| P1 | HXML error-response utilities | Session expiry, CSRF failure, unsupported methods, validation errors, and missing objects all required consumer-owned handlers to prevent HTML or redirects. | Provide opt-in helpers or mixins that preserve status codes and the Hyperview media type while rendering consumer templates. Do not ship product screens. |
| P1 | Public source capability protocol | Third-party source caching currently depends on private `_dj_hyperview_cacheable` and `_dj_hyperview_cache_safe` hooks. | Replace or complement private hooks with a documented public protocol for source identity, revision, cacheability, and transaction safety. |
| P2 | Template validation command | Consumer tests validate known screens, but there is no single release gate that enumerates every filesystem and active database template. | Add a management command that validates configured templates and reports canonical name, source, and failure code without rendering business-specific context. |
| P2 | Operational cache invalidation command | Database writes invalidate automatically, while filesystem edits need Python-shell calls or cache bypass. | Add a management command to invalidate one or more canonical names safely. Avoid any command that flushes the complete cache backend. |
| P2 | Resolver diagnostics | Real-time overrides are harder to debug when the caller cannot easily see which source and revision won. | Add opt-in debug metadata or structured logging for canonical name, winning source, revision, cache hit, fallback, and failure mode. Never expose filesystem paths in production by default. |
| P3 | Consumer integration recipes | Correct session login, CSRF, fragments, pagination, and Expo transport required knowledge from several layers. | Add concise recipes linking server response patterns to Hyperview client actions. Keep Expo bootstrapping outside the core API contract. |

## Important non-goals

The package should not absorb HyperTodo's business or presentation layer:

- task and category models;
- dashboard layouts or mobile templates;
- application-specific navigation bars, side menus, snackbars, or swipe actions;
- pagination policy for a product's querysets;
- Expo project generation or native build orchestration.

dj-hyperview should provide safe server primitives. The consuming Django project
continues to own its templates, context, URLs, authorization, and domain behavior.

## Package correctness gate from the 0.1.0a7 audit

The consumer API backlog must not displace correctness work already identified in
the package audit. Before adding convenience APIs, triage these independent work
units in the package repository:

1. Multi-database delete routing, SQL parameter-aware mutation batches, and
   model-level byte-exact name validation.
2. Mandatory XML autoescaping, raw fixture compatibility, and legacy-name admin
   recovery.
3. Invalid-name propagation, Django template backend subclass support, and
   consistent charset parsing.
4. Initial cache publication, source identity divergence, and missing-root policy.
5. Filesystem cache deployment guidance, admin delete-template parity, `py.typed`,
   and a package `__version__` attribute.

The detailed audit remains the source of scenarios and proposed regression tests.
Each item still needs its own failing package test before implementation.

## Suggested validation order

1. Reproduce the candidate with the smallest standalone Django test.
2. Write the public contract and compatibility expectations.
3. Add a failing package test before implementation.
4. Update package documentation and release notes with the code.
5. Reinstall the resulting pre-release in HyperTodo and repeat the relevant physical
   device flow.

## Findings that do not currently imply a package defect

- Hyperview's missing native time input is a client-library capability boundary.
- React Native cookie handling across redirects is avoided by the consumer's direct
  response flow.
- Safe-area layout and gesture responder ownership belong to the mobile shell.
- Expo Go account authorization and LAN addressing are Expo development concerns.
