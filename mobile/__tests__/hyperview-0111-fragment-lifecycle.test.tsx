import "react-native-gesture-handler/jestSetup";
import React from "react";
import { act, fireEvent, render, waitFor } from "@testing-library/react-native";
import { NavigationContainer } from "@react-navigation/native";
import Hyperview from "hyperview";

jest.mock("react-native-webview", () => ({ WebView: () => null }));

const HV = "https://hyperview.org/hyperview";
const BASE = "https://example.test/hv/";
const FRAGMENT = "https://example.test/hv/fragment/";
const ROOT = `<doc xmlns="${HV}"><navigator id="root" type="stack"><nav-route id="home" href="${BASE}screen/"/></navigator></doc>`;
const SCREEN = `<doc xmlns="${HV}"><screen><body>
  <view id="container"><text id="original">Original fragment</text></view>
  <text id="status">Ready</text><spinner id="loading" hide="true"/>
  <view href="${FRAGMENT}" action="replace" target="container"
    show-during-load="loading" hide-during-load="status"><text>Retry fragment</text></view>
  <list id="tasks" trigger="refresh"><behavior trigger="refresh" href="${FRAGMENT}"
    action="replace" target="tasks"/><item key="one"><text id="task">Example task</text></item></list>
</body></screen></doc>`;
const REPLACEMENT = `<view xmlns="${HV}" id="container"><text>Recovered fragment</text></view>`;
const LIST_REPLACEMENT = `<list xmlns="${HV}" id="tasks" trigger="refresh"><behavior trigger="refresh" href="${FRAGMENT}" action="replace" target="tasks"/><item key="two"><text>Recovered task</text></item></list>`;
const reply = (body: string, status = 200) =>
  new Response(body, { status, headers: { "Content-Type": status === 500 ? "text/plain" : "application/vnd.hyperview+xml" } });

function fixture(failure: "server" | "network", replacement: "view" | "list") {
  let failuresLeft = 2;
  const onError = jest.fn();
  const fetch = jest.fn(async (input: RequestInfo | URL) => {
    const url = String(input);
    if (url === BASE) return reply(ROOT);
    if (url === `${BASE}screen/`) return reply(SCREEN);
    if (url === FRAGMENT && failuresLeft-- > 0) {
      if (failure === "network") throw new TypeError("Network request failed");
      return reply("Internal Server Error", 500);
    }
    return reply(replacement === "list" ? LIST_REPLACEMENT : REPLACEMENT);
  });
  const ui = render(<NavigationContainer><Hyperview
    entrypointUrl={BASE} fetch={fetch} formatDate={() => undefined} onError={onError}
  /></NavigationContainer>);
  return { ui, fetch, onError };
}

describe.each(["server", "network"] as const)("actual Hyperview %s fragment lifecycle", failure => {
  it("clears indicators after failure, retains the old fragment, and permits retry", async () => {
    const { ui, fetch, onError } = fixture(failure, "view");
    try {
      await ui.findByText("Retry fragment");
      fireEvent.press(ui.getByText("Retry fragment"));
      await waitFor(() => expect(onError).toHaveBeenCalledTimes(1));
      await waitFor(() => {
        expect(ui.queryByTestId("loading")).toBeNull();
        expect(ui.getByText("Ready")).toBeTruthy();
        expect(ui.getByText("Original fragment")).toBeTruthy();
      });
      fireEvent.press(ui.getByText("Retry fragment"));
      await waitFor(() => expect(onError).toHaveBeenCalledTimes(2));
      await waitFor(() => expect(ui.queryByTestId("loading")).toBeNull());
      fireEvent.press(ui.getByText("Retry fragment"));
      await ui.findByText("Recovered fragment");
      expect(fetch.mock.calls.filter(([url]) => url === FRAGMENT)).toHaveLength(3);
    } finally { ui.unmount(); }
  });

  it("ends a failed pull-to-refresh and allows a later successful refresh", async () => {
    const { ui, onError } = fixture(failure, "list");
    try {
      await ui.findByText("Example task");
      const control = () => ui.getByTestId("tasks").props.refreshControl;
      await act(async () => control().props.onRefresh());
      await waitFor(() => expect(onError).toHaveBeenCalledTimes(1));
      await waitFor(() => expect(control().props.refreshing).toBe(false));
      expect(ui.getByText("Example task")).toBeTruthy();
      await act(async () => control().props.onRefresh());
      await waitFor(() => expect(onError).toHaveBeenCalledTimes(2));
      await waitFor(() => expect(control().props.refreshing).toBe(false));
      await act(async () => control().props.onRefresh());
      await ui.findByText("Recovered task");
      expect(control().props.refreshing).toBe(false);
    } finally { ui.unmount(); }
  });
});

it("keeps an intentional sync-drop distinct from a failed request", async () => {
  let release!: (response: Response) => void;
  const pending = new Promise<Response>(resolve => { release = resolve; });
  const dropScreen = `<doc xmlns="${HV}"><screen><body>
    <view id="container"><text>Original fragment</text></view>
    <spinner id="loading" hide="true"/>
    <view href="${FRAGMENT}" action="replace" target="container" sync-id="shared"
      sync-method="drop" show-during-load="loading"><text>First request</text></view>
    <view href="${FRAGMENT}" action="replace" target="container" sync-id="shared"
      sync-method="drop" show-during-load="loading"><text>Dropped request</text></view>
  </body></screen></doc>`;
  const onError = jest.fn();
  const fetch = jest.fn(async (input: RequestInfo | URL) => {
    const url = String(input);
    if (url === BASE) return reply(ROOT);
    if (url === `${BASE}screen/`) return reply(dropScreen);
    return pending;
  });
  const ui = render(<NavigationContainer><Hyperview
    entrypointUrl={BASE} fetch={fetch} formatDate={() => undefined} onError={onError}
  /></NavigationContainer>);
  try {
    await ui.findByText("First request");
    fireEvent.press(ui.getByText("First request"));
    await waitFor(() => expect(fetch).toHaveBeenCalledTimes(3));
    expect(ui.getByTestId("loading")).toBeTruthy();
    fireEvent.press(ui.getByText("Dropped request"));
    await act(async () => {});
    expect(fetch).toHaveBeenCalledTimes(3);
    expect(ui.getByTestId("loading")).toBeTruthy();
    expect(ui.getByText("Original fragment")).toBeTruthy();
    await act(async () => release(reply(REPLACEMENT)));
    await ui.findByText("Recovered fragment");
    expect(ui.queryByTestId("loading")).toBeNull();
    expect(onError).not.toHaveBeenCalled();
  } finally { ui.unmount(); }
});
