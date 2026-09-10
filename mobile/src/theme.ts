import * as SecureStore from "expo-secure-store";
import { createContext, createElement, useContext, useSyncExternalStore, type ReactNode } from "react";

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

/** Internal synchronous palette persistence, injectable for the native fixture. */
export type ThemePersistence = {
  read(): unknown;
  write(name: ThemeName): void;
};
function isThemeName(value: unknown): value is ThemeName {
  return value === "light" || value === "dark";
}

/** Capture a store without I/O; seed synchronously only when explicitly read. */
export function createThemeStore(persistence: ThemePersistence) {
  let current: ThemeName | undefined;
  const listeners = new Set<() => void>();
  const getSnapshot = (): ThemeName => {
    if (current === undefined) {
      try {
        const stored = persistence.read();
        current = isThemeName(stored) ? stored : "light";
      } catch {
        current = "light";
      }
    }
    return current;
  };
  return Object.freeze({
    getSnapshot,
    publish: (name: string | null | undefined) => {
      if (!isThemeName(name) || name === getSnapshot()) return;
      current = name;
      try {
        persistence.write(name);
      } catch {/* Painting does not depend on persistence. */}
      for (const listener of listeners) listener();
    },
    subscribe: (listener: () => void) => {
      listeners.add(listener);
      return () => {
        listeners.delete(listener);
      };
    }
  });
}
export type ThemeStore = ReturnType<typeof createThemeStore>;
const STORAGE_KEY = "hypertodo.theme";
/** The normal App retains its existing key and synchronous first paint. */
export const defaultThemeStore = createThemeStore({
  read: () => SecureStore.getItem(STORAGE_KEY),
  write: name => SecureStore.setItem(STORAGE_KEY, name)
});
const ThemeContext = createContext<ThemeStore | null>(null);
export function ThemeProvider({
  store,
  children
}: {
  store: ThemeStore;
  children: ReactNode;
}) {
  return createElement(ThemeContext.Provider, {
    value: store
  }, children);
}
export function getThemeName(): ThemeName {
  return defaultThemeStore.getSnapshot();
}
export function publishTheme(name: string | null | undefined): void {
  defaultThemeStore.publish(name);
}
/** Existing shell components automatically use their containing App's store. */
export function useThemeName(): ThemeName {
  const store = useContext(ThemeContext) ?? defaultThemeStore;
  return useSyncExternalStore(store.subscribe, store.getSnapshot, store.getSnapshot);
}
