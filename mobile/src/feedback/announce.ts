import { AccessibilityInfo, Platform } from "react-native";

/**
 * Speaks a message that appears without taking focus. accessibilityLiveRegion is
 * Android only and the alert role has no iOS trait, so VoiceOver says nothing about a
 * snackbar, a notice or a banner unless it is told. TalkBack already speaks the live
 * region, so announcing there as well would say everything twice.
 */
export function announce(message: string): void {
  if (Platform.OS === "ios") {
    AccessibilityInfo.announceForAccessibility(message);
  }
}
