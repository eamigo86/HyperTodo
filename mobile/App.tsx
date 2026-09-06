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
import { createHyperviewFetch } from "./src/network";

void SplashScreen.preventAutoHideAsync();

export function LoadingScreen(_props: LoadingProps): React.JSX.Element {
  return (
    <View accessibilityLabel="Loading HyperTodo" style={styles.loading}>
      <View style={styles.mark}><Text style={styles.markText}>✓</Text></View>
      <Text style={styles.brand}>HyperTodo</Text>
      <ActivityIndicator color="#278CFF" style={styles.spinner} />
    </View>
  );
}

export function ErrorScreen({ error, onPressReload }: ErrorScreenProps): React.JSX.Element {
  return (
    <View accessibilityLabel="HyperTodo error" style={styles.loading}>
      <View style={styles.errorCard}>
        <Text style={styles.errorTitle}>We could not load your tasks</Text>
        <Text style={styles.errorCopy}>{error?.message ?? "Check the backend connection and try again."}</Text>
        <Pressable accessibilityRole="button" onPress={onPressReload} style={styles.button}>
          <Text style={styles.buttonText}>Try again</Text>
        </Pressable>
      </View>
    </View>
  );
}

const entrypointUrl = getApiUrl();
const hyperviewFetch = createHyperviewFetch(entrypointUrl);

export default function App(): React.JSX.Element {
  return (
    <SafeAreaProvider>
      <StatusBar style="dark" />
      <SafeAreaView
        accessibilityLabel="HyperTodo safe area"
        edges={["top", "bottom"]}
        style={styles.safeArea}
      >
        <NavigationContainer onReady={() => void SplashScreen.hideAsync()}>
          <Hyperview
            entrypointUrl={entrypointUrl}
            fetch={hyperviewFetch}
            formatDate={(date, format) => date && format ? moment(date).format(format) : undefined}
            loadingScreen={LoadingScreen}
            errorScreen={ErrorScreen}
          />
        </NavigationContainer>
      </SafeAreaView>
    </SafeAreaProvider>
  );
}

const styles = StyleSheet.create({
  safeArea: { flex: 1 },
  loading: { flex: 1, alignItems: "center", justifyContent: "center", backgroundColor: "#F7F8FC", padding: 28 },
  mark: { width: 72, height: 72, borderRadius: 24, alignItems: "center", justifyContent: "center", backgroundColor: "#AEBBFA" },
  markText: { color: "#161A35", fontSize: 38, fontWeight: "700" },
  brand: { marginTop: 16, color: "#161A35", fontSize: 28, fontWeight: "700" },
  spinner: { marginTop: 22 },
  errorCard: { width: "100%", borderRadius: 28, backgroundColor: "#FFFFFF", padding: 24 },
  errorTitle: { color: "#161A35", fontSize: 23, fontWeight: "700" },
  errorCopy: { color: "#6D728A", fontSize: 16, lineHeight: 23, marginTop: 10 },
  button: { backgroundColor: "#278CFF", borderRadius: 18, marginTop: 22, padding: 16 },
  buttonText: { color: "#FFFFFF", textAlign: "center", fontSize: 16, fontWeight: "700" }
});
