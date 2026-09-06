import React from "react";
import { Alert } from "react-native";
import { fireEvent, render } from "@testing-library/react-native";

const mockClose = jest.fn();

jest.mock("react-native-gesture-handler", () => {
  const { View } = require("react-native");
  return {
    Swipeable: ({ children, renderRightActions }: any) => (
      <View testID="swipeable-row">
        {children}
        {renderRightActions?.(null, null, { close: mockClose })}
      </View>
    ),
  };
});

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
  beforeEach(() => {
    props.onUpdate.mockClear();
    mockClose.mockClear();
    jest.restoreAllMocks();
  });

  it("reveals accessible Edit, Complete, and Delete actions", () => {
    const screen = render(<SwipeTaskRow {...props} />);

    expect(screen.getByRole("button", { name: "Edit task" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "Complete task" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "Delete task" })).toBeTruthy();
  });

  it("opens editing as a new Hyperview route", () => {
    const screen = render(<SwipeTaskRow {...props} />);

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

    fireEvent.press(screen.getByRole("button", { name: "Complete task" }));

    expect(props.onUpdate).toHaveBeenCalledWith(
      "/hv/tasks/123/toggle/",
      "replace",
      element,
      { verb: "post" },
    );
  });

  it("confirms deletion before posting it", () => {
    jest.spyOn(Alert, "alert").mockImplementation((_title, _message, buttons) => {
      buttons?.find((button) => button.style === "destructive")?.onPress?.();
    });
    const screen = render(<SwipeTaskRow {...props} />);

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
      { verb: "post" },
    );
  });
});
