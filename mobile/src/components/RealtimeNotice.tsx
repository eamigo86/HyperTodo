import React from "react";
import { ActivityIndicator, Pressable, StyleSheet, Text, View } from "react-native";

import { THEME_TOKENS, useThemeName, type ThemeTokens } from "../theme";

export type RealtimeNoticeProps = {
  message: string;
  actionLabel?: string;
  onAction?: () => void;
  dismissLabel: string;
  onDismiss: () => void;
  pending?: boolean;
};

/** Presentation only: the caller owns draft safety, confirmation and dismissal scope. */
export default function RealtimeNotice({
  message,
  actionLabel,
  onAction,
  dismissLabel,
  onDismiss,
  pending = false,
}: RealtimeNoticeProps): React.JSX.Element {
  const theme = useThemeName();
  const styles = STYLES[theme];
  return (
    <View style={styles.card} testID="realtime-notice">
      <View style={styles.header}>
        <Text
          accessibilityLiveRegion="polite"
          accessibilityRole="alert"
          allowFontScaling
          style={styles.message}
        >
          {message}
        </Text>
        <Pressable
          accessibilityLabel={dismissLabel}
          accessibilityRole="button"
          onPress={onDismiss}
          style={({ pressed }) => [styles.dismiss, pressed && styles.pressed]}
        >
          <Text accessible={false} importantForAccessibility="no" style={styles.dismissText}>×</Text>
        </Pressable>
      </View>
      {actionLabel && onAction ? (
        <Pressable
          accessibilityRole="button"
          accessibilityState={{ disabled: pending, busy: pending }}
          disabled={pending}
          onPress={onAction}
          style={({ pressed }) => [styles.action, (pending || pressed) && styles.pressed]}
        >
          {pending ? (
            <ActivityIndicator
              accessible={false}
              importantForAccessibility="no-hide-descendants"
              color={THEME_TOKENS[theme].on_brand}
              size="small"
              style={styles.progress}
            />
          ) : null}
          <Text allowFontScaling style={styles.actionText}>{actionLabel}</Text>
        </Pressable>
      ) : null}
    </View>
  );
}

const makeStyles = (tokens: ThemeTokens) => StyleSheet.create({
  card: {
    backgroundColor: tokens.chip,
    borderRadius: 20,
    marginHorizontal: 16,
    marginVertical: 8,
    padding: 16,
  },
  header: {
    alignItems: "flex-start",
    flexDirection: "row",
    gap: 8,
  },
  message: {
    color: tokens.ink,
    flex: 1,
    flexShrink: 1,
    fontSize: 15,
    lineHeight: 22,
    paddingVertical: 10,
  },
  dismiss: {
    alignItems: "center",
    borderRadius: 22,
    justifyContent: "center",
    minHeight: 44,
    minWidth: 44,
  },
  dismissText: {
    color: tokens.ink_label,
    fontSize: 28,
  },
  action: {
    alignItems: "center",
    alignSelf: "flex-start",
    backgroundColor: tokens.brand,
    borderRadius: 12,
    flexDirection: "row",
    justifyContent: "center",
    marginTop: 8,
    maxWidth: "100%",
    minHeight: 44,
    minWidth: 44,
    paddingHorizontal: 16,
    paddingVertical: 8,
  },
  // Existing light brand/on_brand needs large bold text (>= 3:1), not small white text.
  actionText: {
    color: tokens.on_brand,
    flexShrink: 1,
    fontSize: 19,
    fontWeight: "700",
    lineHeight: 26,
    textAlign: "center",
  },
  progress: {
    marginRight: 8,
  },
  pressed: {
    opacity: 0.7,
  },
});

const STYLES = {
  light: makeStyles(THEME_TOKENS.light),
  dark: makeStyles(THEME_TOKENS.dark),
};
