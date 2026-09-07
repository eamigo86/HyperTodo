import Constants from "expo-constants";

export const DEFAULT_API_URL = "http://127.0.0.1:8000/hv/";

export function normalizeApiUrl(value: string): string {
  const url = new URL(value);
  url.pathname = url.pathname.endsWith("/") ? url.pathname : `${url.pathname}/`;
  return url.toString();
}

export function getApiUrl(): string {
  const configured = Constants.expoConfig?.extra?.apiUrl;
  return normalizeApiUrl(typeof configured === "string" ? configured : DEFAULT_API_URL);
}

export function getAppVersion(): string {
  return Constants.expoConfig?.version ?? "";
}
