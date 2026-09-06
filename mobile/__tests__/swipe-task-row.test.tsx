import React from "react";
import { Alert } from "react-native";
import { fireEvent, render } from "@testing-library/react-native";

jest.mock("hyperview", () => ({
  createStyleProp: jest.fn(() => [{ marginBottom: 12 }]),
  renderChildren: jest.fn(() => null),
}));

import SwipeTaskRow from "../src/components/SwipeTaskRow";

const attributes: Record<string, string> = {
  id: "task-swipe-123",
  "edit-href": "/hv/tasks/123/edit/",
  "toggle-href": "/hv/tasks/123/toggle/",
  "delete-href": "/hv/tasks/123/delete/",
  completed: "false",
};
const element = {
  getAttribute: (name: string) => attributes[name] ?? null,
} as Element;
const props = {
  element,
  onUpdate: jest.fn(),
  options: {},
  stylesheets: { regular: {}, selected: {}, pressed: {}, focused: {}, pressedSelected: {} },
};

describe("SwipeTaskRow", () => {
  const openActions = (screen: ReturnType<typeof render>): void => {
    const row = screen.getByTestId("task-swipe-123");
    fireEvent(row, "responderMove", {}, { dx: -100, dy: 0 });
    fireEvent(row, "responderRelease", {}, { dx: -100, dy: 0 });
  };

  beforeEach(() => {
    props.onUpdate.mockClear();
    jest.restoreAllMocks();
  });

  it("reveals accessible Edit, Complete, and Delete actions", () => {
    const screen = render(<SwipeTaskRow {...props} />);

    expect(screen.getByRole("button", { name: "Edit task" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "Complete task" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "Delete task" })).toBeTruthy();
  });

  it("keeps task content stationary beneath an absolute action tray", () => {
    const screen = render(<SwipeTaskRow {...props} />);

    expect(screen.getByTestId("task-swipe-content").props.style).not.toEqual(
      expect.objectContaining({ transform: expect.anything() }),
    );
    expect(screen.getByTestId("task-swipe-actions").props.style).toEqual(
      expect.objectContaining({ position: "absolute", right: 0 }),
    );
  });

  it("opens editing as a new Hyperview route", () => {
    const screen = render(<SwipeTaskRow {...props} />);
    openActions(screen);

    fireEvent.press(screen.getByRole("button", { name: "Edit task" }));

    expect(props.onUpdate).toHaveBeenCalledWith(
      "/hv/tasks/123/edit/",
      "new",
      element,
      { verb: "get" },
    );
  });

  it("posts completion through the surrounding HXML form", () => {
    const screen = render(<SwipeTaskRow {...props} />);
    openActions(screen);

    fireEvent.press(screen.getByRole("button", { name: "Complete task" }));

    expect(props.onUpdate).toHaveBeenCalledWith(
      "/hv/tasks/123/toggle/",
      "replace",
      element,
      { targetId: "task-swipe-123", verb: "post" },
    );
  });

  it("confirms deletion before posting it", () => {
    jest.spyOn(Alert, "alert").mockImplementation((_title, _message, buttons) => {
      buttons?.find((button) => button.style === "destructive")?.onPress?.();
    });
    const screen = render(<SwipeTaskRow {...props} />);
    openActions(screen);

    fireEvent.press(screen.getByRole("button", { name: "Delete task" }));

    expect(Alert.alert).toHaveBeenCalledWith(
      "Delete task?",
      "This action cannot be undone.",
      expect.any(Array),
    );
    expect(props.onUpdate).toHaveBeenCalledWith(
      "/hv/tasks/123/delete/",
      "replace",
      element,
      { targetId: "task-swipe-123", verb: "post" },
    );
  });
});
