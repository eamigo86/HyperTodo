import { parseOwnedAuthPanel } from "../src/realtime/auth";

const HV = "https://hyperview.org/hyperview";
const id = "attempt-1";
const panel = (children = "", key = `auth-panel-${id}`) =>
  `<view xmlns="${HV}" id="login-panel" key="${key}">${children}</view>`;
const result = (body: string, status = 422) =>
  ({ kind: "panel" as const, status, body, receipt: {} });

describe("owned authentication panel admission", () => {
  it("accepts a keyed validation panel and exposes only its XML element", () => {
    const node = parseOwnedAuthPanel(result(panel("<text>Retry password</text>")), id);
    expect(node.getAttribute("id")).toBe("login-panel");
    expect(node.getElementsByTagName("text")[0].textContent).toBe("Retry password");
  });

  it.each([422, 401, 429])("accepts a permitted panel status: %s", status => {
    expect(parseOwnedAuthPanel(result(panel(), status), id).getAttribute("key"))
      .toBe(`auth-panel-${id}`);
  });

  it.each([
    ["refusal", { kind: "refused" as const, status: 403, body: panel(), receipt: {} }],
    ["success", result(panel(), 200)],
    ["oversized", result(panel("x".repeat(262145)))],
    ["DTD", result(`<!DOCTYPE view>${panel()}`)],
    ["wrong root", result(`<doc xmlns="${HV}"/>`)],
    ["missing key", result(panel("", ""))],
    ["different key", result(panel("", "auth-panel-other"))],
    ["nested screen", result(panel("<screen/>"))],
    ["unrequested biometric effect", result(panel('<behavior action="store-biometric-token" token=""/>'))],
  ])("rejects a %s before changing the current panel", (_case, invalid) => {
    expect(() => parseOwnedAuthPanel(invalid, id)).toThrow();
  });

  it("allows an empty-token biometric clear only on a 401 panel", () => {
    const body = panel('<behavior action="store-biometric-token" token=""/>');
    expect(parseOwnedAuthPanel(result(body, 401), id)
      .getElementsByTagName("behavior")).toHaveLength(1);
    expect(() => parseOwnedAuthPanel(result(body, 429), id)).toThrow("invalid-auth-effect");
    expect(() => parseOwnedAuthPanel(result(panel('<behavior action="store-biometric-token" token="secret"/>'), 401), id))
      .toThrow("invalid-auth-effect");
  });
});
