"""Server-side colour tokens for the light and dark stylesheets.

Hyperview resolves styles from the SCREEN document only (client
services/stylesheets/index.ts:198-286 reads the first <styles> tag and
keys every rule by its own id), so a theme change is a whole-screen reload by
construction and no client change is needed to ship one.

LIGHT IS FROZEN. Every value below is byte-identical to the literal it replaced
in the templates; tests/test_theme_tokens.py compares the rendered light
stylesheets against a golden captured before the extraction, so any edit here
that moves a light value fails loudly. Fourteen light pairs are below their WCAG
floor today and are recorded as exemptions in tests/test_theme_contrast.py
rather than silently fixed, because "light stays byte-identical" was the brief.

Tokens are named for the ROLE, never for the colour. Where one hex serves two
roles in light it splits into two tokens, because the roles diverge in dark --
that split is the whole reason this file exists.
"""

LIGHT: dict[str, str] = {
    # Surfaces
    "canvas": "#F7F8FC",
    "surface": "#FFFFFF",
    "hairline": "#E9ECF5",
    "border_strong": "#C4CBDC",
    "field": "#F1F4FC",
    "field_pressed": "#E7EEFF",
    "field_border": "#E1E7F5",
    "scrim": "#161A35",
    # Brand
    "brand": "#278CFF",
    "brand_pressed": "#1F7AE0",
    "brand_deep": "#1F6FD1",
    "brand_ink": "#278CFF",
    "brand_ink_pressed": "#1D69BF",
    "brand_on_disc": "#278CFF",
    "on_brand": "#FFFFFF",
    "on_brand_muted": "#D9EAFF",
    "on_brand_disc": "#FFFFFF",
    "on_brand_disc_ink": "#161A35",
    "progress_track": "#5FA8FF",
    "progress_fill": "#FFFFFF",
    # Ink
    "ink": "#161A35",
    "ink_body": "#20243D",
    "ink_muted": "#6A6F86",
    "ink_muted_alt": "#6D728A",
    "ink_faint": "#7B8097",
    "ink_label": "#4C526B",
    "ink_label_strong": "#343951",
    "ink_nav": "#68708B",
    "ink_nav_active": "#1F6FD1",
    "link_ink": "#1F6FD1",
    "chevron": "#8A8FA3",
    "spinner": "#5C6178",
    # Status
    "danger": "#B42318",
    "danger_border": "#D92D20",
    "danger_surface": "#FFF0EE",
    "danger_surface_border": "#FFD5D0",
    "danger_field": "#FFF7F6",
    "danger_outline": "#F3C9C4",
    "danger_press_fill": "#F3D8D2",
    "success": "#1D9E75",
    "alert_surface": "#FCE7F6",
    "alert_ink": "#9F1239",
    # State
    "select_fill": "#EEF3FF",
    "select_ink": "#1F6FD1",
    "select_press": "#D4DFF8",
    "row_press": "#D0DAF2",
    "chip": "#EEF2FC",
    "chip_active": "#DDE7FF",
    "chip_ink_active": "#1A5FB4",
    "tint_press_fill": "#EAF3FF",
    "switch_off": "#818AA4",
    "switch_knob": "#FFFFFF",
    "bar": "#AEBBFA",
    # Identity. A user picked "Mint"; Mint is not a theme decision, so the five
    # fills and the one ink that clears 4.5:1 on all of them (4.95 on green, the
    # binding constraint) are IDENTICAL in both palettes.
    "cat_lavender": "#AEBBFA",
    "cat_yellow": "#FFF27B",
    "cat_mint": "#C9F0E7",
    "cat_pink": "#F6B5E8",
    "cat_green": "#3B9B70",
    "on_category": "#161A35",
    "cat_lavender_ink": "#5B6ACD",
    "cat_yellow_ink": "#9A7B0A",
    "cat_mint_ink": "#1D9E75",
    "cat_pink_ink": "#B4479E",
    "cat_green_ink": "#1D7A4E",
}

DARK: dict[str, str] = {
    # Surfaces
    "canvas": "#0F1118",
    "surface": "#1A1D26",
    "hairline": "#2A2E3A",
    "border_strong": "#7E8598",
    "field": "#232733",
    "field_pressed": "#2E3444",
    "field_border": "#6E7689",
    "scrim": "#000000",
    # Brand. The band stays a band, one step deeper so plain white clears 4.5:1
    # on it at any size -- the arithmetic screens/dashboard.xml already documents
    # for the side-menu header.
    "brand": "#1F6FD1",
    "brand_pressed": "#1A5CAF",
    "brand_deep": "#17539E",
    "brand_ink": "#7FB6FF",
    "brand_ink_pressed": "#A8CEFF",
    # The avatar disc stays white in both palettes, so its ink stays dark in both.
    "brand_on_disc": "#278CFF",
    "on_brand": "#FFFFFF",
    "on_brand_muted": "#F2F8FF",
    "on_brand_disc": "#FFFFFF",
    "on_brand_disc_ink": "#161A35",
    "progress_track": "#12447F",
    "progress_fill": "#FFFFFF",
    # Ink
    "ink": "#F3F5FB",
    "ink_body": "#E3E7F2",
    "ink_muted": "#A9AFC2",
    "ink_muted_alt": "#A9AFC2",
    "ink_faint": "#9DA3B6",
    "ink_label": "#B7BDCE",
    "ink_label_strong": "#D3D8E6",
    "ink_nav": "#A0A7BA",
    "ink_nav_active": "#7FB6FF",
    "link_ink": "#7FB6FF",
    "chevron": "#9098AD",
    "spinner": "#9DA3B6",
    # Status
    "danger": "#FF9E93",
    "danger_border": "#FF6B5C",
    "danger_surface": "#3A1A17",
    "danger_surface_border": "#5E2A24",
    "danger_field": "#2E1614",
    "danger_outline": "#B0665C",
    "danger_press_fill": "#4E241F",
    "success": "#5FD3A6",
    "alert_surface": "#3A1B2B",
    "alert_ink": "#FFA8BE",
    # State
    "select_fill": "#283248",
    "select_ink": "#9CC4FF",
    "select_press": "#33405C",
    "row_press": "#3A4258",
    "chip": "#232733",
    "chip_active": "#2C3852",
    "chip_ink_active": "#9CC4FF",
    "tint_press_fill": "#16233A",
    # Was #5A6178, which is 2.74:1 on `surface` and therefore an invisible control
    # boundary in dark. It only ever looked fine because the one control that used
    # it, the login opt-in, sits on the canvas and the ledger measured its KNOB
    # against its own track and never the track against the surface behind it.
    # #6E7689 is 3.70:1 on surface, 4.14:1 on the dark login sheet, and still
    # carries a white knob at 4.55:1. LIGHT switch_off does not move.
    "switch_off": "#6E7689",
    "switch_knob": "#FFFFFF",
    "bar": "#8090DE",
    # Identity: unchanged, on purpose. See LIGHT.
    "cat_lavender": "#AEBBFA",
    "cat_yellow": "#FFF27B",
    "cat_mint": "#C9F0E7",
    "cat_pink": "#F6B5E8",
    "cat_green": "#3B9B70",
    "on_category": "#161A35",
    "cat_lavender_ink": "#AEBBFA",
    "cat_yellow_ink": "#E7CE5C",
    "cat_mint_ink": "#5FD3A6",
    "cat_pink_ink": "#F0A6DE",
    "cat_green_ink": "#57C894",
}

THEMES: dict[str, dict[str, str]] = {"light": LIGHT, "dark": DARK}
DEFAULT_THEME = "light"


def palette(name: str | None) -> dict[str, str]:
    """Return the token table for one theme name.

    Args:
        name: Stored preference, which may be blank, unknown, or None for an
            account that predates the preference table.

    Returns:
        The matching palette, falling back to light.
    """
    return THEMES.get(name or "", LIGHT)
