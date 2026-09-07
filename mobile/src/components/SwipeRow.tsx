import type { HvComponentProps } from "hyperview";
import { createStyleProp } from "hyperview";
import { renderChildNodes } from "hyperview/src/services/render";
import React, { useCallback, useMemo, useRef, useState } from "react";
import {
  Alert,
  Animated,
  Easing,
  PanResponder,
  Pressable,
  StyleSheet,
  Text,
  View,
} from "react-native";

const COMPONENT_NAMESPACE = "https://hypertodo.app/components";
const ACTION_LOCAL_NAME = "swipe-action";
// One width for every action. The old triad used 68/96/70 only because "Complete"
// is the longest label the tasks screen ships; 88 fits it at 13/700, keeps the tray
// arithmetic a single multiplication, and makes every target identical.
const ACTION_WIDTH = 88;
const SWIPE_THRESHOLD = 44;
const ANIMATION_DURATION = 160;

type UpdateAction = "navigate" | "replace";
type UpdateVerb = "get" | "post";

type SwipeAction = {
  href: string;
  action: UpdateAction;
  verb: UpdateVerb;
  label: string;
  accessibilityLabel: string;
  tone: keyof typeof TONES;
  confirmTitle: string | null;
  confirmBody: string;
  confirmLabel: string;
};

const TONES = {
  primary: "#1F6FD1",
  positive: "#1C7C57",
  danger: "#B42318",
} as const;

/** Split the row's children into the actions it declares and the content it draws.
 *
 * The actions are DATA, not markup: `swipe-action` is deliberately unregistered, so
 * an old binary skips it with an info log (services/render/index.tsx:71-85) and this
 * one filters it out of the content instead of rendering it.
 */
function readActions(element: Element): {
  actions: SwipeAction[];
  content: ChildNode[];
} {
  const actions: SwipeAction[] = [];
  const content: ChildNode[] = [];

  for (const child of Array.from(element.childNodes ?? [])) {
    const node = child as unknown as Element;
    if (
      node.namespaceURI !== COMPONENT_NAMESPACE ||
      node.localName !== ACTION_LOCAL_NAME
    ) {
      content.push(child);
      continue;
    }
    const href = node.getAttribute("href");
    const label = node.getAttribute("label");
    if (!href || !label) {
      continue;
    }
    const tone = node.getAttribute("tone") ?? "";
    actions.push({
      accessibilityLabel: node.getAttribute("a11y-label") || label,
      action: node.getAttribute("action") === "replace" ? "replace" : "navigate",
      confirmBody: node.getAttribute("confirm-body") ?? "",
      confirmLabel: node.getAttribute("confirm-label") || label,
      confirmTitle: node.getAttribute("confirm-title"),
      href,
      label,
      tone: tone in TONES ? (tone as keyof typeof TONES) : "primary",
      verb: node.getAttribute("verb") === "post" ? "post" : "get",
    });
  }

  return { actions, content };
}

function SwipeRowComponent({
  element,
  onUpdate,
  options,
  stylesheets,
}: HvComponentProps): React.JSX.Element {
  const { actions, content } = useMemo(() => readActions(element), [element]);
  const trayWidth = ACTION_WIDTH * actions.length;
  const rootStyle = createStyleProp(element, stylesheets, options);
  const children = renderChildNodes(content, stylesheets, onUpdate, options);
  const [actionsOpen, setActionsOpen] = useState(false);
  const actionsTranslateX = useRef(new Animated.Value(trayWidth)).current;

  const animateActions = useCallback(
    (open: boolean): void => {
      setActionsOpen(open);
      Animated.timing(actionsTranslateX, {
        duration: ANIMATION_DURATION,
        easing: Easing.out(Easing.cubic),
        toValue: open ? 0 : trayWidth,
        useNativeDriver: true,
      }).start();
    },
    [actionsTranslateX, trayWidth],
  );

  const dispatch = useCallback(
    (item: SwipeAction): void => {
      const targetId = item.action === "replace" ? element.getAttribute("id") : null;
      animateActions(false);
      onUpdate(item.href, item.action, element, {
        ...(targetId ? { targetId } : {}),
        verb: item.verb,
      });
    },
    [animateActions, element, onUpdate],
  );

  const run = useCallback(
    (item: SwipeAction): void => {
      if (!item.confirmTitle) {
        dispatch(item);
        return;
      }
      Alert.alert(item.confirmTitle, item.confirmBody, [
        { text: "Cancel", style: "cancel" },
        {
          text: item.confirmLabel,
          style: "destructive",
          onPress: () => dispatch(item),
        },
      ]);
    },
    [dispatch],
  );

  const panResponder = useMemo(
    () =>
      PanResponder.create({
        onMoveShouldSetPanResponder: (_event, gesture) =>
          Math.abs(gesture.dx) > 8 && Math.abs(gesture.dx) > Math.abs(gesture.dy),
        onMoveShouldSetPanResponderCapture: (_event, gesture) =>
          Math.abs(gesture.dx) > 8 && Math.abs(gesture.dx) > Math.abs(gesture.dy),
        onPanResponderGrant: () => actionsTranslateX.stopAnimation(),
        onPanResponderMove: (_event, gesture) => {
          const origin = actionsOpen ? 0 : trayWidth;
          const nextPosition = Math.max(0, Math.min(trayWidth, origin + gesture.dx));
          actionsTranslateX.setValue(nextPosition);
        },
        onPanResponderRelease: (_event, gesture) => {
          const shouldOpen = actionsOpen
            ? gesture.dx <= SWIPE_THRESHOLD
            : gesture.dx < -SWIPE_THRESHOLD;
          animateActions(shouldOpen);
        },
        onPanResponderTerminate: () => animateActions(actionsOpen),
        onPanResponderTerminationRequest: () => false,
      }),
    [actionsOpen, actionsTranslateX, animateActions, trayWidth],
  );

  return (
    <View
      // An accessibility ELEMENT, because custom actions hang off one: without this
      // the tray below is hidden and the actions reach nobody. The row collapsing
      // into a single announcement is the right shape for a list row anyway.
      accessible
      accessibilityActions={actions.map((item) => ({
        name: item.accessibilityLabel,
        label: item.accessibilityLabel,
      }))}
      onAccessibilityAction={(event) => {
        const item = actions.find(
          (candidate) => candidate.accessibilityLabel === event.nativeEvent.actionName,
        );
        if (item) {
          run(item);
        }
      }}
      style={[rootStyle, styles.root]}
      testID={element.getAttribute("id") ?? undefined}
      {...panResponder.panHandlers}
    >
      <View
        style={[styles.content, actionsOpen && { paddingRight: trayWidth }]}
        testID="swipe-row-content"
      >
        {children}
      </View>
      {/* `overflow: hidden` does not prune the accessibility tree, so a tray that is
          merely translated off-screen still announces every button it holds. It is
          hidden while closed and the row exposes the same list as custom actions,
          which is the only way a screen reader reaches them without the gesture. */}
      <Animated.View
        accessibilityElementsHidden={!actionsOpen}
        importantForAccessibility={actionsOpen ? "auto" : "no-hide-descendants"}
        style={[
          styles.actions,
          { transform: [{ translateX: actionsTranslateX }], width: trayWidth },
        ]}
        testID="swipe-row-actions"
      >
        {actions.map((item) => (
          <Pressable
            accessibilityLabel={item.accessibilityLabel}
            accessibilityRole="button"
            key={item.href}
            onPress={() => run(item)}
            style={[styles.action, { backgroundColor: TONES[item.tone] }, styles.width]}
          >
            <Text numberOfLines={1} style={styles.actionText}>
              {item.label}
            </Text>
          </Pressable>
        ))}
      </Animated.View>
    </View>
  );
}

const SwipeRow = Object.assign(SwipeRowComponent, {
  localName: "swipe-row",
  namespaceURI: COMPONENT_NAMESPACE,
});

const styles = StyleSheet.create({
  root: {
    overflow: "hidden",
    position: "relative",
  },
  content: {
    position: "relative",
  },
  actions: {
    bottom: 0,
    flexDirection: "row",
    position: "absolute",
    right: 0,
    top: 0,
  },
  action: {
    alignItems: "center",
    justifyContent: "center",
    paddingHorizontal: 8,
  },
  width: {
    width: ACTION_WIDTH,
  },
  // White 13/700 is normal text and owes 4.5:1. The shipped fills gave it 3.34 on
  // #278CFF and 3.36 on #2F9E73; the tones above read 4.94 / 5.16 / 6.57.
  actionText: {
    color: "#FFFFFF",
    fontSize: 13,
    fontWeight: "700",
  },
});

export default SwipeRow;
