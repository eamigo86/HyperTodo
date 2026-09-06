import type { HvComponentProps } from "hyperview";
import { createStyleProp, renderChildren } from "hyperview";
import React, { useCallback, useEffect, useMemo, useRef } from "react";
import { Animated, Easing, Pressable, StyleSheet, Text, View } from "react-native";

const COMPONENT_NAMESPACE = "https://hypertodo.app/components";
const DEFAULT_DURATION = 220;
const PANEL_WIDTH = 286;

function parseDuration(element: Element): number {
  const value = Number.parseInt(element.getAttribute("animation-duration") ?? "", 10);
  return Number.isFinite(value) && value >= 0 ? value : DEFAULT_DURATION;
}

function AnimatedSideMenuComponent({
  element,
  onUpdate,
  options,
  stylesheets,
}: HvComponentProps): React.JSX.Element {
  const duration = useMemo(() => parseDuration(element), [element]);
  const translateX = useRef(new Animated.Value(-PANEL_WIDTH)).current;
  const scrimOpacity = useRef(new Animated.Value(0)).current;
  const dismissing = useRef(false);
  const closeTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    Animated.parallel([
      Animated.timing(translateX, {
        duration,
        easing: Easing.out(Easing.cubic),
        toValue: 0,
        useNativeDriver: true,
      }),
      Animated.timing(scrimOpacity, {
        duration,
        easing: Easing.out(Easing.cubic),
        toValue: 0.22,
        useNativeDriver: true,
      }),
    ]).start();

    return () => {
      if (closeTimer.current !== null) {
        clearTimeout(closeTimer.current);
      }
    };
  }, [duration, scrimOpacity, translateX]);

  const dismiss = useCallback(() => {
    if (dismissing.current) {
      return;
    }
    dismissing.current = true;

    Animated.parallel([
      Animated.timing(translateX, {
        duration,
        easing: Easing.in(Easing.cubic),
        toValue: -PANEL_WIDTH,
        useNativeDriver: true,
      }),
      Animated.timing(scrimOpacity, {
        duration,
        easing: Easing.in(Easing.cubic),
        toValue: 0,
        useNativeDriver: true,
      }),
    ]).start();

    closeTimer.current = setTimeout(() => {
      const href = element.getAttribute("close-href") ?? "/hv/menu/close/";
      const targetId = element.getAttribute("id") ?? "side-menu-host";
      onUpdate(href, "replace", element, { targetId, verb: "get" });
    }, duration);
  }, [duration, element, onUpdate, scrimOpacity, translateX]);

  const rootStyle = createStyleProp(element, stylesheets, options);
  const children = renderChildren(element, stylesheets, onUpdate, options);

  return (
    <View style={rootStyle} testID={element.getAttribute("id") ?? undefined}>
      <Animated.View
        style={[styles.scrim, { opacity: scrimOpacity }]}
        testID="side-menu-backdrop"
      >
        <Pressable
          accessibilityLabel="Close menu overlay"
          onPress={dismiss}
          style={styles.scrimPressable}
          testID="side-menu-scrim"
        />
      </Animated.View>
      <Animated.View style={[styles.panel, { transform: [{ translateX }] }]}>
        {children}
        <Pressable
          accessibilityLabel="Close menu"
          accessibilityRole="button"
          onPress={dismiss}
          style={styles.closeButton}
        >
          <Text style={styles.closeText}>×</Text>
        </Pressable>
      </Animated.View>
    </View>
  );
}

const AnimatedSideMenu = Object.assign(AnimatedSideMenuComponent, {
  localName: "side-menu",
  namespaceURI: COMPONENT_NAMESPACE,
});

const styles = StyleSheet.create({
  panel: {
    height: "100%",
    width: PANEL_WIDTH,
    zIndex: 1,
  },
  closeButton: {
    alignItems: "center",
    backgroundColor: "#EEF2FC",
    borderRadius: 22,
    height: 44,
    justifyContent: "center",
    position: "absolute",
    right: 20,
    top: 20,
    width: 44,
  },
  closeText: {
    color: "#4C526B",
    fontSize: 26,
    lineHeight: 28,
  },
  scrim: {
    backgroundColor: "#161A35",
    bottom: 0,
    left: 0,
    position: "absolute",
    right: 0,
    top: 0,
  },
  scrimPressable: {
    flex: 1,
  },
});

export default AnimatedSideMenu;
