import { DOMParser } from "@instawork/xmldom";
import React from "react";
import { fireEvent, render } from "@testing-library/react-native";
import { Platform } from "react-native";
import { Registry } from "hyperview/src/services/components";
import { captureDraft, trackDraft } from "../src/realtime/drafts";
import TimePicker from "../src/components/TimePicker";

jest.mock("react-native-webview", () => ({ WebView: () => null }));
jest.mock("@react-native-community/datetimepicker", () => {
  const React = require("react");
  const { View } = require("react-native");
  return { __esModule: true, default: (props: object) => React.createElement(View, { ...props, testID: "native-time-picker" }) };
});

const HV = "https://hyperview.org/hyperview";
const APP = "https://hypertodo.app/components";
const stylesheets = { regular: { field: { minHeight: 48 }, "field-text": { color: "#161A35" } }, selected: {}, pressed: {}, focused: {}, pressedSelected: {} };
function fixture(value = "", disabled = false) {
  const doc = new DOMParser().parseFromString(`<view xmlns="${HV}" xmlns:app="${APP}"><form><date-field name="due_date" value="2026-10-20"/><app:time-picker accessibilityLabel="Due time" placeholder="Select due time" cancel-label="Cancel" done-label="Done" clear-label="Clear" field-style="field" field-text-style="field-text"${disabled ? ' disabled="true"' : ""}><text-field name="due_time" value="${value}" hide="true"/></app:time-picker></form></view>`, "application/xml") as Document;
  const element = doc.getElementsByTagNameNS(APP, "time-picker").item(0)!;
  const registry = new Registry([TimePicker]);
  const form = doc.getElementsByTagNameNS(HV, "form").item(0)!;
  const onUpdate = jest.fn((...args: any[]) => {
    const [, action, oldElement, options] = args;
    if (action === "swap") oldElement.parentNode!.replaceChild(options.newElement, oldElement);
  });
  return { element, form, registry, onUpdate, boundary: doc.documentElement };
}
function mount(value = "", disabled = false) {
  const data = fixture(value, disabled);
  const screen = render(<TimePicker element={data.element} onUpdate={data.onUpdate} options={{}} stylesheets={stylesheets as any} />);
  const posted = () => new URLSearchParams(data.registry.getFormData(data.form) as any);
  return { ...data, screen, posted };
}
const choose = (screen: ReturnType<typeof render>, hour: number, minute: number, type = "set") => {
  // Native timeZoneName="UTC" callbacks carry the selected wall clock as UTC fields.
  const selected = new Date(Date.UTC(2000, 0, 1, hour, minute));
  fireEvent(screen.getByTestId("native-time-picker"), "onChange", { type }, selected);
};

describe("native task time selection", () => {
  const originalPlatform = Platform.OS;
  afterEach(() => { Object.defineProperty(Platform, "OS", { value: originalPlatform }); });
  const platform = (os: "ios" | "android") => Object.defineProperty(Platform, "OS", { value: os });

  it("leaves a blank field and draft untouched when opened then cancelled on iOS", () => {
    platform("ios");
    const form = mount();
    const baseline = captureDraft(form.boundary, form.registry);
    expect(form.screen.getByRole("button", { name: "Due time" }).props.accessibilityValue).toMatchObject({ text: "Select due time" });
    expect(form.screen.queryByText("00:00")).toBeNull();
    fireEvent.press(form.screen.getByRole("button", { name: "Due time" }));
    expect(form.screen.getByTestId("native-time-picker").props.mode).toBe("time");
    expect(form.screen.getByTestId("native-time-picker").props.display).toBe("spinner");
    expect(form.screen.getByTestId("native-time-picker").props.locale).toBe("en-GB");
    expect(form.screen.getByTestId("native-time-picker").props.timeZoneName).toBe("UTC");
    expect(form.posted().get("due_time")).toBe("");
    choose(form.screen, 21, 45);
    fireEvent.press(form.screen.getByRole("button", { name: "Cancel" }));
    expect(form.posted().get("due_time")).toBe("");
    expect(trackDraft({ baseline, current: baseline, revision: 0, dirty: false }, captureDraft(form.boundary, form.registry)).dirty).toBe(false);
    expect(form.onUpdate).not.toHaveBeenCalled();
  });

  it("confirms a selected time as one serializable HH:MM value and a dirty draft", () => {
    platform("ios");
    const form = mount();
    const baseline = captureDraft(form.boundary, form.registry);
    fireEvent.press(form.screen.getByRole("button", { name: "Due time" }));
    choose(form.screen, 9, 5);
    expect(form.posted().get("due_time")).toBe("");
    fireEvent.press(form.screen.getByRole("button", { name: "Done" }));
    expect(form.posted().getAll("due_time")).toEqual(["09:05"]);
    expect(form.posted().get("due_date")).toBe("2026-10-20");
    expect(trackDraft({ baseline, current: baseline, revision: 0, dirty: false }, captureDraft(form.boundary, form.registry)).dirty).toBe(true);
    expect(form.onUpdate).toHaveBeenCalledTimes(1);
  });

  it("can confirm the default without moving wheels and preserves midnight", () => {
    platform("ios");
    const blank = mount();
    fireEvent.press(blank.screen.getByRole("button", { name: "Due time" }));
    fireEvent.press(blank.screen.getByRole("button", { name: "Done" }));
    expect(blank.posted().get("due_time")).toMatch(/^\d{2}:\d{2}$/);
    const midnight = mount("00:00");
    expect(midnight.posted().get("due_time")).toBe("00:00");
    fireEvent.press(midnight.screen.getByRole("button", { name: "Due time" }));
    expect(midnight.screen.getByTestId("native-time-picker").props.value.getUTCHours()).toBe(0);
    fireEvent.press(midnight.screen.getByRole("button", { name: "Cancel" }));
    expect(midnight.posted().get("due_time")).toBe("00:00");
  });

  it.each(["00:00", "14:30", "23:59"])("shows %s without AM/PM in text and accessibility", (value) => {
    platform("ios");
    const form = mount(value);
    expect(form.screen.getByText(value)).toBeTruthy();
    expect(form.screen.getByRole("button", { name: "Due time" }).props.accessibilityValue).toEqual({ text: value });
    expect(form.posted().get("due_time")).toBe(value);
  });

  it("clears only time and leaves the date in the form", () => {
    platform("ios");
    const form = mount("14:30");
    fireEvent.press(form.screen.getByRole("button", { name: "Clear" }));
    expect(form.posted().get("due_time")).toBe("");
    expect(form.posted().get("due_date")).toBe("2026-10-20");
  });

  it("commits Android set and ignores native dismissal", () => {
    platform("android");
    const form = mount("14:30");
    fireEvent.press(form.screen.getByRole("button", { name: "Due time" }));
    expect(form.screen.getByTestId("native-time-picker").props.mode).toBe("time");
    expect(form.screen.getByTestId("native-time-picker").props.is24Hour).toBe(true);
    choose(form.screen, 8, 7, "dismissed");
    expect(form.posted().get("due_time")).toBe("14:30");
    fireEvent.press(form.screen.getByRole("button", { name: "Due time" }));
    choose(form.screen, 0, 0);
    expect(form.posted().get("due_time")).toBe("00:00");
  });

  describe("spring DST gap with a deadline on another date", () => {
    const frozenInstant = new Date("2026-03-08T16:00:00Z");
    beforeEach(() => {
      jest.useFakeTimers();
      jest.setSystemTime(frozenInstant);
    });
    afterEach(() => {
      jest.useRealTimers();
    });

    it("shows and reconfirms 02:30 without silently normalizing it on iOS", () => {
      platform("ios");
      const form = mount("02:30");
      const baseline = captureDraft(form.boundary, form.registry);
      expect(form.screen.getByRole("button", { name: "Due time" }).props.accessibilityValue.text).toBe("02:30");
      fireEvent.press(form.screen.getByRole("button", { name: "Due time" }));
      const picker = form.screen.getByTestId("native-time-picker");
      expect(picker.props.timeZoneName).toBe("UTC");
      expect(picker.props.value.getUTCHours()).toBe(2);
      expect(picker.props.value.getUTCMinutes()).toBe(30);
      choose(form.screen, 3, 10);
      fireEvent.press(form.screen.getByRole("button", { name: "Cancel" }));
      expect(form.posted().get("due_time")).toBe("02:30");
      fireEvent.press(form.screen.getByRole("button", { name: "Due time" }));
      fireEvent.press(form.screen.getByRole("button", { name: "Done" }));
      expect(form.posted().get("due_time")).toBe("02:30");
      expect(form.onUpdate).not.toHaveBeenCalled();
      expect(trackDraft({ baseline, current: baseline, revision: 0, dirty: false }, captureDraft(form.boundary, form.registry)).dirty).toBe(false);

      const midnight = mount("00:00");
      fireEvent.press(midnight.screen.getByRole("button", { name: "Due time" }));
      expect(midnight.screen.getByTestId("native-time-picker").props.value.getUTCHours()).toBe(0);
      fireEvent.press(midnight.screen.getByRole("button", { name: "Done" }));
      expect(midnight.posted().get("due_time")).toBe("00:00");
      expect(midnight.onUpdate).not.toHaveBeenCalled();
    });

    it("keeps the local current clock as the blank default and accepts Android wall time", () => {
      platform("android");
      const blank = mount();
      fireEvent.press(blank.screen.getByRole("button", { name: "Due time" }));
      expect(blank.screen.getByTestId("native-time-picker").props.timeZoneName).toBe("UTC");
      const selected = blank.screen.getByTestId("native-time-picker").props.value;
      expect(selected.getTime()).toBe(Date.UTC(2000, 0, 1, frozenInstant.getHours(), frozenInstant.getMinutes()));
      choose(blank.screen, 2, 30, "dismissed");
      expect(blank.posted().get("due_time")).toBe("");
      fireEvent.press(blank.screen.getByRole("button", { name: "Due time" }));
      choose(blank.screen, 2, 30);
      expect(blank.posted().get("due_time")).toBe("02:30");
    });
  });

  it("does not offer editing or clearing while disabled", () => {
    platform("ios");
    const form = mount("12:10", true);
    expect(form.screen.getByRole("button", { name: "Due time" }).props.accessibilityValue.text).toBe("12:10");
    expect(form.screen.getByRole("button", { name: "Due time" }).props.accessibilityState.disabled).toBe(true);
    fireEvent.press(form.screen.getByRole("button", { name: "Due time" }));
    expect(form.screen.queryByTestId("native-time-picker")).toBeNull();
    expect(form.screen.queryByRole("button", { name: "Clear" })).toBeNull();
    expect(form.posted().get("due_time")).toBe("12:10");
  });

  it.each(["24:00", "12:60", "9:05", "not-a-time"])
    ("does not normalize an invalid stored value into a different posted time: %s", value => {
      platform("ios");
      const form = mount(value);
      fireEvent.press(form.screen.getByRole("button", { name: "Due time" }));
      expect(form.screen.getByTestId("native-time-picker").props.value).toBeInstanceOf(Date);
      fireEvent.press(form.screen.getByRole("button", { name: "Cancel" }));
      expect(form.posted().get("due_time")).toBe(value);
      expect(form.onUpdate).not.toHaveBeenCalled();
    });

  it("ignores a native callback without a selected date", () => {
    platform("ios");
    const form = mount("14:30");
    fireEvent.press(form.screen.getByRole("button", { name: "Due time" }));
    fireEvent(form.screen.getByTestId("native-time-picker"), "onChange", { type: "set" }, undefined);
    fireEvent.press(form.screen.getByRole("button", { name: "Done" }));
    expect(form.posted().get("due_time")).toBe("14:30");
    expect(form.onUpdate).not.toHaveBeenCalled();
  });

  it("keeps the value unchanged when the native selector is dismissed on iOS", () => {
    platform("ios");
    const form = mount("16:40");
    fireEvent.press(form.screen.getByRole("button", { name: "Due time" }));
    choose(form.screen, 3, 10, "dismissed");
    expect(form.screen.queryByTestId("native-time-picker")).toBeNull();
    expect(form.posted().get("due_time")).toBe("16:40");
  });

  it("treats editable=false as disabled without changing the hidden form field", () => {
    platform("ios");
    const data = fixture("18:15");
    data.element.setAttribute("editable", "false");
    const screen = render(<TimePicker element={data.element} onUpdate={data.onUpdate} options={{}} stylesheets={stylesheets as any} />);
    expect(screen.getByRole("button", { name: "Due time" }).props.accessibilityState.disabled).toBe(true);
    fireEvent.press(screen.getByRole("button", { name: "Due time" }));
    expect(screen.queryByTestId("native-time-picker")).toBeNull();
    expect(new URLSearchParams(data.registry.getFormData(data.form) as any).get("due_time")).toBe("18:15");
  });

  it("does not fabricate a hidden field when malformed markup has none", () => {
    platform("ios");
    const data = fixture();
    data.element.removeChild(data.element.getElementsByTagNameNS(HV, "text-field").item(0)!);
    const screen = render(<TimePicker element={data.element} onUpdate={data.onUpdate} options={{}} stylesheets={stylesheets as any} />);
    expect(screen.getByRole("button", { name: "Due time" }).props.accessibilityValue.text).toBe("Select due time");
    fireEvent.press(screen.getByRole("button", { name: "Due time" }));
    choose(screen, 7, 30);
    fireEvent.press(screen.getByRole("button", { name: "Done" }));
    expect(data.onUpdate).not.toHaveBeenCalled();
    expect(new URLSearchParams(data.registry.getFormData(data.form) as any).get("due_time")).toBeNull();
  });
});
