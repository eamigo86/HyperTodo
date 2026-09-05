jest.mock("expo-constants", () => ({ expoConfig: { extra: { apiUrl: "http://10.0.2.2:8000/hv" } } }));

import { getApiUrl, normalizeApiUrl } from "../src/config";

describe("mobile configuration", () => {
  it("normalizes the configured API URL with a trailing slash", () => {
    expect(getApiUrl()).toBe("http://10.0.2.2:8000/hv/");
    expect(normalizeApiUrl("http://localhost:8000/hv/")).toBe("http://localhost:8000/hv/");
  });
});
