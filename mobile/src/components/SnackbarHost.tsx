import React, { useCallback, useEffect, useRef, useState } from "react";
import { Animated, Easing, Pressable, StyleSheet, Text, View } from "react-native";

import type { SnackbarNotice } from "../feedback/snackbar";
import { subscribeToSnackbars } from "../feedback/snackbar";

const DISPLAY_DURATION = 3200;
const ANIMATION_DURATION = 180;

export default function SnackbarHost(): React.JSX.Element | null {
  const [notice, setNotice] = useState<SnackbarNotice | null>(null);
  const opacity = useRef(new Animated.Value(0)).current;
  const translateY = useRef(new Animated.Value(12)).current;
  const dismissTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  const clearDismissTimer = useCallback(() => {
    if (dismissTimer.current !== null) {
      clearTimeout(dismissTimer.current);
      dismissTimer.current = null;
    }
  }, []);

  const dismiss = useCallback(() => {
    clearDismissTimer();
    Animated.parallel([
      Animated.timing(opacity, {
        duration: ANIMATION_DURATION,
        easing: Easing.in(Easing.cubic),
        toValue: 0,
        useNativeDriver: true,
      }),
      Animated.timing(translateY, {
        duration: ANIMATION_DURATION,
        easing: Easing.in(Easing.cubic),
        toValue: 12,
        useNativeDriver: true,
      }),
    ]).start(() => setNotice(null));
  }, [clearDismissTimer, opacity, translateY]);

  useEffect(() => {
    const unsubscribe = subscribeToSnackbars((nextNotice) => {
      clearDismissTimer();
      setNotice(nextNotice);
      opacity.setValue(0);
      translateY.setValue(12);
      Animated.parallel([
        Animated.timing(opacity, {
          duration: ANIMATION_DURATION,
          easing: Easing.out(Easing.cubic),
          toValue: 1,
          useNativeDriver: true,
        }),
        Animated.timing(translateY, {
          duration: ANIMATION_DURATION,
          easing: Easing.out(Easing.cubic),
          toValue: 0,
          useNativeDriver: true,
        }),
      ]).start();
      dismissTimer.current = setTimeout(dismiss, DISPLAY_DURATION);
    });

    return () => {
      clearDismissTimer();
      unsubscribe();
    };
  }, [clearDismissTimer, dismiss, opacity, translateY]);

  if (!notice) {
    return null;
  }

  const toneStyle = notice.tone === "error" ? styles.error : styles.success;
  return (
    <View pointerEvents="box-none" style={styles.host} testID="snackbar-host">
      <Animated.View
        accessibilityLiveRegion="polite"
        style={[styles.surface, toneStyle, { opacity, transform: [{ translateY }] }]}
        testID="snackbar-surface"
      >
        <Text style={styles.status}>{notice.tone === "error" ? "!" : "i"}</Text>
        <Text style={styles.message}>{notice.message}</Text>
        <Pressable
          accessibilityLabel="Dismiss notification"
          accessibilityRole="button"
          hitSlop={10}
          onPress={dismiss}
          style={styles.dismiss}
        >
          <Text style={styles.dismissText}>×</Text>
        </Pressable>
      </Animated.View>
    </View>
  );
}

const styles = StyleSheet.create({
  host: {
    bottom: 104,
    left: 16,
    position: "absolute",
    right: 16,
    zIndex: 80,
  },
  surface: {
    alignItems: "center",
    borderRadius: 14,
    flexDirection: "row",
    minHeight: 52,
    paddingHorizontal: 14,
    shadowColor: "#161A35",
    shadowOffset: { height: 4, width: 0 },
    shadowOpacity: 0.18,
    shadowRadius: 10,
  },
  success: {
    backgroundColor: "#147DEB",
  },
  error: {
    backgroundColor: "#D92D20",
  },
  status: {
    borderColor: "#FFFFFF",
    borderRadius: 9,
    borderWidth: 1.5,
    color: "#FFFFFF",
    fontSize: 12,
    fontWeight: "800",
    height: 18,
    lineHeight: 15,
    textAlign: "center",
    width: 18,
  },
  message: {
    color: "#FFFFFF",
    flex: 1,
    fontSize: 14,
    fontWeight: "600",
    marginHorizontal: 11,
  },
  dismiss: {
    alignItems: "center",
    height: 36,
    justifyContent: "center",
    width: 36,
  },
  dismissText: {
    color: "#FFFFFF",
    fontSize: 23,
    lineHeight: 25,
  },
});
