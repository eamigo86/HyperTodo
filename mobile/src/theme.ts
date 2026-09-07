import * as SecureStore from "expo-secure-store";
import { useSyncExternalStore } from "react";

/**
 * The colours the native shell paints, mirrored from the server's token layer.
 *
 * Hyperview resolves styles from the SCREEN document, so every server-driven
 * surface already follows the stored preference. These tokens are the ones no HXML
 * document can reach: both safe-area insets, the splash overlay, the two
 * full-screen failure states, the fragment error banner, the drawer chrome and the
 * pull-to-refresh spinner, which hv-list renders with no colour props at all
 * (hv-list/index.tsx:263) so its platform default is whatever the app does not set.
 *
 * EVERY VALUE HERE IS OWNED BY ``backend/todo/theme.py``. Nothing in this table may
 * be invented, tuned or rounded locally: ``backend/tests/test_theme_client_tokens.py``
 * reads this file and fails the backend suite the moment a value stops matching
 * ``theme.LIGHT[key]`` / ``theme.DARK[key]``. Add a token by adding it there first.
 */
export const THEME_TOKENS = {
  light: {
    canvas: "#F7F8FC",
    surface: "#FFFFFF",
    scrim: "#161A35",
    chip: "#EEF2FC",
    brand: "#278CFF",
    brand_ink: "#278CFF",
    on_brand: "#FFFFFF",
    ink: "#161A35",
    ink_muted_alt: "#6D728A",
    ink_label: "#4C526B",
    spinner: "#5C6178",
    // Identity, not theme: a category fill and its ink are byte-identical in both
    // palettes upstream, and the loading mark borrows them. Listed rather than
    // inlined so the drift guard covers them too.
    cat_lavender: "#AEBBFA",
    on_category: "#161A35",
  },
  dark: {
    canvas: "#0F1118",
    surface: "#1A1D26",
    scrim: "#000000",
    chip: "#232733",
    brand: "#1F6FD1",
    brand_ink: "#7FB6FF",
    on_brand: "#FFFFFF",
    ink: "#F3F5FB",
    ink_muted_alt: "#A9AFC2",
    ink_label: "#B7BDCE",
    spinner: "#9DA3B6",
    cat_lavender: "#AEBBFA",
    on_category: "#161A35",
  },
} as const;

export type ThemeName = keyof typeof THEME_TOKENS;
export type ThemeTokens = (typeof THEME_TOKENS)[ThemeName];

// ponytail: SecureStore is the wrong store for a non-secret, but it is already a
// dependency (src/biometrics/store.ts) and it is the only installed one with a
// SYNCHRONOUS read, which is what lets the very first frame -- splash included --
// be the right colour with no await. Swap in @react-native-async-storage/async-storage
// the day a plaintext keychain entry actually bothers someone.
const STORAGE_KEY = "hypertodo.theme";

function isThemeName(value: unknown): value is ThemeName {
  return value === "light" || value === "dark";
}

function seed(): ThemeName {
  try {
    const stored = SecureStore.getItem(STORAGE_KEY);
    return isThemeName(stored) ? stored : "light";
  } catch {
    // A locked or unavailable keychain is not worth a crash before first paint.
    return "light";
  }
}

let current: ThemeName = seed();
const listeners = new Set<() => void>();

export function getThemeName(): ThemeName {
  return current;
}

/** Adopt the palette a response named, if it named one we ship.
 *
 * Every document AND every fragment carries the header, so the unchanged case is
 * the overwhelmingly common one and has to be free: without that guard, routine
 * fragment traffic would wake every subscriber several times a screen.
 */
export function publishTheme(name: string | null | undefined): void {
  if (!isThemeName(name) || name === current) {
    return;
  }
  current = name;
  try {
    SecureStore.setItem(STORAGE_KEY, name);
  } catch {
    // Persistence is an optimisation for the next cold start, never a
    // precondition for painting this frame correctly.
  }
  listeners.forEach((listener) => listener());
}

function subscribe(listener: () => void): () => void {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}

/** Subscribe a shell component to the server's palette. */
export function useThemeName(): ThemeName {
  return useSyncExternalStore(subscribe, getThemeName, getThemeName);
}
