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
      expect.objectContaining({ backgroundColor: "#147DEB" }),
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
