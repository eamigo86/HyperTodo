jest.mock("expo-constants", () => ({ expoConfig: { version: "9.9.9", extra: { apiUrl: "http://10.0.2.2:8000/hv" } } }));

import Constants from "expo-constants";
import { getApiUrl, getAppVersion, normalizeApiUrl } from "../src/config";

// The mock above is the module object itself, so a test can swap what the runtime reads.
const mocked = Constants as unknown as { expoConfig: unknown };

describe("mobile configuration", () => {
  it("normalizes the configured API URL with a trailing slash", () => {
    expect(getApiUrl()).toBe("http://10.0.2.2:8000/hv/");
    expect(normalizeApiUrl("http://localhost:8000/hv/")).toBe("http://localhost:8000/hv/");
  });

  // app.config.ts refuses to build without a URL and has no localhost default on
  // purpose. A binary that still lacks one was not built from it, and guessing
  // 127.0.0.1 would only hide that behind requests that reach nothing.
  it.each([
    ["no config at all", null],
    ["no extra block", { version: "9.9.9" }],
    ["no apiUrl", { version: "9.9.9", extra: {} }],
    ["an empty apiUrl", { version: "9.9.9", extra: { apiUrl: "" } }],
    ["a non-string apiUrl", { version: "9.9.9", extra: { apiUrl: 8000 } }],
  ])("refuses to guess a server when the config has %s", (_label, expoConfig) => {
    const saved = mocked.expoConfig;
    mocked.expoConfig = expoConfig;
    try {
      expect(() => getApiUrl()).toThrow(/extra\.apiUrl/);
    } finally {
      mocked.expoConfig = saved;
    }
  });

  it("reports the binary's own version so the server can render it", () => {
    expect(getAppVersion()).toBe("9.9.9");
  });
});
