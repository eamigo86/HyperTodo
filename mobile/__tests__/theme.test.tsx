import React from "react";
import { act, render } from "@testing-library/react-native";
import { Text } from "react-native";

const mockGetItem = jest.fn<string | null, [string]>();
const mockSetItem = jest.fn();

jest.mock("expo-secure-store", () => ({
  getItem: (key: string) => mockGetItem(key),
  setItem: (key: string, value: string) => mockSetItem(key, value),
}));

// The shared instance, which is the one the hook test must use: `isolateModules`
// hands back a second copy of React as well, and a hook from a second React copy
// cannot render.
import * as sharedTheme from "../src/theme";

type ThemeModule = typeof import("../src/theme");

// The store seeds itself at import time, so every seeding test needs a fresh
// module registry rather than a fresh function call.
function loadTheme(): ThemeModule {
  let module!: ThemeModule;
  jest.isolateModules(() => {
    module = require("../src/theme");
  });
  return module;
}

describe("theme store", () => {
  beforeEach(() => {
    mockGetItem.mockReset();
    mockSetItem.mockReset();
    mockGetItem.mockReturnValue(null);
  });

  it("mirrors both server palettes token for token", () => {
    const { THEME_TOKENS } = loadTheme();
    expect(Object.keys(THEME_TOKENS.light)).toEqual(Object.keys(THEME_TOKENS.dark));
    expect(THEME_TOKENS.light.canvas).toBe("#F7F8FC");
    expect(THEME_TOKENS.dark.canvas).toBe("#0F1118");
  });

  it("starts light when the device has never been told otherwise", () => {
    expect(loadTheme().getThemeName()).toBe("light");
  });

  it("starts on the palette the last response left behind", () => {
    mockGetItem.mockReturnValue("dark");
    expect(loadTheme().getThemeName()).toBe("dark");
  });

  it("still starts, light, when the keystore read throws", () => {
    // A locked or unavailable keychain must not take the app down before the
    // first frame: this read is the only thing between import and render.
    mockGetItem.mockImplementation(() => {
      throw new Error("keychain unavailable");
    });
    expect(loadTheme().getThemeName()).toBe("light");
  });

  it("ignores a stored value that is not a palette we ship", () => {
    mockGetItem.mockReturnValue("chartreuse");
    expect(loadTheme().getThemeName()).toBe("light");
  });

  it("takes a palette from the server and remembers it for the next cold start", () => {
    const theme = loadTheme();
    theme.publishTheme("dark");
    expect(theme.getThemeName()).toBe("dark");
    expect(mockSetItem).toHaveBeenCalledWith("hypertodo.theme", "dark");
  });

  it("keeps the current palette when the header is missing or nonsense", () => {
    const theme = loadTheme();
    theme.publishTheme("dark");
    mockSetItem.mockClear();

    theme.publishTheme(null);
    theme.publishTheme(undefined);
    theme.publishTheme("");
    theme.publishTheme("chartreuse");

    expect(theme.getThemeName()).toBe("dark");
    expect(mockSetItem).not.toHaveBeenCalled();
  });

  it("survives a keystore write that throws", () => {
    mockSetItem.mockImplementation(() => {
      throw new Error("keychain full");
    });
    const theme = loadTheme();
    expect(() => theme.publishTheme("dark")).not.toThrow();
    expect(theme.getThemeName()).toBe("dark");
  });

  it("re-renders subscribers when the palette changes and never for routine traffic", () => {
    const theme = sharedTheme;
    theme.publishTheme("light");
    const renders = jest.fn();

    function Probe(): React.JSX.Element {
      const name = theme.useThemeName();
      renders();
      return <Text>{theme.THEME_TOKENS[name].canvas}</Text>;
    }

    const screen = render(<Probe />);
    expect(screen.getByText("#F7F8FC")).toBeTruthy();
    const initial = renders.mock.calls.length;

    act(() => theme.publishTheme("dark"));
    expect(screen.getByText("#0F1118")).toBeTruthy();

    // Every fragment response carries the header. Re-publishing the palette the
    // app is already showing must not wake a single component.
    const settled = renders.mock.calls.length;
    act(() => theme.publishTheme("dark"));
    expect(renders.mock.calls.length).toBe(settled);
    expect(settled).toBeGreaterThan(initial);

    screen.unmount();
    expect(() => act(() => theme.publishTheme("light"))).not.toThrow();
  });
});
