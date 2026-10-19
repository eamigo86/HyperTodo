import { DOMParser } from "@instawork/xmldom";

import { findTarget, fragmentReplacement } from "../src/realtime/fragment";
import {
  UnsupportedDocument,
  navigationTarget,
  prepareReload,
  previousRoute,
  reloadUrl,
  screenCallbacks,
} from "../src/realtime/navigation";

jest.mock("react-native-webview", () => ({ WebView: () => null }));

const BASE = "https://hypertodo.test/hv/tasks/?status=active";
const HV = "https://hyperview.org/hyperview";
const APP = "https://hypertodo.app/components";
const parse = (xml: string) => new DOMParser().parseFromString(xml, "application/xml");

function reloadDocument(requestId = "attempt-1") {
  return parse(`<doc xmlns="${HV}" xmlns:app="${APP}"><screen><body><app:realtime><list><item><app:realtime-page request-id="${requestId}"/></item></list></app:realtime></body></screen></doc>`);
}

describe("owned fragment boundaries", () => {
  const tree = () => {
    const doc = parse('<doc><view id="root"><view id="target"><text>old</text></view><view id="trigger"><text>button</text></view></view></doc>');
    const root = doc.getElementsByTagName("view")[0];
    const target = doc.getElementsByTagName("view")[1];
    const trigger = doc.getElementsByTagName("view")[2];
    const origin = doc.getElementsByTagName("text")[1];
    return { doc, root, target, trigger, origin };
  };

  it("prefers an explicit live target over the behavior element's parent", () => {
    const { root, target, trigger, origin } = tree();
    expect(findTarget(root, origin, { targetId: "target", behaviorElement: trigger } as never)).toBe(target);
  });

  it("falls back to the behavior's live parent when the target id has disappeared", () => {
    const { root, trigger, origin } = tree();
    expect(findTarget(root, origin, { targetId: "deleted", behaviorElement: trigger } as never)).toBe(root);
  });

  it("falls back to the live origin without a target or behavior", () => {
    const { root, origin } = tree();
    expect(findTarget(root, origin, {} as never)).toBe(origin);
  });

  it("rejects an origin detached from the live document", () => {
    const { root, origin } = tree();
    origin.parentNode?.removeChild(origin);
    expect(findTarget(root, origin, {} as never)).toBeNull();
  });

  it("does not use a detached behavior as a live target", () => {
    const { root, trigger, origin } = tree();
    trigger.parentNode?.removeChild(trigger);
    expect(findTarget(root, origin, { behaviorElement: trigger } as never)).toBeNull();
  });

  it("replaces with exactly the server fragment", () => {
    const { target, doc } = tree();
    const source = doc.createElement("list");
    expect(fragmentReplacement(target, source, "replace")).toBe(source);
    expect(target.getElementsByTagName("text")).toHaveLength(1);
  });

  it("appends while preserving the previous child node's identity and order", () => {
    const { target, doc } = tree();
    const existing = target.firstChild;
    const source = doc.createElement("item");
    const replacement = fragmentReplacement(target, source, "append");
    expect(replacement).not.toBe(target);
    expect(replacement.getAttribute("id")).toBe("target");
    expect(replacement.childNodes[0]).toBe(existing);
    expect(replacement.childNodes[1]).toBe(source);
    expect(target.childNodes).toHaveLength(0);
  });

  it("refuses any other fragment action instead of changing the tree", () => {
    const { target, doc } = tree();
    expect(() => fragmentReplacement(target, doc.createElement("item"), "navigate"))
      .toThrow("Unsupported owned fragment action");
    expect(target.getElementsByTagName("text")).toHaveLength(1);
  });
});

describe("public reload contract", () => {
  it.each([null, undefined, "#"])("keeps the current URL for an empty destination: %s", href => {
    expect(reloadUrl(href, BASE)).toBe(BASE);
  });

  it("resolves a relative URL without losing its query", () => {
    expect(reloadUrl("../categories/?sort=name", BASE))
      .toBe("https://hypertodo.test/hv/categories/?sort=name");
  });

  it.each([
    "https://other.test/hv/tasks/",
    "#details",
    "https://hypertodo.test/hv/tasks/#details",
    "javascript:alert(1)",
  ])("rejects a destination outside an ordinary same-origin screen: %s", href => {
    expect(() => reloadUrl(href, BASE)).toThrow("unsupported-href");
  });

  it("accepts exactly one owned screen with the matching request marker", () => {
    const doc = reloadDocument();
    const result = prepareReload(doc, "attempt-1");
    expect(result.boundary.localName).toBe("realtime");
    expect(result.boundary.namespaceURI).toBe(APP);
    expect(result.styles).toBeDefined();
  });

  it.each([
    ["wrong root", `<view xmlns="${HV}"/>`],
    ["no screen", `<doc xmlns="${HV}"/>`],
    ["two screens", `<doc xmlns="${HV}"><screen/><screen/></doc>`],
    ["navigator", `<doc xmlns="${HV}"><navigator/><screen/></doc>`],
    ["no boundary", `<doc xmlns="${HV}"><screen/></doc>`],
    ["two boundaries", `<doc xmlns="${HV}" xmlns:app="${APP}"><screen><app:realtime/><app:realtime/></screen></doc>`],
  ])("rejects an unsupported %s document", (_reason, xml) => {
    expect(() => prepareReload(parse(xml), "attempt-1")).toThrow(UnsupportedDocument);
  });

  it("rejects a screen whose marker belongs to a different request", () => {
    expect(() => prepareReload(reloadDocument("old-attempt"), "attempt-1"))
      .toThrow("Reload result does not match its attempt");
  });
});

describe("public navigation target", () => {
  const state = (name = "tasks") => ({ index: 0, routeNames: ["tasks", "settings", "card"], routes: [{ key: "current", name }] });
  const handle = (route = "tasks", parent?: unknown) => ({
    canGoBack: jest.fn(() => false),
    getParent: jest.fn(() => parent),
    getState: jest.fn(() => state(route)),
  });

  it("reports a no-op when back has no preceding route", () => {
    const nav = handle();
    expect(navigationTarget(nav as never, null, "back", BASE))
      .toMatchObject({ navigation: nav, reason: "navigation-no-op" });
    expect(nav.canGoBack).toHaveBeenCalledTimes(1);
  });

  it("retains back when the stack can go back", () => {
    const nav = handle();
    nav.canGoBack.mockReturnValue(true);
    expect(navigationTarget(nav as never, null, "back", BASE).reason).toBeNull();
  });

  it.each([null, undefined, "#"])("refuses an absent forward destination: %s", href => {
    const nav = handle();
    expect(navigationTarget(nav as never, href, "navigate", BASE).reason)
      .toBe("missing-destination");
  });

  it("recognizes a named route already in focus as a no-op", () => {
    const nav = handle();
    expect(navigationTarget(nav as never, "#tasks", "navigate", BASE))
      .toMatchObject({ navigation: nav, name: "tasks", reason: "navigation-no-op" });
  });

  it("uses a parent that actually declares the named route", () => {
    const parent = handle("tasks");
    const child = handle("child", parent);
    child.getState.mockReturnValue({ index: 0, routeNames: ["child"], routes: [{ key: "child", name: "child" }] });
    expect(navigationTarget(child as never, "#settings", "navigate", BASE))
      .toMatchObject({ navigation: parent, name: "settings", reason: null });
  });

  it("reports a named route missing from every public navigator", () => {
    const nav = handle();
    expect(navigationTarget(nav as never, "#deleted", "navigate", BASE))
      .toMatchObject({ navigation: nav, name: "deleted", reason: "missing-destination" });
  });

  it("selects a declared card route for same-origin URL navigation", () => {
    const nav = handle();
    expect(navigationTarget(nav as never, "/hv/tasks/1/", "push", BASE))
      .toMatchObject({ navigation: nav, name: "card", reason: null, url: "https://hypertodo.test/hv/tasks/1/" });
  });

  it("does not guess a card destination when no navigator declares one", () => {
    const nav = handle();
    nav.getState.mockReturnValue({ index: 0, routeNames: ["tasks"], routes: [{ key: "current", name: "tasks" }] });
    expect(navigationTarget(nav as never, "/hv/tasks/1/", "navigate", BASE))
      .toMatchObject({ navigation: nav, name: "card", reason: "missing-destination" });
  });
});

describe("screen state ownership", () => {
  it("returns caller-supplied public callbacks without wrapping them", () => {
    const callbacks = { getState: jest.fn(() => ({})), setState: jest.fn() };
    expect(screenCallbacks({ onUpdateCallbacks: callbacks } as never)).toBe(callbacks);
  });

  it.each([undefined, { getState: jest.fn() }, { setState: jest.fn() }])
    ("rejects absent or incomplete screen callbacks", callbacks => {
      expect(() => screenCallbacks({ onUpdateCallbacks: callbacks } as never))
        .toThrow("missing-screen-callback");
    });
});

describe("captured previous route", () => {
  const state = () => ({
    key: "owner", type: "stack", index: 1,
    routes: [{ key: "first", name: "tasks" }, { key: "current", name: "card" }],
  });
  const nav = (value = state()) => ({
    getState: jest.fn(() => value), getParent: jest.fn(() => undefined), dispatch: jest.fn(),
  });

  it("does not capture a previous route if the current screen is not focused", () => {
    const owner = nav();
    expect(previousRoute(owner as never, "first")).toBeNull();
    expect(owner.dispatch).not.toHaveBeenCalled();
  });

  it("does not capture an unnamed previous entry", () => {
    const owner = nav({ ...state(), routes: [{ name: "tasks" } as never, state().routes[1]] });
    expect(previousRoute(owner as never, "current")).toBeNull();
  });

  it("invalidates a capture if the preceding route changes before dispatch", () => {
    let current = state();
    const owner = { getState: jest.fn(() => current), getParent: jest.fn(), dispatch: jest.fn() };
    const previous = previousRoute(owner as never, "current")!;
    current = { ...current, routes: [{ key: "replacement", name: "tasks" }, current.routes[1]] };
    expect(previous.isCurrent()).toBe(false);
    expect(previous.goBack()).toBe(false);
    expect(owner.dispatch).not.toHaveBeenCalled();
  });

  it("dispatches once when the captured stack is still current", () => {
    const owner = nav();
    const previous = previousRoute(owner as never, "current")!;
    expect(previous.key).toBe("first");
    expect(previous.goBack()).toBe(true);
    expect(previous.goBack()).toBe(false);
    expect(owner.dispatch).toHaveBeenCalledTimes(1);
    expect(owner.dispatch.mock.calls[0][0]).toMatchObject({ source: "current", target: "owner" });
  });
});
