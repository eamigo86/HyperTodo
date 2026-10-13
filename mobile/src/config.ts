import Constants from "expo-constants";

export function normalizeApiUrl(value: string): string {
  const url = new URL(value);
  url.pathname = url.pathname.endsWith("/") ? url.pathname : `${url.pathname}/`;
  return url.toString();
}

export function getApiUrl(): string {
  const configured = Constants.expoConfig?.extra?.apiUrl;
  if (typeof configured !== "string" || !configured) {
    // app.config.ts bakes the URL in or fails the build, and has no localhost default
    // on purpose. A binary without it was not built from that config, so say so
    // instead of guessing a server that reaches nothing.
    throw new Error(
      "extra.apiUrl is missing from the app config. app.config.ts sets it from " +
        "EXPO_PUBLIC_API_URL and deliberately has no localhost default.",
    );
  }
  return normalizeApiUrl(configured);
}

export function getAppVersion(): string {
  return Constants.expoConfig?.version ?? "";
}
