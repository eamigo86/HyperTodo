import React from "react";
import { act, fireEvent, render } from "@testing-library/react-native";
import { StyleSheet } from "react-native";

import RealtimeNotice from "../src/components/RealtimeNotice";
import { createThemeStore, THEME_TOKENS, ThemeProvider, type ThemeName } from "../src/theme";

const message = "Hay cambios nuevos. Tu borrador sigue acá.";
const actionLabel = "Revisar cambios";
const dismissLabel = "Cerrar aviso de cambios";

function mount(theme: ThemeName = "light", extra: Partial<React.ComponentProps<typeof RealtimeNotice>> = {}) {
  const onAction = jest.fn();
  const onDismiss = jest.fn();
  const store = createThemeStore({ read: () => theme, write: jest.fn() });
  const screen = render(
    <ThemeProvider store={store}>
      <RealtimeNotice {...{ message, actionLabel, dismissLabel, onAction, onDismiss }} {...extra} />
    </ThemeProvider>,
  );
  return { ...screen, store, onAction, onDismiss };
}

const luminance = (hex: string) => [1, 3, 5]
  .map(index => parseInt(hex.slice(index, index + 2), 16) / 255)
  .map(value => value <= 0.04045 ? value / 12.92 : ((value + 0.055) / 1.055) ** 2.4)
  .reduce((sum, value, index) => sum + value * [0.2126, 0.7152, 0.0722][index], 0);
const contrast = (a: string, b: string) => {
  const values = [luminance(a), luminance(b)].sort((x, y) => y - x);
  return (values[0] + 0.05) / (values[1] + 0.05);
};

describe("RealtimeNotice presentation", () => {
  it("announces only the message politely and exposes separately named controls", () => {
    const screen = mount();
    const notice = screen.getByRole("alert");
    expect(notice.props.children).toBe(message);
    expect(notice.props.accessibilityLiveRegion).toBe("polite");
    expect(notice.props.accessibilityLabel).toBeUndefined();
    expect(screen.getAllByRole("button")).toHaveLength(2);
    expect(screen.getByRole("button", { name: actionLabel })).toBeTruthy();
    expect(screen.getByRole("button", { name: dismissLabel })).toBeTruthy();
  });

  it("delegates action and dismissal independently without hiding itself or acknowledging data", () => {
    const screen = mount();
    fireEvent.press(screen.getByRole("button", { name: actionLabel }));
    expect(screen.onAction).toHaveBeenCalledTimes(1);
    expect(screen.onDismiss).not.toHaveBeenCalled();
    fireEvent.press(screen.getByRole("button", { name: dismissLabel }));
    expect(screen.onDismiss).toHaveBeenCalledTimes(1);
    expect(screen.onAction).toHaveBeenCalledTimes(1);
    expect(screen.getByText(message)).toBeTruthy();
  });

  it("blocks a pending action while leaving dismissal available", () => {
    const screen = mount("light", { pending: true });
    const action = screen.getByRole("button", { name: actionLabel });
    expect(action.props.accessibilityState).toEqual(expect.objectContaining({ disabled: true, busy: true }));
    fireEvent.press(action);
    expect(screen.onAction).not.toHaveBeenCalled();
    fireEvent.press(screen.getByRole("button", { name: dismissLabel }));
    expect(screen.onDismiss).toHaveBeenCalledTimes(1);
  });

  it.each([
    { actionLabel: undefined },
    { onAction: undefined },
    { actionLabel: undefined, onAction: undefined },
    { actionLabel: "" },
  ])("keeps informational notices dismissible without an incomplete action: %j", extra => {
    const screen = mount("light", extra);
    expect(screen.getAllByRole("button")).toHaveLength(1);
    fireEvent.press(screen.getByRole("button", { name: dismissLabel }));
    expect(screen.onDismiss).toHaveBeenCalledTimes(1);
    expect(screen.onAction).not.toHaveBeenCalled();
  });

  it("keeps long localized text intact, scalable and free to wrap", () => {
    const longMessage = "Tu borrador conserva todos los cambios mientras decidís cómo revisar la actualización. ".repeat(4);
    const longAction = "Revisar los cambios remotos sin perder de vista mi borrador";
    const screen = mount("light", { message: longMessage, actionLabel: longAction });
    for (const text of [screen.getByText(longMessage), screen.getByText(longAction)]) {
      expect(text.props.allowFontScaling).toBe(true);
      expect(text.props.numberOfLines).toBeUndefined();
      expect(text.props.maxFontSizeMultiplier).toBeUndefined();
      expect(text.props.adjustsFontSizeToFit).not.toBe(true);
      expect(StyleSheet.flatten(text.props.style).flexShrink).toBe(1);
    }
    const card = StyleSheet.flatten(screen.getByTestId("realtime-notice").props.style);
    expect(card.height).toBeUndefined();
    expect(card.maxHeight).toBeUndefined();
    for (const button of screen.getAllByRole("button")) {
      const style = StyleSheet.flatten(button.props.style);
      expect(style.minHeight).toBeGreaterThanOrEqual(44);
      expect(style.minWidth).toBeGreaterThanOrEqual(44);
    }
  });

  it.each(["light", "dark"] as const)("uses the %s soft palette with readable text and a brand action", theme => {
    const screen = mount(theme);
    const tokens = THEME_TOKENS[theme];
    const card = StyleSheet.flatten(screen.getByTestId("realtime-notice").props.style);
    const body = StyleSheet.flatten(screen.getByText(message).props.style);
    const action = StyleSheet.flatten(screen.getByRole("button", { name: actionLabel }).props.style);
    const label = StyleSheet.flatten(screen.getByText(actionLabel).props.style);
    const close = StyleSheet.flatten(screen.getByText("×").props.style);
    expect(card.backgroundColor).toBe(tokens.chip);
    expect(card.borderRadius).toBeGreaterThanOrEqual(16);
    expect(card.borderWidth ?? 0).toBe(0);
    expect(card.elevation ?? 0).toBe(0);
    expect(body.color).toBe(tokens.ink);
    expect(contrast(body.color, card.backgroundColor)).toBeGreaterThanOrEqual(4.5);
    expect(contrast(close.color, card.backgroundColor)).toBeGreaterThanOrEqual(4.5);
    expect(action.backgroundColor).toBe(tokens.brand);
    expect(label.color).toBe(tokens.on_brand);
    expect(label.fontSize).toBeGreaterThanOrEqual(19);
    expect(Number(label.fontWeight)).toBeGreaterThanOrEqual(700);
    expect(contrast(label.color, action.backgroundColor)).toBeGreaterThanOrEqual(3);
  });

  it("updates the same notice when the containing theme changes", () => {
    const screen = mount("light");
    act(() => screen.store.publish("dark"));
    expect(StyleSheet.flatten(screen.getByTestId("realtime-notice").props.style).backgroundColor)
      .toBe(THEME_TOKENS.dark.chip);
    expect(screen.getByText(message)).toBeTruthy();
    expect(screen.onAction).not.toHaveBeenCalled();
    expect(screen.onDismiss).not.toHaveBeenCalled();
  });
});
