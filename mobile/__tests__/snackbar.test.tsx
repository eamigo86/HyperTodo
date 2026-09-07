import React from "react";
import { act, fireEvent, render } from "@testing-library/react-native";

import ShowSnackbarBehavior from "../src/behaviors/ShowSnackbarBehavior";
import SnackbarHost from "../src/components/SnackbarHost";
import { publishSnackbar, subscribeToSnackbars } from "../src/feedback/snackbar";

describe("server-driven snackbar feedback", () => {
  beforeEach(() => {
    jest.useFakeTimers();
  });

  afterEach(() => {
    jest.useRealTimers();
  });

  it("publishes the HXML behavior payload", () => {
    const listener = jest.fn();
    const unsubscribe = subscribeToSnackbars(listener);
    const element = {
      getAttribute: (name: string) => ({
        message: "Task created.",
        tone: "success",
      })[name] ?? null,
    } as Element;

    ShowSnackbarBehavior.callback(element, jest.fn(), jest.fn(), jest.fn());

    expect(listener).toHaveBeenCalledWith({ message: "Task created.", tone: "success" });
    unsubscribe();
  });

  it("renders blue success and red error feedback above navigation", () => {
    const screen = render(<SnackbarHost />);

    act(() => publishSnackbar({ message: "Task created.", tone: "success" }));
    expect(screen.getByText("Task created.")).toBeTruthy();
    expect(screen.getByTestId("snackbar-surface").props.style).toEqual(
      expect.objectContaining({ backgroundColor: "#1F6FD1" }),
    );
    expect(screen.getByTestId("snackbar-host").props.style).toEqual(
      expect.objectContaining({ bottom: 104 }),
    );

    act(() => publishSnackbar({ message: "Could not save task.", tone: "error" }));
    expect(screen.getByText("Could not save task.")).toBeTruthy();
    expect(screen.getByTestId("snackbar-surface").props.style).toEqual(
      expect.objectContaining({ backgroundColor: "#D92D20" }),
    );
  });

  it("can be dismissed without waiting for its timeout", () => {
    const screen = render(<SnackbarHost />);
    act(() => publishSnackbar({ message: "Category deleted.", tone: "success" }));

    fireEvent.press(screen.getByRole("button", { name: "Dismiss notification" }));
    act(() => jest.runAllTimers());

    expect(screen.queryByText("Category deleted.")).toBeNull();
  });
});

// Both fills are deliberately palette-independent: they carry a white 14/600 label,
// and dark's `danger` (#FF9E93) or a lighter blue would drop that label under 4.5:1.
// What they DO owe is legibility on both canvases, which the floors below pin.
describe("snackbar contrast", () => {
  const luminance = (hex: string) =>
    [1, 3, 5]
      .map((index) => parseInt(hex.slice(index, index + 2), 16) / 255)
      .map((value) => (value <= 0.04045 ? value / 12.92 : ((value + 0.055) / 1.055) ** 2.4))
      .reduce((total, value, index) => total + [0.2126, 0.7152, 0.0722][index] * value, 0);
  const ratio = (a: string, b: string) => {
    const [light, dark] = [luminance(a), luminance(b)].sort((x, y) => y - x);
    return (light + 0.05) / (dark + 0.05);
  };
  const CANVASES = ["#F7F8FC", "#0F1118"];

  it.each([
    ["success", "#1F6FD1"],
    ["error", "#D92D20"],
  ])("keeps the white %s label above AA on a fill both canvases can carry", (_tone, fill) => {
    // #147DEB, the fill this replaced, was 4.07:1 -- an AA failure in the SHIPPED
    // light theme, not something dark mode introduced.
    expect(ratio("#FFFFFF", fill)).toBeGreaterThanOrEqual(4.5);
    CANVASES.forEach((canvas) => expect(ratio(fill, canvas)).toBeGreaterThanOrEqual(3));
  });
});
