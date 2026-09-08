import "react-native-gesture-handler";

import { NavigationContainer } from "@react-navigation/native";
import * as SplashScreen from "expo-splash-screen";
import { StatusBar } from "expo-status-bar";
import Hyperview from "hyperview";
import type { ErrorScreenProps } from "hyperview/src/types";
import type { Props as LoadingProps } from "hyperview/src/components/loading/types";
import moment from "moment";
import React from "react";
import { ActivityIndicator, Pressable, StyleSheet, Text, View } from "react-native";
import { SafeAreaProvider, SafeAreaView } from "react-native-safe-area-context";

import { getApiUrl } from "./src/config";
import AnimatedSideMenu from "./src/components/AnimatedSideMenu";
import EdgeMenuOpener from "./src/components/EdgeMenuOpener";
import ElementErrorBanner from "./src/components/ElementErrorBanner";
import OfflineRefreshControl from "./src/components/OfflineRefreshControl";
import { FAILURE_COPY, classifyFailure } from "./src/feedback/failure";
import { hyperviewLogger, reportHyperviewError } from "./src/feedback/logging";
import AnimatedSplash from "./src/components/AnimatedSplash";
import SwipeRow from "./src/components/SwipeRow";
import SnackbarHost from "./src/components/SnackbarHost";
import ShowSnackbarBehavior from "./src/behaviors/ShowSnackbarBehavior";
import BiometricUnlockBehavior from "./src/behaviors/BiometricUnlockBehavior";
import PickAvatarBehavior from "./src/behaviors/PickAvatarBehavior";
import ProbeBiometricsBehavior from "./src/behaviors/ProbeBiometricsBehavior";
import StoreBiometricTokenBehavior from "./src/behaviors/StoreBiometricTokenBehavior";
import { createHyperviewFetch } from "./src/network";
import { THEME_TOKENS, useThemeName, type ThemeTokens } from "./src/theme";

void SplashScreen.preventAutoHideAsync();

export function LoadingScreen(_props: LoadingProps): React.JSX.Element {
  const styles = STYLES[useThemeName()];
  return (
    <View accessibilityLabel="Loading HyperTodo" style={styles.loading}>
      <View style={styles.mark}><Text style={styles.markText}>✓</Text></View>
      <Text style={styles.brand}>HyperTodo</Text>
      <ActivityIndicator color={styles.spinner.color} style={styles.spinner} />
    </View>
  );
}

export function ErrorScreen({ error, onPressReload }: ErrorScreenProps): React.JSX.Element {
  // Never render `error.message`: it is developer text (stack frames, status codes) and the
  // full-screen error state is the most visible surface in the app.
  const copy = FAILURE_COPY[classifyFailure(error)];
  const styles = STYLES[useThemeName()];
  return (
    <View accessibilityLabel="HyperTodo error" style={styles.loading}>
      <View style={styles.errorCard} testID="error-card">
        <Text style={styles.errorTitle}>{copy.title}</Text>
        <Text style={styles.errorCopy}>{copy.body}</Text>
        <Pressable accessibilityRole="button" onPress={onPressReload} style={styles.button}>
          <Text style={styles.buttonText}>{copy.action}</Text>
        </Pressable>
      </View>
    </View>
  );
}

const entrypointUrl = getApiUrl();
const hyperviewFetch = createHyperviewFetch(entrypointUrl);
// Module scope, not inline props. App re-renders whenever the server names a new
// palette, and Hyperview is a PureComponent: a fresh array or closure on each
// render would fail its shallow compare and re-render the whole server-driven tree
// for a change that only repaints two insets.
const behaviors = [ShowSnackbarBehavior, StoreBiometricTokenBehavior, ProbeBiometricsBehavior, BiometricUnlockBehavior, PickAvatarBehavior];
const components = [AnimatedSideMenu, EdgeMenuOpener, SwipeRow];
const formatDate = (date?: Date | null, format?: string) =>
  date && format ? moment(date).format(format) : undefined;

export default function App(): React.JSX.Element {
  const styles = STYLES[useThemeName()];
  return (
    <SafeAreaProvider>
      <AnimatedSplash>
        {/* Stays "light" in both palettes: `brand` is a deep blue either way and
            white glyphs clear 4.94:1 on the dark one. */}
        <StatusBar style="light" />
        <SafeAreaView edges={["top"]} style={styles.topInset} testID="top-inset">
          <SafeAreaView
            accessibilityLabel="HyperTodo safe area"
            edges={["bottom"]}
            style={styles.safeArea}
          >
            <NavigationContainer>
              <Hyperview
                behaviors={behaviors}
                components={components}
                entrypointUrl={entrypointUrl}
                fetch={hyperviewFetch}
                formatDate={formatDate}
                loadingScreen={LoadingScreen}
                errorScreen={ErrorScreen}
                elementErrorComponent={ElementErrorBanner}
                refreshControl={OfflineRefreshControl}
                logger={hyperviewLogger}
                onError={reportHyperviewError}
              />
            </NavigationContainer>
            <SnackbarHost />
          </SafeAreaView>
        </SafeAreaView>
      </AnimatedSplash>
    </SafeAreaProvider>
  );
}

// Two frozen sheets built once at import, rather than a sheet rebuilt per render or
// an inline colour override per element: `style` stays a single object, so every
// style assertion in the suite keeps reading the way it always did.
const makeStyles = (t: ThemeTokens) => StyleSheet.create({
  topInset: { flex: 1, backgroundColor: t.brand },
  // `canvas`, not `surface`: every screen's `bottom-navigation-style` rule declares
  // backgroundColor="{{ theme.canvas }}", and this inset sits directly under it.
  safeArea: { flex: 1, backgroundColor: t.canvas },
  loading: { flex: 1, alignItems: "center", justifyContent: "center", backgroundColor: t.canvas, padding: 28 },
  // Identity, not theme: cat_lavender and on_category are byte-identical in both
  // server palettes, so the mark is the one thing here that does not move.
  mark: { width: 72, height: 72, borderRadius: 24, alignItems: "center", justifyContent: "center", backgroundColor: t.cat_lavender },
  markText: { color: t.on_category, fontSize: 38, fontWeight: "700" },
  brand: { marginTop: 16, color: t.ink, fontSize: 28, fontWeight: "700" },
  // `color` is read off this sheet and handed to ActivityIndicator, which takes a
  // prop rather than a style. 3.15:1 on the light canvas, 9.01:1 on the dark one.
  spinner: { marginTop: 22, color: t.brand_ink },
  errorCard: { width: "100%", borderRadius: 28, backgroundColor: t.surface, padding: 24 },
  errorTitle: { color: t.ink, fontSize: 23, fontWeight: "700" },
  errorCopy: { color: t.ink_muted_alt, fontSize: 16, lineHeight: 23, marginTop: 10 },
  button: { backgroundColor: t.brand, borderRadius: 18, marginTop: 22, padding: 16, minHeight: 44, justifyContent: "center" },
  // White on light's #278CFF is 3.34:1, so it only clears WCAG large-text contrast
  // at 19/700. Dark's #1F6FD1 improves that to 4.94:1 and clears AA at any size.
  buttonText: { color: t.on_brand, textAlign: "center", fontSize: 19, fontWeight: "700" }
});

const STYLES = { light: makeStyles(THEME_TOKENS.light), dark: makeStyles(THEME_TOKENS.dark) };
