import React from "react";
import { act, fireEvent, render } from "@testing-library/react-native";
import { Animated } from "react-native";

jest.mock("hyperview", () => ({
  createStyleProp: jest.fn(() => []),
  renderChildren: jest.fn(() => null),
}));

import AnimatedSideMenu from "../src/components/AnimatedSideMenu";

const element = {
  getAttribute: (name: string) => ({
    id: "side-menu-host",
    "close-href": "/hv/menu/close/",
    "animation-duration": "220",
  })[name] ?? null,
} as Element;

const props = {
  element,
  onUpdate: jest.fn(),
  options: {},
  stylesheets: { regular: {}, selected: {}, pressed: {}, focused: {}, pressedSelected: {} },
};

describe("AnimatedSideMenu", () => {
  beforeEach(() => {
    jest.useFakeTimers();
    props.onUpdate.mockClear();
  });

  afterEach(() => {
    jest.restoreAllMocks();
    jest.useRealTimers();
  });

  it("slides the panel in and fades the scrim on mount", () => {
    const timing = jest.spyOn(Animated, "timing");

    render(<AnimatedSideMenu {...props} />);

    expect(timing).toHaveBeenCalledWith(
      expect.anything(),
      expect.objectContaining({ duration: 220, toValue: 0 }),
    );
    expect(timing).toHaveBeenCalledWith(
      expect.anything(),
      expect.objectContaining({ duration: 220, toValue: 0.22 }),
    );
  });

  it("animates out before closing when the scrim is pressed", () => {
    const screen = render(<AnimatedSideMenu {...props} />);

    fireEvent.press(screen.getByTestId("side-menu-scrim"));
    expect(props.onUpdate).not.toHaveBeenCalled();

    act(() => jest.advanceTimersByTime(220));
    expect(props.onUpdate).toHaveBeenCalledWith(
      "/hv/menu/close/",
      "replace",
      element,
      { targetId: "side-menu-host", verb: "get" },
    );
  });

  it("uses the same animated dismissal for the close button", () => {
    const screen = render(<AnimatedSideMenu {...props} />);

    fireEvent.press(screen.getByRole("button", { name: "Close menu" }));
    act(() => jest.advanceTimersByTime(220));

    expect(props.onUpdate).toHaveBeenCalledTimes(1);
  });
});
