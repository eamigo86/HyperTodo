import React from "react";
import { PanResponder } from "react-native";
import { act, render } from "@testing-library/react-native";

jest.mock("hyperview", () => ({
  createStyleProp: jest.fn(() => [{ left: 0, width: 24 }]),
}));

import EdgeMenuOpener from "../src/components/EdgeMenuOpener";

function elementWith(attributes: Record<string, string>): Element {
  return {
    getAttribute: (name: string) => attributes[name] ?? null,
  } as Element;
}

const element = elementWith({
  id: "dashboard-edge-menu",
  href: "/hv/menu/?active=dashboard",
  target: "side-menu-host",
});
const props = {
  element,
  onUpdate: jest.fn(),
  options: {},
  stylesheets: { regular: {}, selected: {}, pressed: {}, focused: {}, pressedSelected: {} },
};

describe("EdgeMenuOpener", () => {
  beforeEach(() => {
    props.onUpdate.mockClear();
    jest.spyOn(PanResponder, "create");
  });

  afterEach(() => jest.restoreAllMocks());

  const responder = () => (PanResponder.create as jest.Mock).mock.calls.at(-1)?.[0];

  it("claims only rightward horizontal movement from the dashboard edge", () => {
    render(<EdgeMenuOpener {...props} />);
    const config = responder();

    expect(config.onMoveShouldSetPanResponder({}, { dx: 12, dy: 2 })).toBe(true);
    expect(config.onMoveShouldSetPanResponder({}, { dx: -12, dy: 2 })).toBe(false);
    expect(config.onMoveShouldSetPanResponder({}, { dx: 12, dy: 18 })).toBe(false);
  });

  it("opens the dashboard menu after a deliberate right swipe", () => {
    render(<EdgeMenuOpener {...props} />);

    act(() => responder().onPanResponderRelease({}, { dx: 64, dy: 4 }));

    expect(props.onUpdate).toHaveBeenCalledWith(
      "/hv/menu/?active=dashboard",
      "replace",
      element,
      { targetId: "side-menu-host", verb: "get" },
    );
  });

  // backend/schema/hypertodo.xsd requires `action` (navigate | replace) on this element.
  it.each([
    ["navigate", "navigate"],
    ["replace", "replace"],
    [undefined, "replace"],
    ["push", "replace"],
  ])("opens the menu with the declared action %s as %s", (declared, expected) => {
    const withAction = elementWith({
      id: "dashboard-edge-menu",
      href: "/hv/menu/?active=dashboard",
      target: "side-menu-host",
      ...(declared ? { action: declared } : {}),
    });
    render(<EdgeMenuOpener {...props} element={withAction} />);

    act(() => responder().onPanResponderRelease({}, { dx: 64, dy: 4 }));

    expect(props.onUpdate).toHaveBeenCalledWith(
      "/hv/menu/?active=dashboard",
      expected,
      withAction,
      { targetId: "side-menu-host", verb: "get" },
    );
  });

  it("ignores a short edge drag", () => {
    render(<EdgeMenuOpener {...props} />);

    act(() => responder().onPanResponderRelease({}, { dx: 30, dy: 1 }));

    expect(props.onUpdate).not.toHaveBeenCalled();
  });

  it("ignores a long but predominantly vertical drag", () => {
    render(<EdgeMenuOpener {...props} />);
    const config = responder();
    expect(config.onMoveShouldSetPanResponderCapture({}, { dx: 60, dy: 70 })).toBe(false);
    expect(config.onMoveShouldSetPanResponderCapture({}, { dx: 60, dy: 2 })).toBe(true);
    act(() => config.onPanResponderRelease({}, { dx: 60, dy: 70 }));
    expect(props.onUpdate).not.toHaveBeenCalled();
    expect(config.onPanResponderTerminationRequest()).toBe(false);
  });

  it("uses the declared menu destination when provided and defaults when omitted", () => {
    const explicit = elementWith({ href: "/hv/menu/?active=tasks", target: "custom-host" });
    render(<EdgeMenuOpener {...props} element={explicit} />);
    act(() => responder().onPanResponderRelease({}, { dx: 64, dy: 4 }));
    expect(props.onUpdate).toHaveBeenCalledWith("/hv/menu/?active=tasks", "replace", explicit, { targetId: "custom-host", verb: "get" });

    const absent = elementWith({});
    render(<EdgeMenuOpener {...props} element={absent} />);
    act(() => responder().onPanResponderRelease({}, { dx: 64, dy: 4 }));
    expect(props.onUpdate).toHaveBeenLastCalledWith("/hv/menu/?active=dashboard", "replace", absent, { targetId: "side-menu-host", verb: "get" });
  });

  it("renders only the narrow server-styled edge hit area", () => {
    const screen = render(<EdgeMenuOpener {...props} />);

    expect(screen.getByTestId("dashboard-edge-menu").props.style).toEqual([
      { left: 0, width: 24 },
    ]);
  });
});
