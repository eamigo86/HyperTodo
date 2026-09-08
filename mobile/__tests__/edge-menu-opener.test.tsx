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

  it("ignores a short edge drag", () => {
    render(<EdgeMenuOpener {...props} />);

    act(() => responder().onPanResponderRelease({}, { dx: 30, dy: 1 }));

    expect(props.onUpdate).not.toHaveBeenCalled();
  });

  it("renders only the narrow server-styled edge hit area", () => {
    const screen = render(<EdgeMenuOpener {...props} />);

    expect(screen.getByTestId("dashboard-edge-menu").props.style).toEqual([
      { left: 0, width: 24 },
    ]);
  });
});
