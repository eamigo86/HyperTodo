"""The two-palette contrast ledger.

Every row resolves BOTH colours from the rendered stylesheet of a user whose
Profile carries that palette, never from a literal in this file, so repointing a
style at a different token fails here rather than shipping.

LIGHT_EXEMPT records the pairs that were already below their floor before this
work started. They are not fixed, because the brief for this round was that the
light palette stays byte-identical, and moving them would have made the golden in
test_theme_tokens.py unfalsifiable. They are pinned rather than skipped: a pair
in this list must STILL FAIL, so the day one is repaired the list has to shrink.
DARK has no exemptions at all.
"""

import pytest

from tests.test_forms_ui import contrast_ratio, over, style_by_id
from tests.test_theme_tokens import SCREENS, render_screen

pytestmark = pytest.mark.django_db

# Hyperview's press feedback is an opacity, and `pressed` reaches every descendant:
# a styled child declaring no pressed rule of its own falls back to 0.7 and React
# Native NESTS the layers, so a label inside a dimmed row lands at 0.49. A pressed
# FILL is the only feedback that survives, and it has to be visible against the
# surface the row actually sits on.
MIN_PRESS_FILL_CONTRAST = 1.2

# WCAG 1.4.3 large text is >=24px, or >=18.66px bold. Everything else owes 4.5:1.
# 1.4.11 puts graphics, glyph tints and control boundaries at 3:1.
AA, LARGE, GRAPHIC = 4.5, 3.0, 3.0

# (screen, "rule.attribute" foreground, "rule.attribute" background, floor)
PAIRS = (
    # --- dashboard: hero band -------------------------------------------------
    ("dashboard", "hero-initials.color", "hero-avatar.backgroundColor", AA),
    ("dashboard", "hero-greeting.color", "hero.backgroundColor", AA),
    ("dashboard", "hero-name.color", "hero.backgroundColor", AA),
    ("dashboard", "hero-headline.color", "hero.backgroundColor", LARGE),
    ("dashboard", "hero-caption.color", "hero.backgroundColor", AA),
    ("dashboard", "hero-avatar.backgroundColor", "hero.backgroundColor", GRAPHIC),
    (
        "dashboard",
        "progress-fill.backgroundColor",
        "progress-track.backgroundColor",
        GRAPHIC,
    ),
    # --- dashboard: stat cards ------------------------------------------------
    ("dashboard", "stat-label.color", "stat-card.backgroundColor", AA),
    ("dashboard", "stat-count.color", "stat-card.backgroundColor", LARGE),
    ("dashboard", "stat-note.color", "stat-card.backgroundColor", AA),
    ("dashboard", "stat-note-good.color", "stat-card.backgroundColor", AA),
    ("dashboard", "stat-note-alert.color", "stat-card.backgroundColor", AA),
    ("dashboard", "stat-card.backgroundColor", "screen.backgroundColor", 1.03),
    # --- dashboard: alert -----------------------------------------------------
    ("dashboard", "alert-title.color", "alert-card.backgroundColor", AA),
    ("dashboard", "alert-action-text.color", "alert-action.backgroundColor", AA),
    # --- dashboard: up next ---------------------------------------------------
    ("dashboard", "section.color", "screen.backgroundColor", AA),
    ("dashboard", "section-link-text.color", "screen.backgroundColor", AA),
    ("dashboard", "row-title.color", "row.backgroundColor", AA),
    ("dashboard", "row-meta.color", "row.backgroundColor", AA),
    ("dashboard", "lavender-text.color", "row.backgroundColor", AA),
    ("dashboard", "yellow-text.color", "row.backgroundColor", AA),
    ("dashboard", "mint-text.color", "row.backgroundColor", AA),
    ("dashboard", "pink-text.color", "row.backgroundColor", AA),
    ("dashboard", "green-text.color", "row.backgroundColor", AA),
    ("dashboard", "toggle.borderColor", "row.backgroundColor", GRAPHIC),
    ("dashboard", "row-chevron.tintColor", "row.backgroundColor", GRAPHIC),
    ("dashboard", "meta.color", "screen.backgroundColor", AA),
    # --- dashboard: week chart ------------------------------------------------
    ("dashboard", "bar.backgroundColor", "week-card.backgroundColor", GRAPHIC),
    ("dashboard", "bar-today.backgroundColor", "week-card.backgroundColor", GRAPHIC),
    ("dashboard", "bar-label.color", "week-card.backgroundColor", AA),
    ("dashboard", "bar-label-today.color", "week-card.backgroundColor", AA),
    # The dashboard chips carry a CATEGORY fill, never the screen. Measuring this
    # ink against screen.backgroundColor passed in both palettes while the dark
    # theme actually drew near-white text on the unchanged pastels.
    *(
        ("dashboard", "chip-text.color", f"{tone}.backgroundColor", AA)
        for tone in ("lavender", "yellow", "mint", "pink", "green")
    ),
    # --- dashboard: side menu -------------------------------------------------
    ("dashboard", "side-menu-name.color", "side-menu-header.backgroundColor", AA),
    ("dashboard", "side-menu-email.color", "side-menu-header.backgroundColor", AA),
    ("dashboard", "side-menu-initials.color", "side-menu-avatar.backgroundColor", AA),
    ("dashboard", "side-menu-link-text.color", "side-menu-panel.backgroundColor", AA),
    (
        "dashboard",
        "side-menu-link-text.color",
        "side-menu-link-active.backgroundColor",
        AA,
    ),
    (
        "dashboard",
        "side-menu-icon.tintColor",
        "side-menu-panel.backgroundColor",
        GRAPHIC,
    ),
    (
        "dashboard",
        "side-menu-icon-active.tintColor",
        "side-menu-link-active.backgroundColor",
        GRAPHIC,
    ),
    (
        "dashboard",
        "side-menu-logout-text.color",
        "side-menu-footer.backgroundColor",
        AA,
    ),
    (
        "dashboard",
        "side-menu-logout-icon.tintColor",
        "side-menu-footer.backgroundColor",
        GRAPHIC,
    ),
    (
        "dashboard",
        "side-menu-footer.borderTopColor",
        "side-menu-footer.backgroundColor",
        GRAPHIC,
    ),
    # --- shared bottom navigation --------------------------------------------
    *(
        pair
        for screen in ("dashboard", "tasks", "categories", "settings")
        for pair in (
            (screen, "nav-label.color", "bottom-navigation.backgroundColor", AA),
            (screen, "nav-label-active.color", "bottom-navigation.backgroundColor", AA),
            (
                screen,
                "nav-icon.tintColor",
                "bottom-navigation.backgroundColor",
                GRAPHIC,
            ),
            (
                screen,
                "nav-icon-active.tintColor",
                "bottom-navigation.backgroundColor",
                GRAPHIC,
            ),
            (screen, "nav-add-symbol.color", "nav-add.backgroundColor", LARGE),
        )
    ),
    # --- shared screen header -------------------------------------------------
    *(
        pair
        for screen in ("tasks", "categories", "settings", "task_form", "category_form")
        for pair in (
            (screen, "back-chevron.color", "screen-header.backgroundColor", LARGE),
            (screen, "back-label.color", "screen-header.backgroundColor", LARGE),
            (
                screen,
                "screen-header-title.color",
                "screen-header.backgroundColor",
                LARGE,
            ),
        )
    ),
    # --- tasks ----------------------------------------------------------------
    ("tasks", "filter-summary.color", "screen.backgroundColor", AA),
    ("tasks", "chip-text.color", "chip.backgroundColor", AA),
    ("tasks", "chip-text-active.color", "chip-active.backgroundColor", AA),
    ("tasks", "task-title.color", "task.backgroundColor", AA),
    ("tasks", "meta.color", "task.backgroundColor", AA),
    ("tasks", "empty-title.color", "empty-card.backgroundColor", AA),
    ("tasks", "empty-copy.color", "empty-card.backgroundColor", AA),
    # --- categories -----------------------------------------------------------
    *(
        ("categories", foreground, f"{tone}.backgroundColor", AA)
        for foreground in ("name-on-fill.color", "meta-on-fill.color")
        for tone in ("lavender", "yellow", "mint", "pink", "green")
    ),
    ("categories", "name.color", "card.backgroundColor", LARGE),
    ("categories", "meta.color", "card.backgroundColor", AA),
    ("categories", "action.color", "card.backgroundColor", AA),
    ("categories", "danger.color", "card.backgroundColor", AA),
    ("categories", "action-button.borderColor", "card.backgroundColor", GRAPHIC),
    ("categories", "action-button-danger.borderColor", "card.backgroundColor", GRAPHIC),
    ("categories", "primary-text.color", "primary.backgroundColor", LARGE),
    ("categories", "empty-title.color", "empty-card.backgroundColor", AA),
    ("categories", "empty-copy.color", "empty-card.backgroundColor", AA),
    # --- settings -------------------------------------------------------------
    ("settings", "section.color", "card.backgroundColor", AA),
    ("settings", "label.color", "card.backgroundColor", AA),
    ("settings", "field.color", "field.backgroundColor", AA),
    ("settings", "field.borderColor", "card.backgroundColor", GRAPHIC),
    ("settings", "field-invalid.borderColor", "field-invalid.backgroundColor", GRAPHIC),
    ("settings", "field-error.color", "card.backgroundColor", AA),
    ("settings", "error-text.color", "error-card.backgroundColor", AA),
    ("settings", "action-row-text.color", "action-row.backgroundColor", AA),
    ("settings", "meta.color", "card.backgroundColor", AA),
    # The biometric switch. Four rows and not two: the TRACK against the surface
    # behind it as well as the thumb against the track, in BOTH states. That
    # missing track-against-surface row is exactly how dark's #5A6178 once
    # shipped at 2.74:1, and the selected track against the sheet is the pair the
    # login screen still does not measure (this file's own note at the optin rows
    # says so). It is closed here, on the new host.
    # The surface is action-row and NOT card: the switch sits inside
    # <view style="action-row switch-row"> (partials/security_card.xml), action-row
    # fills with theme.field, and switch-row adds layout only. Measured on card the
    # ledger read 3.44/3.34 light while the screen actually renders 3.13/3.04, so a
    # light `field` moved to a value this palette already ships as field_pressed
    # would drop the real track to 2.96 and 2.88 with every row still green.
    ("settings", "optin-switch.backgroundColor", "action-row.backgroundColor", GRAPHIC),
    (
        "settings",
        "optin-switch.color",
        "optin-switch.backgroundColor",
        GRAPHIC,
    ),
    (
        "settings",
        "optin-switch:selected=true.backgroundColor",
        "action-row.backgroundColor",
        GRAPHIC,
    ),
    (
        "settings",
        "optin-switch:selected=true.color",
        "optin-switch:selected=true.backgroundColor",
        GRAPHIC,
    ),
    # The photo row. avatar-gate's own fill and border are NOT pinned: a disabled
    # control is exempt under 1.4.3 and 1.4.11, and a floor there would force the
    # inert box to look pressable. Its TEXT is pinned, because the instruction is
    # the only thing in that box a user has to be able to read.
    ("settings", "avatar-action.borderColor", "card.backgroundColor", GRAPHIC),
    ("settings", "avatar-action-text.color", "card.backgroundColor", AA),
    ("settings", "avatar-gate-text.color", "avatar-gate.backgroundColor", AA),
    ("settings", "avatar-gate-note.color", "card.backgroundColor", AA),
    ("settings", "version.color", "screen.backgroundColor", AA),
    ("settings", "button-text.color", "button.backgroundColor", LARGE),
    ("settings", "card.backgroundColor", "screen.backgroundColor", 1.03),
    # --- task form ------------------------------------------------------------
    ("task_form", "section.color", "card.backgroundColor", AA),
    ("task_form", "label.color", "card.backgroundColor", AA),
    ("task_form", "field.color", "field.backgroundColor", AA),
    ("task_form", "field-text.color", "picker-box.backgroundColor", AA),
    ("task_form", "field-error.color", "card.backgroundColor", AA),
    ("task_form", "error-text.color", "error-card.backgroundColor", AA),
    ("task_form", "date-modal-action.color", "date-modal.backgroundColor", AA),
    ("task_form", "button-text.color", "button.backgroundColor", LARGE),
    # --- category form --------------------------------------------------------
    ("category_form", "color-option-text.color", "color-option.backgroundColor", AA),
    (
        "category_form",
        "color-option-text:selected=true.color",
        "color-option:selected=true.backgroundColor",
        AA,
    ),
    (
        "category_form",
        "color-swatch.borderColor",
        "color-option.backgroundColor",
        GRAPHIC,
    ),
    ("category_form", "button-text.color", "button.backgroundColor", LARGE),
    # --- login ----------------------------------------------------------------
    ("login", "login-brand.color", "login-body.backgroundColor", LARGE),
    ("login", "hero-mark-check.color", "hero-mark.backgroundColor", LARGE),
    ("login", "card-title.color", "login-sheet.backgroundColor", LARGE),
    ("login", "card-copy.color", "login-sheet.backgroundColor", AA),
    ("login", "label.color", "login-sheet.backgroundColor", AA),
    ("login", "field.color", "field.backgroundColor", AA),
    ("login", "field.borderColor", "login-sheet.backgroundColor", GRAPHIC),
    ("login", "error-text.color", "error-card.backgroundColor", AA),
    ("login", "hint.color", "login-sheet.backgroundColor", AA),
    ("login", "optin-label.color", "login-sheet.backgroundColor", AA),
    ("login", "biometric-icon.tintColor", "biometric-button.backgroundColor", GRAPHIC),
    (
        "login",
        "biometric-button.borderColor",
        "login-sheet.backgroundColor",
        GRAPHIC,
    ),
    ("login", "button-text.color", "button.backgroundColor", LARGE),
    ("login", "optin-switch.color", "optin-switch.backgroundColor", GRAPHIC),
    # The TRACK against the sheet behind it, not only the knob against the track.
    # That missing row is exactly how dark's #5A6178 shipped at 2.74:1 on surface
    # (see the switch_off note in todo/theme.py); the fix added the rows for the
    # appearance pill and left the login switch measuring its own knob. It passes
    # today only because both controls happen to share one token, so the day that
    # token splits per role -- which this file's own doctrine invites -- this is
    # what fails instead of the sign-in screen shipping an invisible control edge.
    ("login", "optin-switch.backgroundColor", "login-sheet.backgroundColor", GRAPHIC),
    (
        "login",
        "optin-switch:selected=true.color",
        "optin-switch:selected=true.backgroundColor",
        GRAPHIC,
    ),
    # --- preference switcher, on the ONE screen that hosts it -----------------
    # It used to be two. Settings became one real form with one Save button, and a
    # control that commits on tap cannot share that screen, so the drawer is the
    # only host left -- derived and pinned by
    # tests/test_preferences.py::test_the_preference_switcher_declares_its_styles
    # _on_every_screen_that_can_host_it, which is also what would force these rows
    # to grow a second screen again.
    ("dashboard", "preference-label.color", "side-menu-panel.backgroundColor", AA),
    *(
        (
            "dashboard",
            foreground,
            background,
            floor,
        )
        for foreground, background, floor in (
            (
                "pref-toggle-track.backgroundColor",
                "side-menu-panel.backgroundColor",
                GRAPHIC,
            ),
            (
                "pref-toggle-track-on.backgroundColor",
                "side-menu-panel.backgroundColor",
                GRAPHIC,
            ),
            (
                "pref-toggle-knob.backgroundColor",
                "pref-toggle-track.backgroundColor",
                GRAPHIC,
            ),
            (
                "pref-toggle-knob.backgroundColor",
                "pref-toggle-track-on.backgroundColor",
                GRAPHIC,
            ),
            ("pref-toggle-label.color", "side-menu-panel.backgroundColor", AA),
            (
                "preference-option-text.color",
                "preference-option.backgroundColor",
                AA,
            ),
            (
                "preference-option-text-current.color",
                "preference-option-current.backgroundColor",
                AA,
            ),
        )
    ),
    # --- error / session expired ---------------------------------------------
    ("error", "error-title.color", "error-card.backgroundColor", LARGE),
    ("error", "error-copy.color", "error-card.backgroundColor", AA),
    ("error", "error-button-text.color", "error-button.backgroundColor", LARGE),
    ("session_expired", "title.color", "card.backgroundColor", LARGE),
    ("session_expired", "copy.color", "card.backgroundColor", AA),
    ("session_expired", "button-text.color", "button.backgroundColor", LARGE),
)

# (screen, pressed fill, surface it sits on, ink, pressed ink, floor for that ink)
PRESSED = (
    (
        "dashboard",
        "side-menu-link:pressed=true.backgroundColor",
        "side-menu-panel.backgroundColor",
        "side-menu-link-text.color",
        "side-menu-link-text:pressed=true.color",
        AA,
    ),
    (
        "dashboard",
        "side-menu-logout:pressed=true.backgroundColor",
        "side-menu-footer.backgroundColor",
        "side-menu-logout-text.color",
        "side-menu-logout-text:pressed=true.color",
        AA,
    ),
    (
        "settings",
        "action-row:pressed=true.backgroundColor",
        "action-row.backgroundColor",
        "action-row-text.color",
        "action-row-text:pressed=true.color",
        AA,
    ),
    (
        "settings",
        "button:pressed=true.backgroundColor",
        "card.backgroundColor",
        "button-text.color",
        "button-text:pressed=true.color",
        LARGE,
    ),
    (
        "task_form",
        "button:pressed=true.backgroundColor",
        "card.backgroundColor",
        "button-text.color",
        "button-text:pressed=true.color",
        LARGE,
    ),
    (
        "settings",
        "avatar-action:pressed=true.backgroundColor",
        "card.backgroundColor",
        "avatar-action-text.color",
        "avatar-action-text:pressed=true.color",
        AA,
    ),
    # The pre-1.1.0 category card, which had no pressed rule at ALL: the row fell
    # to 0.7, React Native nested it, and the labels landed at 0.49 -- 2.05:1 for
    # Edit in light, 2.46:1 for Delete, against idle values of 4.94 and 6.57. It
    # ships to the oldest installed binaries and nothing else guards it.
    (
        "categories",
        "action-button:pressed=true.backgroundColor",
        "card.backgroundColor",
        "action.color",
        "action:pressed=true.color",
        AA,
    ),
    (
        "categories",
        "action-button-danger:pressed=true.backgroundColor",
        "card.backgroundColor",
        "danger.color",
        "danger:pressed=true.color",
        AA,
    ),
    # BOTH chip compositions, on BOTH hosts. Naming only `settings` and only the
    # plain chip left three quarters of this control unmeasured: the drawer's copy
    # is duplicated by hand, and createStyleProp concatenates the pressed rules of
    # every composed id with the LAST winning (services/index.ts:33-41), so the
    # CURRENT chip took preference-option's row_press over its own chip_active --
    # 1.13 light and 1.17 dark against the 1.2 floor, with the held ink at 4.489,
    # under AA. It carries its own pressed fill now, and this is what says so.
    *(
        (
            "dashboard",
            f"{rule}:pressed=true.backgroundColor",
            f"{rule}.backgroundColor",
            f"{ink}.color",
            f"{ink}:pressed=true.color",
            AA,
        )
        for rule, ink in (
            ("preference-option", "preference-option-text"),
            ("preference-option-current", "preference-option-text-current"),
        )
    ),
    (
        "dashboard",
        "pref-toggle-row:pressed=true.backgroundColor",
        "side-menu-panel.backgroundColor",
        "pref-toggle-label.color",
        "pref-toggle-label:pressed=true.color",
        AA,
    ),
    (
        "categories",
        "primary:pressed=true.backgroundColor",
        "screen.backgroundColor",
        "primary-text.color",
        "primary-text:pressed=true.color",
        LARGE,
    ),
)

# Pairs that were ALREADY below their floor before todo/theme.py existed. Every one
# is a colour written as a literal somewhere nobody parametrised, and every one is
# still exactly the colour it was. Repair means moving a light token, which is a
# separate, visible change: see the report accompanying this work.
LIGHT_EXEMPT = frozenset(
    {
        ("dashboard", "hero-greeting.color", "hero.backgroundColor"),
        ("dashboard", "hero-name.color", "hero.backgroundColor"),
        ("dashboard", "hero-caption.color", "hero.backgroundColor"),
        (
            "dashboard",
            "progress-fill.backgroundColor",
            "progress-track.backgroundColor",
        ),
        ("dashboard", "stat-note.color", "stat-card.backgroundColor"),
        ("dashboard", "stat-note-good.color", "stat-card.backgroundColor"),
        ("dashboard", "section-link-text.color", "screen.backgroundColor"),
        ("dashboard", "row-meta.color", "row.backgroundColor"),
        ("dashboard", "yellow-text.color", "row.backgroundColor"),
        ("dashboard", "mint-text.color", "row.backgroundColor"),
        ("dashboard", "toggle.borderColor", "row.backgroundColor"),
        ("dashboard", "meta.color", "screen.backgroundColor"),
        ("dashboard", "bar.backgroundColor", "week-card.backgroundColor"),
        ("dashboard", "bar-label.color", "week-card.backgroundColor"),
        ("dashboard", "bar-label-today.color", "week-card.backgroundColor"),
        (
            "dashboard",
            "side-menu-footer.borderTopColor",
            "side-menu-footer.backgroundColor",
        ),
        ("categories", "action-button.borderColor", "card.backgroundColor"),
        ("categories", "action-button-danger.borderColor", "card.backgroundColor"),
        ("settings", "field.borderColor", "card.backgroundColor"),
        ("task_form", "date-modal-action.color", "date-modal.backgroundColor"),
        (
            "category_form",
            "color-option-text:selected=true.color",
            "color-option:selected=true.backgroundColor",
        ),
        ("category_form", "color-swatch.borderColor", "color-option.backgroundColor"),
        ("login", "field.borderColor", "login-sheet.backgroundColor"),
    }
)


@pytest.fixture(scope="module")
def documents(django_db_setup, django_db_blocker):
    """Render every screen once per palette rather than once per ledger row."""
    from django.contrib.auth import get_user_model

    from todo.models import Profile

    rendered = {}
    with django_db_blocker.unblock():
        for palette in ("light", "dark"):
            account = get_user_model().objects.create_user(
                username=f"ledger-{palette}", password="correct-horse"
            )
            Profile.objects.create(user=account, theme=palette)
            account.refresh_from_db()
            for screen in SCREENS:
                rendered[palette, screen] = render_screen(
                    account, screen, palette=palette
                )
    return rendered


def resolve(root, spec):
    """Return one colour named as rule[:state].attribute from a stylesheet.

    Args:
        root: Rendered screen document.
        spec: Ledger reference, e.g. button:pressed=true.backgroundColor.

    Returns:
        The declared #RRGGBB value.
    """
    rule, attribute = spec.rsplit(".", 1)
    if ":" in rule:
        rule, state = rule.split(":", 1)
        key, value = state.split("=", 1)
        node = style_by_id(root, rule).find(
            f"./{{https://hyperview.org/hyperview}}modifier[@{key}='{value}']"
            f"/{{https://hyperview.org/hyperview}}style"
        )
        assert node is not None, f"missing modifier {spec}"
    else:
        node = style_by_id(root, rule)
    assert attribute in node.attrib, f"missing attribute {spec}"
    return node.attrib[attribute]


@pytest.mark.parametrize("palette", ["light", "dark"])
@pytest.mark.parametrize("row", PAIRS, ids=lambda r: f"{r[0]}-{r[1]}-on-{r[2]}")
def test_every_declared_pair_clears_its_floor(palette, row, documents):
    screen, foreground, background, floor = row
    root = documents[palette, screen]
    ratio = contrast_ratio(resolve(root, foreground), resolve(root, background))
    exempt = palette == "light" and (screen, foreground, background) in LIGHT_EXEMPT

    if exempt:
        # Pinned, not skipped: the day this pair is repaired it has to come off the
        # exemption list, so the list can only ever shrink.
        assert ratio < floor, (
            f"{screen}: {foreground} on {background} now clears {floor} at "
            f"{ratio:.2f} -- remove it from LIGHT_EXEMPT"
        )
    else:
        assert ratio >= floor, (
            f"{palette}/{screen}: {foreground} on {background} is {ratio:.2f}, "
            f"floor {floor}"
        )


@pytest.mark.parametrize("palette", ["light", "dark"])
@pytest.mark.parametrize("row", PRESSED, ids=lambda r: f"{r[0]}-{r[1]}")
def test_every_pressed_row_stays_readable_while_it_is_held(palette, row, documents):
    screen, fill_spec, surface_spec, ink_spec, pressed_ink_spec, floor = row
    root = documents[palette, screen]
    fill = resolve(root, fill_spec)
    surface = resolve(root, surface_spec)
    ink = resolve(root, ink_spec)
    pressed_ink = resolve(root, pressed_ink_spec)

    assert contrast_ratio(fill, surface) >= MIN_PRESS_FILL_CONTRAST, (
        f"{palette}/{screen}: pressed fill {fill} is invisible on {surface}"
    )
    assert contrast_ratio(pressed_ink, fill) >= floor, (
        f"{palette}/{screen}: held label {pressed_ink} on {fill} is "
        f"{contrast_ratio(pressed_ink, fill):.2f}, floor {floor}"
    )
    # The re-declaration is load-bearing rather than decorative: without it BOTH
    # the row and the label take the 0.7 fallback, React Native nests them, and the
    # ink lands at 0.49 over the fill.
    nested = over(over(ink, fill, 0.7), fill, 0.7)
    assert contrast_ratio(nested, fill) < floor, (
        f"{palette}/{screen}: the pressed re-declaration on {ink_spec} is dead code"
    )


def test_every_ledger_row_names_a_style_the_screen_actually_declares(documents):
    # A renamed style id must fail loudly here instead of quietly dropping the row.
    for screen, foreground, background, _ in PAIRS:
        for spec in (foreground, background):
            resolve(documents["light", screen], spec)
    for screen, *specs, _ in PRESSED:
        for spec in specs:
            resolve(documents["light", screen], spec)


def test_the_light_exemption_list_has_no_stale_entries():
    declared = {(screen, fg, bg) for screen, fg, bg, _ in PAIRS}

    assert LIGHT_EXEMPT <= declared, sorted(LIGHT_EXEMPT - declared)
