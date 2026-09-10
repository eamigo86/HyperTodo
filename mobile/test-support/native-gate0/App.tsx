import Constants from "expo-constants";
import { fetch as expoFetch } from "expo/fetch";
import { version as expoVersion } from "expo/package.json";
import React, { useState } from "react";
import { Platform, Pressable, ScrollView, StyleSheet, Text, View } from "react-native";

import { runNativeProbe, type ProbeResult } from "./probe";

/** Standalone synthetic panel. It never imports HyperTodo App or authentication. */
export default function App(): React.JSX.Element {
  const [started, setStarted] = useState(false);
  const [stage, setStage] = useState("NOT_RUN");
  const [result, setResult] = useState<ProbeResult | null>(null);
  const nativeVersion = Platform.constants.reactNativeVersion;
  const metadata = {
    platform:Platform.OS,
    executionEnvironment:Constants.executionEnvironment,
    clientVersion:Constants.expoVersion ?? "unknown",
    expoVersion,
    reactNativeVersion:nativeVersion ? `${nativeVersion.major}.${nativeVersion.minor}.${nativeVersion.patch}` : "unknown",
  };
  const run = async () => {
    if (started) return;
    setStarted(true);
    const outcome = await runNativeProbe({
      baseUrl:String(Constants.expoConfig?.extra?.gate0BaseUrl ?? ""),
      metadata,
      bootstrapFetch:globalThis.fetch,
      streamFetch:expoFetch,
      onProgress:setStage,
    });
    setResult(outcome);
    // All values are bounded protocol codes/booleans or runtime version metadata.
    // No URL, token, cookie, device identifier, raw exception or stack is logged.
    console.info("NATIVE_GATE0_RESULT", JSON.stringify({scope:"native-io-only",...metadata,...outcome}));
  };
  return (
    <ScrollView contentInsetAdjustmentBehavior="automatic" contentContainerStyle={styles.page}>
      <Text accessibilityRole="header" style={styles.heading}>Gate 0 · Native I/O</Text>
      <Text style={styles.copy}>Synthetic cookie, two ACK-gated stream frames, then AbortController.</Text>
      <View style={styles.card}>
        <Text selectable>Platform: {metadata.platform}</Text>
        <Text selectable>Environment: {metadata.executionEnvironment}</Text>
        <Text selectable>Expo client build/version: {metadata.clientVersion}</Text>
        <Text selectable>Expo source: {metadata.expoVersion}</Text>
        <Text selectable>React Native: {metadata.reactNativeVersion}</Text>
      </View>
      <Pressable accessibilityRole="button" accessibilityLabel="Run isolated native I/O probe" accessibilityState={{disabled:started}} disabled={started} onPress={() => { void run(); }} style={[styles.button, started && styles.disabled]}>
        <Text style={styles.buttonText}>Run isolated native I/O probe</Text>
      </Pressable>
      <Text accessibilityLiveRegion="polite" style={styles.status}>{result ? `${result.status} — native I/O only` : stage}</Text>
      {result && <View style={styles.card}>
        {Object.entries(result.checks).map(([name, value]) => <Text key={name}>{name}: {value ? "yes" : "no"}</Text>)}
        <Text>Report delivered: {result.reported ? "yes" : "no"}</Text>
        <Text>Own cookie cleanup: {result.cookieCleanup}</Text>
        {result.failedStage && <Text>Stage: {result.failedStage}; code: {result.errorCode}</Text>}
      </View>}
      <Text style={styles.copy}>This does not approve the full realtime Gate 0.</Text>
      <Text style={styles.copy}>No app data or existing session is used. One stream per fixture; ask for a fresh fixture to repeat. If cleanup is pending, the synthetic cookie has a bounded expiry. Never clear the shared cookie jar.</Text>
    </ScrollView>
  );
}
const styles = StyleSheet.create({
  page:{padding:24,paddingTop:72,paddingBottom:48,gap:20,backgroundColor:"#ffffff"},
  heading:{fontSize:26,fontWeight:"700",color:"#111827"},
  copy:{fontSize:16,lineHeight:23,color:"#374151"},
  card:{gap:8,padding:16,borderWidth:1,borderColor:"#cbd5e1",borderRadius:12},
  button:{padding:16,minHeight:48,borderRadius:10,backgroundColor:"#1d4ed8"},
  disabled:{backgroundColor:"#64748b"},
  buttonText:{fontSize:16,fontWeight:"600",color:"#ffffff"},
  status:{fontSize:20,fontWeight:"700",color:"#111827"},
});
