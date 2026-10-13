import React from "react";
import { NavigationContext } from "@react-navigation/native";
import { act, fireEvent, render } from "@testing-library/react-native";
import { Animated, BackHandler, StyleSheet } from "react-native";

jest.mock("expo-secure-store", () => ({ getItem: () => null, setItem: () => undefined }));
jest.mock("hyperview", () => ({
  createStyleProp: jest.fn(() => []),
  renderChildren: jest.fn(() => null),
}));

let mockWindowWidth = 390;
jest.mock("react-native/Libraries/Utilities/useWindowDimensions", () => ({
  __esModule: true,
  default: () => ({ width: mockWindowWidth, height: 844, scale: 3, fontScale: 1 }),
}));

import AnimatedSideMenu from "../src/components/AnimatedSideMenu";
import { publishTheme } from "../src/theme";

function elementWith(attributes: Record<string, string>): Element {
  return {
    getAttribute: (name: string) => attributes[name] ?? null,
  } as Element;
}

const element = elementWith({
  id: "side-menu-host",
  "close-href": "/hv/menu/close/",
  "animation-duration": "220",
});

const props = {
  element,
  onUpdate: jest.fn(),
  options: {},
  stylesheets: { regular: {}, selected: {}, pressed: {}, focused: {}, pressedSelected: {} },
};

describe("AnimatedSideMenu", () => {
  beforeEach(() => {
    jest.useFakeTimers();
    mockWindowWidth = 390;
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

  it("dims the entire screen behind the moving panel", () => {
    const screen = render(<AnimatedSideMenu {...props} />);
    const backdrop = screen.getByTestId("side-menu-backdrop");
    const style = StyleSheet.flatten(backdrop.props.style);

    expect(style).toEqual(
      expect.objectContaining({
        bottom: 0,
        left: 0,
        position: "absolute",
        right: 0,
        top: 0,
      }),
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

  // The drawer width is the ONE thing HXML cannot reach: AnimatedSideMenu owns the
  // initial Animated.Value, the dismiss toValue and styles.panel, and they must all
  // agree or the panel sits partly on-screen before the animation starts. A
  // percentage of the window is the right knob, not points: supportsTablet is false
  // and the orientation is locked portrait (app.config.ts:61,85), so 286pt is 89% of
  // a 320pt screen and only 67% of a 430pt one.
  it("takes the panel width from the server as a percentage of the window", () => {
    const timing = jest.spyOn(Animated, "timing");
    const wide = elementWith({
      id: "side-menu-host",
      "close-href": "/hv/menu/close/",
      "animation-duration": "220",
      "panel-width": "80",
    });

    const screen = render(<AnimatedSideMenu {...props} element={wide} />);

    expect(
      StyleSheet.flatten(screen.getByTestId("side-menu-panel").props.style).width,
    ).toBe(312);
    expect(timing).toHaveBeenCalledWith(
      expect.anything(),
      expect.objectContaining({ toValue: 0 }),
    );
  });

  it("keeps the shipped 286pt when the server declares no width", () => {
    const screen = render(<AnimatedSideMenu {...props} />);

    expect(
      StyleSheet.flatten(screen.getByTestId("side-menu-panel").props.style).width,
    ).toBe(286);
  });

  it("slides the panel back out by exactly the width it came in at", () => {
    const timing = jest.spyOn(Animated, "timing");
    const wide = elementWith({
      id: "side-menu-host",
      "close-href": "/hv/menu/close/",
      "animation-duration": "220",
      "panel-width": "80",
    });
    const screen = render(<AnimatedSideMenu {...props} element={wide} />);

    fireEvent.press(screen.getByTestId("side-menu-scrim"));

    expect(timing).toHaveBeenCalledWith(
      expect.anything(),
      expect.objectContaining({ toValue: -312 }),
    );
  });
});

// The drawer is a full-screen overlay: assistive technology has to treat it as modal,
// Android Back has to close it, and a close that never completes must not leave an
// invisible overlay swallowing taps.
describe("AnimatedSideMenu as a modal overlay", () => {
  beforeEach(() => {
    jest.useFakeTimers();
    mockWindowWidth = 390;
    props.onUpdate.mockClear();
  });

  afterEach(() => {
    jest.restoreAllMocks();
    jest.useRealTimers();
  });

  // Hidden elements are included: a closing overlay is deliberately hidden from assistive technology.
  const root = (screen: ReturnType<typeof render>) => screen.getByTestId("side-menu-host", { includeHiddenElements: true });
  const closeRequests = () => props.onUpdate.mock.calls.filter(([href]) => href === "/hv/menu/close/");
  const backHandler = () => {
    let handler: Parameters<typeof BackHandler.addEventListener>[1] | undefined;
    const remove = jest.fn();
    const add = jest.spyOn(BackHandler, "addEventListener").mockImplementation((_event, listener) => {
      handler = listener;
      return { remove };
    });
    return { add, remove, press: () => handler!({ type: "hardwareBackPress", timeStamp: 0 }) };
  };

  it("is modal for assistive technology and closes on the VoiceOver escape gesture", () => {
    const screen = render(<AnimatedSideMenu {...props} />);

    expect(root(screen).props.accessibilityViewIsModal).toBe(true);
    expect(typeof root(screen).props.onAccessibilityEscape).toBe("function");
    act(() => root(screen).props.onAccessibilityEscape());
    expect(props.onUpdate).not.toHaveBeenCalled();
    act(() => jest.advanceTimersByTime(220));

    expect(closeRequests()).toHaveLength(1);
  });

  it("exposes the scrim as a button that closes the menu", () => {
    const screen = render(<AnimatedSideMenu {...props} />);

    const scrim = screen.getByRole("button", { name: "Close menu overlay" });
    expect(scrim.props.accessibilityRole).toBe("button");
    fireEvent.press(scrim);
    act(() => jest.advanceTimersByTime(220));

    expect(closeRequests()).toHaveLength(1);
  });

  it("closes on Android Back, swallowing the press, and stops listening on unmount", () => {
    const back = backHandler();
    const screen = render(<AnimatedSideMenu {...props} />);
    expect(back.add).toHaveBeenCalledWith("hardwareBackPress", expect.any(Function));

    let handled: boolean | null | undefined;
    act(() => { handled = back.press(); });
    expect(handled).toBe(true);
    act(() => jest.advanceTimersByTime(220));
    expect(closeRequests()).toHaveLength(1);

    screen.unmount();
    expect(back.remove).toHaveBeenCalledTimes(1);
  });

  it("does not trap Android Back while the menu is already closing", () => {
    const back = backHandler();
    render(<AnimatedSideMenu {...props} />);

    act(() => { back.press(); });
    let handled: boolean | null | undefined;
    act(() => { handled = back.press(); });
    act(() => jest.advanceTimersByTime(220));

    expect(handled).toBe(false);
    expect(closeRequests()).toHaveLength(1);
  });

  // A link in the menu navigates, and its close request can fail offline: the menu then stays
  // mounted under the screen that was pushed over it, and must not take that screen's Back.
  it("leaves Back to the screen on top while its own screen is not focused", () => {
    const back = backHandler();
    const navigation = { isFocused: jest.fn(() => false) } as unknown as React.ContextType<typeof NavigationContext>;
    render(
      <NavigationContext.Provider value={navigation}>
        <AnimatedSideMenu {...props} />
      </NavigationContext.Provider>,
    );

    let handled: boolean | null | undefined;
    act(() => { handled = back.press(); });
    act(() => jest.advanceTimersByTime(220));
    expect(handled).toBe(false);
    expect(props.onUpdate).not.toHaveBeenCalled();

    (navigation!.isFocused as jest.Mock).mockReturnValue(true);
    act(() => { handled = back.press(); });
    expect(handled).toBe(true);
  });

  it("stops taking touches and hides from assistive technology once it is closing", () => {
    const screen = render(<AnimatedSideMenu {...props} />);
    expect(root(screen).props.pointerEvents).toBe("auto");
    expect(root(screen).props.importantForAccessibility).toBe("auto");

    fireEvent.press(screen.getByTestId("side-menu-scrim"));

    // A full-screen overlay that is invisible and still modal would swallow every tap and
    // keep VoiceOver away from the screen behind it.
    expect(root(screen).props.pointerEvents).toBe("none");
    expect(root(screen).props.accessibilityViewIsModal).toBe(false);
    expect(root(screen).props.accessibilityElementsHidden).toBe(true);
    expect(root(screen).props.importantForAccessibility).toBe("no-hide-descendants");
  });

  it("opens again when the server renders the menu anew after a close request that failed", () => {
    const timing = jest.spyOn(Animated, "timing");
    const back = backHandler();
    const screen = render(<AnimatedSideMenu {...props} />);

    // The close request goes out and fails: the element never changes, the overlay stays.
    fireEvent.press(screen.getByTestId("side-menu-scrim"));
    act(() => jest.advanceTimersByTime(220));
    expect(closeRequests()).toHaveLength(1);
    expect(root(screen).props.pointerEvents).toBe("none");

    // The edge swipe asks for the menu again and gets a fresh element in the same place.
    timing.mockClear();
    const reopened = elementWith({ id: "side-menu-host", "close-href": "/hv/menu/close/", "animation-duration": "220" });
    screen.rerender(<AnimatedSideMenu {...props} element={reopened} />);

    expect(root(screen).props.pointerEvents).toBe("auto");
    expect(root(screen).props.accessibilityViewIsModal).toBe(true);
    expect(timing).toHaveBeenCalledWith(expect.anything(), expect.objectContaining({ duration: 220, toValue: 0 }));
    expect(timing).toHaveBeenCalledWith(expect.anything(), expect.objectContaining({ duration: 220, toValue: 0.22 }));
    fireEvent.press(screen.getByTestId("side-menu-scrim"));
    act(() => jest.advanceTimersByTime(220));
    expect(closeRequests()).toHaveLength(2);
    expect(closeRequests()[1][2]).toBe(reopened);

    let handled: boolean | null | undefined;
    screen.rerender(<AnimatedSideMenu {...props} element={elementWith({ id: "side-menu-host", "close-href": "/hv/menu/close/" })} />);
    act(() => { handled = back.press(); });
    expect(handled).toBe(true);
  });

  it("keeps the dismissal latched while the same element is only re-rendered", () => {
    const screen = render(<AnimatedSideMenu {...props} />);

    fireEvent.press(screen.getByTestId("side-menu-scrim"));
    screen.rerender(<AnimatedSideMenu {...props} />);
    act(() => jest.advanceTimersByTime(220));

    expect(root(screen).props.pointerEvents).toBe("none");
    expect(closeRequests()).toHaveLength(1);
  });
});

// The drawer's own chrome is the one part of the menu the server cannot style:
// the scrim and the close disc are drawn by this component, not by HXML.
describe("the drawer chrome follows the palette the server named", () => {
  afterEach(() => act(() => publishTheme("light")));

  const flat = (node: { props: Record<string, unknown> }) =>
    StyleSheet.flatten(node.props.style as never) as Record<string, string>;

  it("repaints the scrim and the close disc", () => {
    const screen = render(<AnimatedSideMenu {...props} />);

    expect(flat(screen.getByTestId("side-menu-backdrop")).backgroundColor).toBe("#161A35");
    expect(flat(screen.getByRole("button", { name: "Close menu" })).backgroundColor).toBe("#EEF2FC");
    expect(flat(screen.getByText("×")).color).toBe("#4C526B");

    act(() => publishTheme("dark"));

    // Pure black at 0.22 opacity: #161A35 barely dims a canvas that is already
    // nearly black, so the panel would float with nothing behind it.
    expect(flat(screen.getByTestId("side-menu-backdrop")).backgroundColor).toBe("#000000");
    expect(flat(screen.getByRole("button", { name: "Close menu" })).backgroundColor).toBe("#232733");
    // 7.93:1 on the dark chip at 26px, against 6.87:1 in light.
    expect(flat(screen.getByText("×")).color).toBe("#B7BDCE");
  });
});
