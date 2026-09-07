import React from "react";
import { Alert, PanResponder } from "react-native";
import { act, fireEvent, render } from "@testing-library/react-native";

jest.mock("hyperview", () => ({
  createStyleProp: jest.fn(() => [{ marginBottom: 12 }]),
}));
jest.mock("hyperview/src/services/render", () => ({
  renderChildNodes: jest.fn(() => null),
}));

import { renderChildNodes } from "hyperview/src/services/render";

import SwipeRow from "../src/components/SwipeRow";

const NAMESPACE = "https://hypertodo.app/components";
const HYPERVIEW = "https://hyperview.org/hyperview";

function node(
  namespaceURI: string,
  localName: string,
  attributes: Record<string, string> = {},
): Element {
  return {
    namespaceURI,
    localName,
    nodeType: 1,
    getAttribute: (name: string) => attributes[name] ?? null,
  } as unknown as Element;
}

function rowWith(actions: Element[], attributes: Record<string, string> = {}): Element {
  const own: Record<string, string> = { id: "category-swipe-9", ...attributes };
  return {
    getAttribute: (name: string) => own[name] ?? null,
    childNodes: [node(HYPERVIEW, "view"), ...actions],
  } as unknown as Element;
}

const EDIT = node(NAMESPACE, "swipe-action", {
  href: "/hv/categories/9/edit/",
  action: "navigate",
  verb: "get",
  label: "Edit",
  "a11y-label": "Edit category",
  tone: "primary",
});
const DELETE = node(NAMESPACE, "swipe-action", {
  href: "/hv/categories/9/delete/",
  action: "replace",
  verb: "post",
  label: "Delete",
  "a11y-label": "Delete category",
  tone: "danger",
  "confirm-title": "Delete category?",
  "confirm-body": "Its tasks stay, without a category.",
  "confirm-label": "Delete",
});

const element = rowWith([EDIT, DELETE]);
const props = {
  element,
  onUpdate: jest.fn(),
  options: {},
  stylesheets: { regular: {}, selected: {}, pressed: {}, focused: {}, pressedSelected: {} },
};

describe("SwipeRow", () => {
  // The closed tray is hidden from the accessibility tree on purpose, and the
  // queries honour that, so reaching a button while the row is shut is explicit.
  const button = (screen: ReturnType<typeof render>, name: string) => {
    const node = screen.getByLabelText(name, { includeHiddenElements: true });
    expect(node.props.accessibilityRole).toBe("button");
    return node;
  };

  // fireEvent cannot drive this row. RNTL's isEventEnabled calls the nearest touch
  // responder's onMoveShouldSetResponder() with NO gesture, our config answers false
  // for a zero-length move, and every event on the root is then dropped in silence
  // (fire-event.js:39-52). The predecessor of this file "opened" rows that way and
  // was asserting against a row that never opened. Drive the config instead.
  const openActions = (): void => {
    const config = (PanResponder.create as jest.Mock).mock.calls.at(-1)?.[0];
    act(() => config.onPanResponderRelease({}, { dx: -100, dy: 0 }));
  };

  const renderRow = (element?: Element) => {
    jest.spyOn(PanResponder, "create");
    return render(<SwipeRow {...props} {...(element ? { element } : {})} />);
  };

  beforeEach(() => {
    props.onUpdate.mockClear();
    jest.restoreAllMocks();
  });

  it("renders exactly the actions the server declared and nothing else", () => {
    const screen = renderRow();

    expect(button(screen, "Edit category")).toBeTruthy();
    expect(button(screen, "Delete category")).toBeTruthy();
    expect(screen.queryByText("Complete", { includeHiddenElements: true })).toBeNull();
    expect(screen.queryByText("Reopen", { includeHiddenElements: true })).toBeNull();
    // The visible label and the accessible name are two different strings today
    // ("Edit" beside "Edit category"), so collapsing them would either bloat the
    // button or strip the context off the announcement.
    expect(screen.getByText("Edit", { includeHiddenElements: true })).toBeTruthy();
    expect(screen.getByText("Delete", { includeHiddenElements: true })).toBeTruthy();
  });

  it("ignores the pre-1.1.0 attribute shape riding alongside the children", () => {
    // partials/task_items.xml ships BOTH shapes on one tag, so no client version has
    // to be inferred from a header a proxy can strip. This is that contract's client
    // half: the four attributes an older binary drives are invisible here, so the
    // row never grows a fourth control and never posts an href off an attribute.
    const both = rowWith([EDIT, DELETE], {
      "edit-href": "/hv/tasks/9/edit/",
      "toggle-href": "/hv/tasks/9/toggle/",
      "delete-href": "/hv/tasks/9/delete/",
      completed: "false",
    });
    const screen = renderRow(both);
    openActions();

    expect(
      screen.getByTestId("swipe-row-actions", { includeHiddenElements: true }).props
        .style,
    ).toEqual(expect.objectContaining({ width: 176 }));
    expect(screen.queryByText("Complete", { includeHiddenElements: true })).toBeNull();

    fireEvent.press(button(screen, "Edit category"));

    expect(props.onUpdate).toHaveBeenCalledTimes(1);
    expect(props.onUpdate).toHaveBeenCalledWith(
      "/hv/categories/9/edit/",
      "navigate",
      both,
      { verb: "get" },
    );
  });

  it("keeps the declared actions out of the rendered content", () => {
    renderRow();

    const [childNodes] = (renderChildNodes as jest.Mock).mock.calls[0];
    expect(childNodes).toHaveLength(1);
    expect(childNodes[0].localName).toBe("view");
  });

  it("sizes every action identically and the tray to their sum", () => {
    const screen = renderRow();

    for (const name of ["Edit category", "Delete category"]) {
      expect(button(screen, name).props.style).toContainEqual({
        width: 88,
      });
    }
    expect(screen.getByTestId("swipe-row-actions", { includeHiddenElements: true }).props.style).toEqual(
      expect.objectContaining({ width: 176 }),
    );
  });

  it("keeps row content stationary beneath an absolute action tray", () => {
    const screen = renderRow();

    expect(screen.getByTestId("swipe-row-content", { includeHiddenElements: true }).props.style).not.toEqual(
      expect.objectContaining({ transform: expect.anything() }),
    );
    expect(screen.getByTestId("swipe-row-actions", { includeHiddenElements: true }).props.style).toEqual(
      expect.objectContaining({ position: "absolute", right: 0 }),
    );
  });

  it("keeps ownership of horizontal gestures when a child responder competes", () => {
    renderRow();
    const responderConfig = (PanResponder.create as jest.Mock).mock.calls[0][0];
    const horizontalGesture = { dx: -24, dy: 3 };

    expect(
      responderConfig.onMoveShouldSetPanResponderCapture?.(
        {} as never,
        horizontalGesture as never,
      ),
    ).toBe(true);
    expect(
      responderConfig.onPanResponderTerminationRequest?.({} as never, {} as never),
    ).toBe(false);
  });

  it("keeps a long label on one line", () => {
    const long = rowWith([
      node(NAMESPACE, "swipe-action", {
        href: "/hv/tasks/1/toggle/",
        action: "replace",
        verb: "post",
        label: "Complete",
        tone: "positive",
      }),
    ]);
    const screen = renderRow(long);

    expect(
      screen.getByText("Complete", { includeHiddenElements: true }).props.numberOfLines,
    ).toBe(1);
    // With no a11y-label the visible label is the announcement.
    expect(button(screen, "Complete")).toBeTruthy();
  });

  it("dispatches each action exactly as the server declared it", () => {
    const screen = renderRow();
    openActions();

    fireEvent.press(button(screen, "Edit category"));

    // `navigate` resolves to the dynamic `card` route (getRouteId,
    // services/navigator/helpers.ts:211-220); `new` would be a bottom sheet only
    // `close` can dismiss. No targetId, because nothing is being replaced.
    expect(props.onUpdate).toHaveBeenCalledWith(
      "/hv/categories/9/edit/",
      "navigate",
      element,
      { verb: "get" },
    );
  });

  it("confirms a destructive action with the server's own copy", () => {
    jest.spyOn(Alert, "alert").mockImplementation((_title, _message, buttons) => {
      buttons?.find((button) => button.style === "destructive")?.onPress?.();
    });
    const screen = renderRow();
    openActions();

    fireEvent.press(button(screen, "Delete category"));

    // Deleting a category keeps its tasks (Task.category is SET_NULL), so the copy
    // cannot be the task row's "cannot be undone".
    expect(Alert.alert).toHaveBeenCalledWith(
      "Delete category?",
      "Its tasks stay, without a category.",
      expect.any(Array),
    );
    expect(props.onUpdate).toHaveBeenCalledWith(
      "/hv/categories/9/delete/",
      "replace",
      element,
      { targetId: "category-swipe-9", verb: "post" },
    );
  });

  it("fires an action with no confirmation copy immediately", () => {
    const alert = jest.spyOn(Alert, "alert");
    const screen = renderRow();
    openActions();

    fireEvent.press(button(screen, "Edit category"));

    expect(alert).not.toHaveBeenCalled();
  });

  it("keeps the closed tray out of the accessibility tree", () => {
    // `overflow: hidden` does not prune the iOS accessibility tree, so the tray used
    // to announce three buttons per row whether or not the row was open: 80 elements
    // in a 20-row list, most of them invisible and none reachable by a gesture a
    // VoiceOver user has.
    const screen = renderRow();
    const tray = screen.getByTestId("swipe-row-actions", { includeHiddenElements: true });

    expect(tray.props.accessibilityElementsHidden).toBe(true);
    expect(tray.props.importantForAccessibility).toBe("no-hide-descendants");

    openActions();

    expect(screen.getByTestId("swipe-row-actions", { includeHiddenElements: true }).props.accessibilityElementsHidden).toBe(
      false,
    );
  });

  it("offers the same actions to a screen reader that cannot swipe", () => {
    const screen = renderRow();
    const row = screen.getByTestId("category-swipe-9");

    // Custom actions hang off an accessibility ELEMENT, so the row has to be one.
    // The collapse is the point: a list row should announce as "Work, 3 tasks" with
    // its actions in the rotor, not as two separate nodes with no actions at all.
    expect(row.props.accessible).toBe(true);
    expect(row.props.accessibilityActions).toEqual([
      { name: "Edit category", label: "Edit category" },
      { name: "Delete category", label: "Delete category" },
    ]);

    act(() =>
      row.props.onAccessibilityAction({
        nativeEvent: { actionName: "Edit category" },
      }),
    );

    expect(props.onUpdate).toHaveBeenCalledWith(
      "/hv/categories/9/edit/",
      "navigate",
      element,
      { verb: "get" },
    );
  });
});
