import React from "react";
import { Parser } from "hyperview";
import { RefreshControl, StyleSheet } from "react-native";
import { act, fireEvent, render } from "@testing-library/react-native";

import ElementErrorBanner from "../src/components/ElementErrorBanner";
import OfflineRefreshControl from "../src/components/OfflineRefreshControl";
import {
  FAILURE_COPY,
  classifyFailure,
  publishNetworkFailure,
  subscribeToNetworkFailures,
} from "../src/feedback/failure";
import { hyperviewLogger, reportHyperviewError } from "../src/feedback/logging";
import { publishTheme } from "../src/theme";

// Importing the hyperview barrel drags in react-native-webview, whose TurboModule is not
// available under jest. Only that native leaf is stubbed -- the Parser under test is real.
jest.mock("react-native-webview", () => ({ WebView: () => null }));
jest.mock("expo-secure-store", () => ({ getItem: () => null, setItem: () => undefined }));

// Expo SDK 57 swaps the global fetch (expo/src/winter/runtime.native.ts:52), so on a real
// device a reachability failure is an expo FetchError: name stays "Error", message is
// prefixed with "fetch failed: ". Under jest the global fetch is still whatwg-fetch, which
// throws TypeError("Network request failed"). Both shapes must classify as offline or the
// suite stays green while the device stays broken.
function expoFetchError(message: string): Error {
  const error = new Error(`fetch failed: ${message}`);
  error.stack = "at ExpoModulesCore/Promise.swift:56";
  return error;
}

describe("classifyFailure", () => {
  it("treats the expo FetchError shape as offline", () => {
    const error = expoFetchError(
      "UnexpectedException: Could not connect to the server. (at ExpoModulesCore/Promise.swift:56)",
    );
    expect(error.name).toBe("Error");
    expect(classifyFailure(error)).toBe("offline");
  });

  it("treats both whatwg-fetch network TypeErrors as offline", () => {
    expect(classifyFailure(new TypeError("Network request failed"))).toBe("offline");
    expect(classifyFailure(new TypeError("Network request timed out"))).toBe("offline");
  });

  it("treats server, parser and unknown failures as server", () => {
    const serverError = new Error("ServerError (status 500)");
    serverError.name = "ServerError";
    const parserError = new Error("Unexpected end of input");
    parserError.name = "XMLParserFatalError";

    expect(classifyFailure(serverError)).toBe("server");
    expect(classifyFailure(parserError)).toBe("server");
    expect(classifyFailure(new Error("boom"))).toBe("server");
    expect(classifyFailure(null)).toBe("server");
    expect(classifyFailure(undefined)).toBe("server");
  });
});

describe("FAILURE_COPY", () => {
  it("never leaks technical vocabulary to the user", () => {
    const banned = /error|exception|fetch|network request|status|http|server\b|null|undefined|\.swift|:\d/i;
    Object.values(FAILURE_COPY).forEach((copy) => {
      expect(copy.title).not.toMatch(banned);
      expect(copy.body).not.toMatch(banned);
      expect(copy.action).not.toMatch(banned);
    });
  });
});

describe("network failure pub/sub", () => {
  it("notifies subscribers until they unsubscribe", () => {
    const listener = jest.fn();
    const unsubscribe = subscribeToNetworkFailures(listener);

    publishNetworkFailure();
    expect(listener).toHaveBeenCalledTimes(1);

    unsubscribe();
    publishNetworkFailure();
    expect(listener).toHaveBeenCalledTimes(1);
  });
});

describe("ElementErrorBanner", () => {
  const RAW_MESSAGE =
    "fetch failed: UnexpectedException: Could not connect to the server. (at ExpoModulesCore/Promise.swift:56)";

  it("shows the offline copy and never the raw error text", () => {
    const screen = render(
      <ElementErrorBanner
        error={expoFetchError(
          "UnexpectedException: Could not connect to the server. (at ExpoModulesCore/Promise.swift:56)",
        )}
        onPressClose={jest.fn()}
        onPressReload={jest.fn()}
      />,
    );

    expect(screen.getByText(FAILURE_COPY.offline.title)).toBeTruthy();
    expect(screen.getByText(FAILURE_COPY.offline.body)).toBeTruthy();
    expect(screen.queryByText(RAW_MESSAGE)).toBeNull();
    expect(JSON.stringify(screen.toJSON())).not.toContain("ExpoModulesCore");
    expect(JSON.stringify(screen.toJSON())).not.toContain("fetch failed");
  });

  it("shows the server copy and never the raw error text", () => {
    const error = new Error("ServerError (status 500)");
    error.name = "ServerError";
    const screen = render(
      <ElementErrorBanner error={error} onPressClose={jest.fn()} onPressReload={jest.fn()} />,
    );

    expect(screen.getByText(FAILURE_COPY.server.title)).toBeTruthy();
    expect(screen.queryByText(error.message)).toBeNull();
    expect(JSON.stringify(screen.toJSON())).not.toContain("ServerError");
    expect(JSON.stringify(screen.toJSON())).not.toContain("500");
  });

  it("floats above the screen content instead of pushing it down", () => {
    const screen = render(
      <ElementErrorBanner
        error={new Error("boom")}
        onPressClose={jest.fn()}
        onPressReload={jest.fn()}
      />,
    );

    expect(screen.getByTestId("element-error-banner").props.style).toEqual(
      expect.objectContaining({ position: "absolute", top: 0, left: 0, right: 0 }),
    );
  });

  it("wires reload and close to their own controls", () => {
    const onPressReload = jest.fn();
    const onPressClose = jest.fn();
    const screen = render(
      <ElementErrorBanner
        error={new TypeError("Network request failed")}
        onPressClose={onPressClose}
        onPressReload={onPressReload}
      />,
    );

    fireEvent.press(screen.getByRole("button", { name: "Try again" }));
    expect(onPressReload).toHaveBeenCalledTimes(1);
    expect(onPressClose).not.toHaveBeenCalled();

    fireEvent.press(screen.getByRole("button", { name: "Dismiss" }));
    expect(onPressClose).toHaveBeenCalledTimes(1);
    expect(onPressReload).toHaveBeenCalledTimes(1);
  });
});

describe("OfflineRefreshControl", () => {
  it("unsticks the spinner on failure and re-arms on the next pull", () => {
    const onRefresh = jest.fn();
    const screen = render(<OfflineRefreshControl onRefresh={onRefresh} refreshing />);
    const control = () => screen.UNSAFE_getByType(RefreshControl);

    expect(control().props.refreshing).toBe(true);

    act(() => publishNetworkFailure());
    expect(control().props.refreshing).toBe(false);

    act(() => control().props.onRefresh());
    expect(onRefresh).toHaveBeenCalledTimes(1);
    expect(control().props.refreshing).toBe(true);
  });

  it("stops listening once unmounted", () => {
    const screen = render(<OfflineRefreshControl onRefresh={jest.fn()} refreshing />);
    screen.unmount();
    expect(() => act(() => publishNetworkFailure())).not.toThrow();
  });

  it("follows the palette, because hv-list passes the spinner no colours at all", () => {
    // hv-list renders `<RefreshControl onRefresh refreshing />` and nothing else
    // (hv-list/index.tsx:263), so this wrapper is the only lever over the spinner.
    // Unthemed, Android drew its default white puck on the #0F1118 canvas.
    const screen = render(<OfflineRefreshControl onRefresh={jest.fn()} refreshing />);
    const control = () => screen.UNSAFE_getByType(RefreshControl);

    expect(control().props.tintColor).toBe("#5C6178");
    expect(control().props.colors).toEqual(["#278CFF"]);
    expect(control().props.progressBackgroundColor).toBe("#FFFFFF");

    act(() => publishTheme("dark"));

    expect(control().props.tintColor).toBe("#9DA3B6");
    expect(control().props.colors).toEqual(["#7FB6FF"]);
    expect(control().props.progressBackgroundColor).toBe("#1A1D26");

    act(() => publishTheme("light"));
  });
});

describe("hyperview parser failure propagation", () => {
  const URL = "https://hypertodo.test/tasks";

  function parserRejectingWith(error: Error) {
    return new Parser(() => Promise.reject(error), undefined, undefined);
  }

  async function rejection(promise: Promise<unknown>): Promise<Error> {
    try {
      await promise;
    } catch (error) {
      return error as Error;
    }
    throw new Error("expected the parser call to reject");
  }

  it("propagates an offline rejection unchanged from loadDocument", async () => {
    const offline = expoFetchError("Could not connect to the server.");
    const parser = parserRejectingWith(offline);

    await expect(parser.loadDocument(URL)).rejects.toBe(offline);
    expect(classifyFailure(await rejection(parser.loadDocument(URL)))).toBe("offline");
  });

  it("propagates an offline rejection unchanged from loadElement", async () => {
    const offline = new TypeError("Network request failed");
    const parser = parserRejectingWith(offline);

    await expect(
      parser.loadElement(URL, null, "get", undefined, undefined),
    ).rejects.toBe(offline);
    expect(
      classifyFailure(await rejection(parser.loadElement(URL, null, "get", undefined, undefined))),
    ).toBe("offline");
  });

  it("does not swallow or reshape a non-network failure", async () => {
    const boom = new Error("boom");
    const parser = parserRejectingWith(boom);

    await expect(parser.loadDocument(URL)).rejects.toBe(boom);
    await expect(
      parser.loadElement(URL, null, "get", undefined, undefined),
    ).rejects.toBe(boom);
    expect(classifyFailure(boom)).toBe("server");
  });
});

describe("hyperview logging", () => {
  const spies: jest.SpyInstance[] = [];

  afterEach(() => {
    spies.forEach((spy) => spy.mockRestore());
    spies.length = 0;
  });

  function watchConsole() {
    const error = jest.spyOn(console, "error").mockImplementation(() => {});
    const warn = jest.spyOn(console, "warn").mockImplementation(() => {});
    const log = jest.spyOn(console, "log").mockImplementation(() => {});
    spies.push(error, warn, log);
    return { error, warn, log };
  }

  it("never routes through console.error or console.warn, which raise LogBox overlays", () => {
    const watched = watchConsole();
    hyperviewLogger.error("boom", new Error("x"));
    hyperviewLogger.warn("careful");
    expect(watched.error).not.toHaveBeenCalled();
    expect(watched.warn).not.toHaveBeenCalled();
    expect(watched.log).toHaveBeenCalledTimes(2);
  });

  it("keeps the routine navigation chatter silent", () => {
    const watched = watchConsole();
    hyperviewLogger.info("navigating");
    hyperviewLogger.log("navigating");
    expect(watched.log).not.toHaveBeenCalled();
  });

  it("unsticks the refresh spinner without raising a LogBox overlay", () => {
    const watched = watchConsole();
    const listener = jest.fn();
    const unsubscribe = subscribeToNetworkFailures(listener);
    reportHyperviewError(new Error("fetch failed: Could not connect to the server"));
    unsubscribe();
    expect(listener).toHaveBeenCalledTimes(1);
    expect(watched.error).not.toHaveBeenCalled();
    expect(watched.warn).not.toHaveBeenCalled();
  });
});

describe("the fragment error banner follows the palette the server named", () => {
  afterEach(() => act(() => publishTheme("light")));

  const flat = (node: { props: Record<string, unknown> }) =>
    StyleSheet.flatten(node.props.style as never) as Record<string, string>;

  it("repaints its card, its copy and its two controls", () => {
    const screen = render(
      <ElementErrorBanner
        error={new Error("boom")}
        onPressClose={jest.fn()}
        onPressReload={jest.fn()}
      />,
    );

    expect(flat(screen.getByTestId("element-error-card")).backgroundColor).toBe("#FFFFFF");
    expect(flat(screen.getByTestId("element-error-card")).shadowColor).toBe("#161A35");
    // shadow* is iOS-only. The card is 1.06:1 on the light canvas and 1.12:1 on
    // the dark one, so without an elevation Android draws no edge whatsoever.
    expect(flat(screen.getByTestId("element-error-card")).elevation).toBe(8);
    expect(flat(screen.getByText(FAILURE_COPY.server.title)).color).toBe("#161A35");
    expect(flat(screen.getByText(FAILURE_COPY.server.body)).color).toBe("#6D728A");
    expect(flat(screen.getByRole("button", { name: "Try again" })).backgroundColor).toBe("#278CFF");
    expect(flat(screen.getByText("Dismiss")).color).toBe("#161A35");

    act(() => publishTheme("dark"));

    expect(flat(screen.getByTestId("element-error-card")).backgroundColor).toBe("#1A1D26");
    // Dark's scrim is pure black, so the card still reads as lifted off a canvas
    // that is itself nearly black -- #161A35 would have been invisible there.
    expect(flat(screen.getByTestId("element-error-card")).shadowColor).toBe("#000000");
    expect(flat(screen.getByText(FAILURE_COPY.server.title)).color).toBe("#F3F5FB");
    expect(flat(screen.getByText(FAILURE_COPY.server.body)).color).toBe("#A9AFC2");
    expect(flat(screen.getByRole("button", { name: "Try again" })).backgroundColor).toBe("#1F6FD1");
    expect(flat(screen.getByText("Try again")).color).toBe("#FFFFFF");
    expect(flat(screen.getByText("Dismiss")).color).toBe("#F3F5FB");
  });
});

// The server sends X-HyperTodo-Theme to EVERY client, including binaries built
// before src/theme.ts existed. Those binaries never look at it -- their fetch
// wrapper returns the Response untouched -- so the only way the header could hurt
// them is if hyperview itself objected. It does not, and this is the real Parser
// saying so rather than a reading of parser.ts:176-181.
describe("an old binary is inert when the theme header arrives", () => {
  const DOC =
    '<doc xmlns="https://hyperview.org/hyperview"><screen><body><text>Hi</text></body></screen></doc>';

  async function parseWith(headers: Record<string, string>) {
    const parser = new Parser(
      () =>
        Promise.resolve(
          new Response(DOC, {
            headers: { "Content-Type": "application/vnd.hyperview+xml", ...headers },
          }),
        ),
      undefined,
      undefined,
    );
    return parser.loadDocument("https://hypertodo.test/dashboard");
  }

  it("parses the same document with and without the header", async () => {
    const plain = await parseWith({});
    const themed = await parseWith({ "X-HyperTodo-Theme": "dark" });

    expect(themed.doc.toString()).toBe(plain.doc.toString());
    expect(themed.doc.getElementsByTagName("text")[0].textContent).toBe("Hi");
    // parser.ts:179 reads X-Response-Stale-Reason and nothing else beyond
    // Content-Type. An unrecognised header does not even reach a code path.
    expect(themed.staleHeaderType).toBe(plain.staleHeaderType);
  });
});
