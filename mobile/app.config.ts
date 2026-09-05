import type { ExpoConfig } from "expo/config";

const apiUrl = process.env.EXPO_PUBLIC_API_URL ?? "http://127.0.0.1:8000/hv/";

const config: ExpoConfig = {
  name: "HyperTodo",
  slug: "hypertodo",
  version: "0.1.0",
  orientation: "portrait",
  icon: "./assets/icon.png",
  userInterfaceStyle: "light",
  scheme: "hypertodo",
  plugins: [
    ["expo-build-properties", { android: { usesCleartextTraffic: true } }],
    [
      "expo-splash-screen",
      {
        backgroundColor: "#AEBBFA",
        image: "./assets/splash-icon.png",
        imageWidth: 180
      }
    ]
  ],
  ios: {
    supportsTablet: true,
    bundleIdentifier: "com.eamigo.hypertodo",
    infoPlist: { NSAllowsLocalNetworking: true }
  },
  android: {
    package: "com.eamigo.hypertodo",
    adaptiveIcon: {
      backgroundColor: "#AEBBFA",
      foregroundImage: "./assets/android-icon-foreground.png",
      monochromeImage: "./assets/android-icon-monochrome.png"
    }
  },
  extra: { apiUrl }
};

export default config;
