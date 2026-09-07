import type { HvComponentProps } from "hyperview";
import { createStyleProp, renderChildren } from "hyperview";
import React, { useCallback, useEffect, useMemo, useRef } from "react";
import {
  Animated,
  Easing,
  Pressable,
  StyleSheet,
  Text,
  useWindowDimensions,
  View,
} from "react-native";

import { THEME_TOKENS, useThemeName, type ThemeTokens } from "../theme";

const COMPONENT_NAMESPACE = "https://hypertodo.app/components";
const DEFAULT_DURATION = 220;
const DEFAULT_PANEL_WIDTH = 286;

function parseDuration(element: Element): number {
  const value = Number.parseInt(element.getAttribute("animation-duration") ?? "", 10);
  return Number.isFinite(value) && value >= 0 ? value : DEFAULT_DURATION;
}

/** Resolve the server's `panel-width` percentage against the current window.
 *
 * A percentage, not points: the app is portrait-locked and phone-only
 * (app.config.ts:61,85), so the shipped 286 is 89% of a 320pt screen and only 67%
 * of a 430pt one. No clamp for the same reason -- 80% of a small screen is
 * correctly small. Anything absent or unparseable keeps the shipped width.
 */
function parsePanelWidth(element: Element, windowWidth: number): number {
  const percent = Number.parseFloat(element.getAttribute("panel-width") ?? "");
  return Number.isFinite(percent) && percent > 0
    ? Math.round((windowWidth * percent) / 100)
    : DEFAULT_PANEL_WIDTH;
}

function AnimatedSideMenuComponent({
  element,
  onUpdate,
  options,
  stylesheets,
}: HvComponentProps): React.JSX.Element {
  const styles = STYLES[useThemeName()];
  const duration = useMemo(() => parseDuration(element), [element]);
  const { width: windowWidth } = useWindowDimensions();
  const panelWidth = useMemo(
    () => parsePanelWidth(element, windowWidth),
    [element, windowWidth],
  );
  const translateX = useRef(new Animated.Value(-panelWidth)).current;
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
        toValue: -panelWidth,
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
  }, [duration, element, onUpdate, panelWidth, scrimOpacity, translateX]);

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
      <Animated.View
        style={[styles.panel, { transform: [{ translateX }], width: panelWidth }]}
        testID="side-menu-panel"
      >
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

const makeStyles = (t: ThemeTokens) => StyleSheet.create({
  panel: {
    height: "100%",
    zIndex: 1,
  },
  closeButton: {
    alignItems: "center",
    backgroundColor: t.chip,
    borderRadius: 22,
    height: 44,
    justifyContent: "center",
    position: "absolute",
    right: 20,
    top: 20,
    width: 44,
  },
  closeText: {
    color: t.ink_label,
    fontSize: 26,
    lineHeight: 28,
  },
  scrim: {
    // Drawn at 0.22 opacity. Dark's scrim is pure black because #161A35 barely
    // dims a canvas that is already nearly black.
    backgroundColor: t.scrim,
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

const STYLES = { light: makeStyles(THEME_TOKENS.light), dark: makeStyles(THEME_TOKENS.dark) };

export default AnimatedSideMenu;
