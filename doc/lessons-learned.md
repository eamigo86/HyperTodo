# Lessons learned while building HyperTodo

This is a living record of the integration lessons discovered while using
dj-hyperview from a real Django and Expo application. It intentionally separates
portable lessons from HyperTodo-specific design choices.

## The short version

1. Treat the mobile client as a small native shell, not as a second application.
2. Return a full HXML document for navigation and a fragment for in-place updates.
3. Return authenticated destinations directly; do not depend on login redirects.
4. Keep server-rendered elements addressable with stable IDs.
5. Use custom React Native components only for interactions HXML cannot express.
6. Test on a physical device early. Layout wrappers, safe areas, keyboards, and
   responder ownership are difficult to prove from XML or Jest alone.

## Responsibility boundary

| Concern | Owner |
| --- | --- |
| Screen content, filters, validation, and mutation outcomes | Django and HXML |
| User data and authorization | Django |
| Template precedence and optional cache | dj-hyperview |
| Native boot, safe areas, navigation host, and transport | Expo shell |
| Device-only gestures and global animated overlays | Small custom mobile components |

This boundary avoids duplicating domain state in React Native while accepting
that server-driven rendering does not remove the need for a correctly initialized
native host.

## HXML response shapes matter

A navigation request may return a complete `doc`. An action that replaces an
existing element must return a compatible fragment or transition instead. Returning
a complete document to a replacement target causes Hyperview to reject the response
with `XMLRestrictedElementFound: Restricted <doc> tag found in the response`.

Practical rules:

- Send `application/vnd.hyperview_fragment+xml` for replacement, append, and
  prepend responses. The response root must be the bare element being inserted;
  `doc`, `navigator`, `screen`, and `body` are restricted in fragment mode.
- Use stable element IDs for every replacement target.
- Make the response shape part of each endpoint test.
- Validate the media type and XML structure, not only the HTTP status.
- For a custom component calling `onUpdate` with `replace`, pass its `targetId`
  explicitly when no Hyperview behavior element exists.

Hyperview does not rebuild the stylesheet after a partial replacement. Every style
ID used by a returned fragment must already exist in the screen document. HyperTodo
keeps one shared dashboard-content template for the initial screen and the bare
replacement, and a regression test rejects fragment style IDs not declared by that
screen.

## Hyperview 0.110.0 client constraints

Several HXML constructs look more flexible than their runtime behavior:

- Width, height, percentage dimensions, and negative margins belong in `style`
  declarations. Attributes with those names on content elements are ignored.
- Dynamic progress and activity dimensions need a finite set of declared bucket
  styles selected by the Django template. Calculated inline styles do not exist.
- A `header` element is a `view` alias. When the default host header is disabled,
  build the 44-point destination header as a normal view and give both side slots
  equal fixed widths so the title remains centered.
- Hyperview's `safe-area` uses React Native's older iOS-only safe-area component.
  The Expo host should own device insets instead.
- Hyperview's `avoid-keyboard` is iOS-only and wraps children in a position-mode
  keyboard-avoiding view. It can collapse flex layouts; prefer a scrolling body,
  a `flexGrow` content container, and a bounded hero.
- An `option` label must be a child `text` element. A bare text node does not render.
- On a scrolling view, `style` decorates the viewport. Child direction, gap,
  padding, and justification belong in `content-container-style`.
- `href-style` decorates the native touch wrapper. Use it to provide a 44-point
  hit area without enlarging a small visual icon.

## Sessions work when redirects are avoided

The mobile client can use ordinary Django sessions and CSRF protection. The
reliable flow is:

1. Submit the login form through Hyperview.
2. Establish the session cookie on the same response.
3. Return the destination HXML directly with status 200.
4. Send `credentials: include` on later requests and preserve Hyperview headers.

An iOS redirect is a poor place to establish the cookie because React Native's
redirect and cookie behavior is not a stable application contract. Authentication,
object ownership, CSRF failures, and session expiry still need explicit HXML tests.

## Forms need native-aware contracts

Hyperview 0.110.0 supports a date input but does not provide an equivalent native
time input. HyperTodo therefore submits a date and validated `HH:MM` text separately,
then combines them in Django using the configured timezone.

Validation feedback should identify the field, remain inside the form response,
and use status 422. A generic message at the top is useful only as a summary; it
must not replace field-level errors.

## Navigation and safe areas belong to the shell

Hyperview navigation actions require a mounted `NavigationContainer`. The entire
screen hierarchy must also sit inside safe-area providers so content does not collide
with an iPhone notch, status indicators, or the home indicator.

Links can introduce native wrapper views. Width and flex rules sometimes need to be
applied to the clickable wrapper as well as the visible child. This is why equal
dashboard cards must be verified on the actual renderer, not inferred from the inner
HXML styles.

HyperTodo uses separate top and bottom host safe-area views: the top inset matches
the blue screen chrome and the bottom inset matches the light canvas and tab bar.
The application status bar is light over the blue header, while temporary light
overlays such as the animated splash own a dark status-bar override.

## Lists require stable refresh behavior

Pull-to-refresh and infinite scrolling are separate contracts:

- Refresh replaces the stable list container from page one.
- Infinite scroll appends only the next item fragment.
- Mutations dispatch a refresh event or return an updated target immediately.
- Pagination parameters and fragment names must be validated on the server.

Without that separation, a successful create can return to a stale list or append a
full document where only items are allowed.

## Cache invalidation is part of real-time editing

Database template publication can invalidate cached names after transaction commit.
Filesystem changes cannot emit that database signal. During active XML development,
either bypass the shared cache or explicitly invalidate the edited template.

Use separate Redis logical databases and namespaces for development and tests. Never
use `FLUSHDB` or `FLUSHALL` against a shared service.

## Custom components should stay narrow

HyperTodo added native code only where the product interaction required it:

- an animated side menu and full-screen scrim;
- swipe actions with responder arbitration;
- a global animated snackbar behavior;
- an animated splash handoff.

The server still chooses URLs, target state, and mutation results. Fixed labels for
native-only controls remain presentation details in the shell. Custom components must
preserve Hyperview update semantics rather than creating a parallel client-side domain
model.

The swipe implementation exposed two reusable mobile lessons:

- A parent gesture around interactive children needs capture-phase arbitration and
  termination protection.
- Keeping the task card stationary requires an overlaid action tray; translating the
  foreground moves and can obscure the title.

## Expo development workflow

Expo Go is the quickest physical-device loop while all required native modules are
already bundled in Expo Go. A development build becomes necessary when adding a native
dependency or testing native configuration such as launcher icons.

For QR-based LAN testing:

- Expo CLI and Expo Go must use the same Expo account when manifest authorization is
  required.
- Django must listen on a reachable interface and allow the Mac's LAN address.
- The mobile API URL must use that LAN address, never `127.0.0.1` from the phone.
- Restart Metro after changing its mode or backend URL.

## Quality strategy

Strict TDD and branch-aware coverage protect the owned Django behavior. Mobile tests
focus on the custom shell, network adapter, behaviors, and components rather than
claiming coverage over Hyperview internals. Physical iOS and Android acceptance remains
mandatory because native layout and interaction bugs can survive both suites.

## Before promoting a consumer finding to the package

- Reproduce it outside HyperTodo-specific business logic.
- Confirm the current dj-hyperview API does not already solve it.
- Write a failing package-level contract test.
- Prefer an opt-in primitive over a product-specific abstraction.
- Record migration and compatibility impact before changing public behavior.

See [Package improvement candidates](package-improvements.md) for the current backlog.
