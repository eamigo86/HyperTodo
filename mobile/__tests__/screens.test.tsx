import React from "react";
import { fireEvent, render } from "@testing-library/react-native";

import { ErrorScreen, LoadingScreen } from "../App";

jest.mock("expo-splash-screen", () => ({ preventAutoHideAsync: jest.fn(), hideAsync: jest.fn() }));
jest.mock("hyperview", () => () => null);
jest.mock("@react-navigation/native", () => ({ NavigationContainer: ({ children }: { children: React.ReactNode }) => children }));

describe("owned shell screens", () => {
  it("renders the branded loading state", () => {
    const screen = render(<LoadingScreen />);
    expect(screen.getByText("HyperTodo")).toBeTruthy();
    expect(screen.getByLabelText("Loading HyperTodo")).toBeTruthy();
  });

  it("renders an actionable error state", () => {
    const reload = jest.fn();
    const screen = render(<ErrorScreen error={new Error("Backend unavailable")} onPressReload={reload} back={jest.fn()} onPressViewDetails={jest.fn()} />);
    expect(screen.getByText("Backend unavailable")).toBeTruthy();
    fireEvent.press(screen.getByRole("button", { name: "Try again" }));
    expect(reload).toHaveBeenCalledTimes(1);
  });
});
