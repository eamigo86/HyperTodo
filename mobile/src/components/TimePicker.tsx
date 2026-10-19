import DateTimePicker, { type DateTimePickerEvent } from "@react-native-community/datetimepicker";
import type { HvComponentProps } from "hyperview";
import { createStyleProp } from "hyperview";
import React, { useState } from "react";
import { Modal, Platform, Pressable, StyleSheet, Text, View } from "react-native";
import { THEME_TOKENS, useThemeName } from "../theme";

const COMPONENT_NAMESPACE = "https://hypertodo.app/components";
const HYPERVIEW_NAMESPACE = "https://hyperview.org/hyperview";

function timeField(element: Element): Element | null {
  return element.getElementsByTagNameNS(HYPERVIEW_NAMESPACE, "text-field").item(0);
}

function timeDate(value: string): Date | null {
  const match = /^(\d{2}):(\d{2})$/.exec(value);
  if (!match || Number(match[1]) > 23 || Number(match[2]) > 59) return null;
  // UTC is an internal time-only container, never the task deadline timezone.
  return new Date(Date.UTC(2000, 0, 1, Number(match[1]), Number(match[2])));
}

function currentTimeDate(): Date {
  const now = new Date();
  return new Date(Date.UTC(2000, 0, 1, now.getHours(), now.getMinutes()));
}

function serializeTime(value: Date): string {
  return `${String(value.getUTCHours()).padStart(2, "0")}:${String(value.getUTCMinutes()).padStart(2, "0")}`;
}

/** A native selector; the child Hyperview text-field remains the sole form value. */
function TimePickerComponent({ element, onUpdate, options, stylesheets }: HvComponentProps): React.JSX.Element {
  const themeName = useThemeName();
  const theme = THEME_TOKENS[themeName];
  const [open, setOpen] = useState(false);
  const [pending, setPending] = useState<Date | null>(null);
  const field = timeField(element);
  const value = field?.getAttribute("value") ?? "";
  const disabled = element.getAttribute("disabled") === "true" || element.getAttribute("editable") === "false";
  const label = element.getAttribute("accessibilityLabel") ?? "Time";
  const textStyle = createStyleProp(element, stylesheets, { ...options, styleAttr: "field-text-style" });
  const modalStyle = createStyleProp(element, stylesheets, { ...options, styleAttr: "modal-style" });
  const actionStyle = createStyleProp(element, stylesheets, { ...options, styleAttr: "modal-text-style" });

  const commit = (next: string) => {
    const current = timeField(element);
    if (!current || current.getAttribute("value") === next) return;
    const replacement = current.cloneNode(true) as Element;
    replacement.setAttribute("value", next);
    onUpdate(null, "swap", current, { newElement: replacement });
  };
  const openPicker = () => {
    if (disabled) return;
    setPending(timeDate(value) ?? currentTimeDate());
    setOpen(true);
  };
  const cancel = () => { setOpen(false); setPending(null); };
  const confirm = () => {
    if (pending) commit(serializeTime(pending));
    cancel();
  };
  const onNativeChange = (event: DateTimePickerEvent, selected?: Date) => {
    if (event.type === "dismissed") { cancel(); return; }
    if (!selected) return;
    if (Platform.OS === "ios") setPending(selected);
    else { commit(serializeTime(selected)); cancel(); }
  };
  const displayed = timeDate(value)?.toLocaleTimeString(undefined, { hour: "numeric", minute: "2-digit", timeZone: "UTC" }) ?? value;

  return (
    <View style={styles.row}>
      <Pressable
        accessibilityLabel={label}
        accessibilityRole="button"
        accessibilityValue={{ text: value ? displayed : element.getAttribute("placeholder") ?? "" }}
        accessibilityState={{ disabled }}
        disabled={disabled}
        onPress={openPicker}
        style={({ pressed }) => [
          styles.field,
          ...createStyleProp(element, stylesheets, { ...options, styleAttr: "field-style", pressed, focused: open }),
        ]}
      >
        <Text style={[...textStyle, !value && { color: element.getAttribute("placeholderTextColor") ?? theme.ink_muted_alt }]}>
          {value ? displayed : element.getAttribute("placeholder") ?? ""}
        </Text>
      </Pressable>
      {!!value && !disabled && (
        <Pressable accessibilityLabel={element.getAttribute("clear-label") ?? "Clear"} accessibilityRole="button" onPress={() => commit("")} style={styles.clear}>
          <Text style={[...actionStyle, { color: theme.brand_ink }]}>{element.getAttribute("clear-label") ?? "Clear"}</Text>
        </Pressable>
      )}
      {open && pending && Platform.OS === "ios" && (
        <Modal animationType="slide" transparent visible onRequestClose={cancel}>
          <View style={[styles.overlay, { backgroundColor: theme.scrim + "59" }]}>
            <View style={[styles.sheet, { backgroundColor: theme.surface }, ...modalStyle]}>
              <View style={styles.actions}>
                <Pressable accessibilityRole="button" onPress={cancel} style={styles.action}>
                  <Text style={[...actionStyle, { color: theme.brand_ink }]}>{element.getAttribute("cancel-label") ?? "Cancel"}</Text>
                </Pressable>
                <Pressable accessibilityRole="button" onPress={confirm} style={styles.action}>
                  <Text style={[...actionStyle, { color: theme.brand_ink }]}>{element.getAttribute("done-label") ?? "Done"}</Text>
                </Pressable>
              </View>
              <DateTimePicker display="spinner" mode="time" onChange={onNativeChange} themeVariant={themeName} timeZoneName="UTC" value={pending} />
            </View>
          </View>
        </Modal>
      )}
      {open && pending && Platform.OS !== "ios" && (
        <DateTimePicker display="default" mode="time" onChange={onNativeChange} timeZoneName="UTC" value={pending} />
      )}
    </View>
  );
}

const styles = StyleSheet.create({
  row: { alignItems: "center", flexDirection: "row" },
  field: { flex: 1, justifyContent: "center" },
  clear: { justifyContent: "center", minHeight: 48, paddingHorizontal: 12 },
  overlay: { flex: 1, justifyContent: "flex-end" },
  sheet: { paddingBottom: 20 },
  actions: { flexDirection: "row", justifyContent: "space-between" },
  action: { minHeight: 48, justifyContent: "center" },
});

const TimePicker = Object.assign(TimePickerComponent, {
  localName: "time-picker",
  namespaceURI: COMPONENT_NAMESPACE,
});

export default TimePicker;
