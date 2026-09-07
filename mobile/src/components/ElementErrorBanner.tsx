import type { ElementErrorComponentProps } from "hyperview/src/types";
import React from "react";
import { Pressable, StyleSheet, Text, View } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";

import { FAILURE_COPY, classifyFailure } from "../feedback/failure";
import { THEME_TOKENS, useThemeName, type ThemeTokens } from "../theme";

/**
 * Fragment-level failure banner. Hyperview renders `elementErrorComponent` as a bare
 * sibling above the screen content with no flex parent (hv-screen/index.tsx:79-85), so it
 * has to position itself absolutely or it pushes the whole screen down.
 *
 * Nothing derived from `error` is ever rendered: only the classified, non-technical copy.
 */
export default function ElementErrorBanner({
  error,
  onPressClose,
  onPressReload,
}: ElementErrorComponentProps): React.JSX.Element {
  const copy = FAILURE_COPY[classifyFailure(error)];
  const styles = STYLES[useThemeName()];
  return (
    <SafeAreaView
      edges={["top"]}
      pointerEvents="box-none"
      style={styles.host}
      testID="element-error-banner"
    >
      <View accessibilityLiveRegion="polite" style={styles.card} testID="element-error-card">
        <Text style={styles.title}>{copy.title}</Text>
        <Text style={styles.body}>{copy.body}</Text>
        <View style={styles.actions}>
          <Pressable
            accessibilityRole="button"
            hitSlop={8}
            onPress={onPressReload}
            style={styles.retry}
          >
            <Text style={styles.retryText}>{copy.action}</Text>
          </Pressable>
          <Pressable
            accessibilityRole="button"
            hitSlop={8}
            onPress={onPressClose}
            style={styles.dismiss}
          >
            <Text style={styles.dismissText}>Dismiss</Text>
          </Pressable>
        </View>
      </View>
    </SafeAreaView>
  );
}

const makeStyles = (t: ThemeTokens) => StyleSheet.create({
  host: {
    backgroundColor: "transparent",
    left: 0,
    position: "absolute",
    right: 0,
    top: 0,
    zIndex: 99,
  },
  // shadow* is iOS-only in React Native. Without `elevation` this card had NO
  // visible edge at all on Android -- #1A1D26 on the #0F1118 canvas is 1.12:1, and
  // light is worse at 1.06:1 -- so the user could not tell where the floating
  // banner ended and the screen behind it began.
  card: {
    backgroundColor: t.surface,
    borderRadius: 24,
    elevation: 8,
    marginHorizontal: 16,
    marginTop: 12,
    padding: 20,
    shadowColor: t.scrim,
    shadowOffset: { height: 6, width: 0 },
    shadowOpacity: 0.16,
    shadowRadius: 14,
  },
  title: {
    color: t.ink,
    fontSize: 19,
    fontWeight: "700",
  },
  body: {
    color: t.ink_muted_alt,
    fontSize: 15,
    lineHeight: 22,
    marginTop: 8,
  },
  actions: {
    alignItems: "center",
    flexDirection: "row",
    marginTop: 16,
  },
  retry: {
    alignItems: "center",
    backgroundColor: t.brand,
    borderRadius: 16,
    justifyContent: "center",
    minHeight: 44,
    paddingHorizontal: 20,
  },
  // White on light's #278CFF is 3.34:1, so it only clears WCAG large-text contrast
  // at 19/700. Dark's #1F6FD1 improves that to 4.94:1.
  retryText: {
    color: t.on_brand,
    fontSize: 19,
    fontWeight: "700",
  },
  dismiss: {
    alignItems: "center",
    justifyContent: "center",
    minHeight: 44,
    paddingHorizontal: 16,
  },
  dismissText: {
    color: t.ink,
    fontSize: 16,
    fontWeight: "700",
  },
});

const STYLES = { light: makeStyles(THEME_TOKENS.light), dark: makeStyles(THEME_TOKENS.dark) };
