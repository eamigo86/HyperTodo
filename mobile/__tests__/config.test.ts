jest.mock("expo-constants", () => ({ expoConfig: { version: "9.9.9", extra: { apiUrl: "http://10.0.2.2:8000/hv" } } }));

import { getApiUrl, getAppVersion, normalizeApiUrl } from "../src/config";

describe("mobile configuration", () => {
  it("normalizes the configured API URL with a trailing slash", () => {
    expect(getApiUrl()).toBe("http://10.0.2.2:8000/hv/");
    expect(normalizeApiUrl("http://localhost:8000/hv/")).toBe("http://localhost:8000/hv/");
  });

  it("reports the binary's own version so the server can render it", () => {
    expect(getAppVersion()).toBe("9.9.9");
  });
});
