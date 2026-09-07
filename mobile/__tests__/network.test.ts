import { createHyperviewFetch } from "../src/network";
import { getThemeName, publishTheme } from "../src/theme";

jest.mock("expo-secure-store", () => ({ getItem: () => null, setItem: () => undefined }));

describe("createHyperviewFetch", () => {
  it("resolves relative URLs and preserves Hyperview request headers", async () => {
    const implementation = jest.fn().mockResolvedValue(new Response("ok"));
    const client = createHyperviewFetch("http://127.0.0.1:8000/hv/", implementation);
    await client("tasks/", { method: "POST", headers: { "Content-Type": "application/x-www-form-urlencoded", "X-Custom": "yes" } });
    const [url, init] = implementation.mock.calls[0];
    expect(url).toBe("http://127.0.0.1:8000/hv/tasks/");
    expect(init.credentials).toBe("include");
    expect(init.cache).toBe("no-store");
    expect(init.headers.get("Content-Type")).toBe("application/x-www-form-urlencoded");
    expect(init.headers.get("X-Custom")).toBe("yes");
    expect(init.headers.get("Accept")).toBe("application/vnd.hyperview+xml");
    expect(init.headers.get("Origin")).toBe("http://127.0.0.1:8000");
  });

  it("does not overwrite explicit Accept or Origin headers", async () => {
    const implementation = jest.fn().mockResolvedValue(new Response("ok"));
    const client = createHyperviewFetch("http://localhost:8000/hv/", implementation);
    await client(new Request("http://example.test/screen"), { headers: { Accept: "custom", Origin: "http://mobile.test" } });
    const init = implementation.mock.calls[0][1];
    expect(init.headers.get("Accept")).toBe("custom");
    expect(init.headers.get("Origin")).toBe("http://mobile.test");
  });

  it("sends the app version so the server can render it", async () => {
    const implementation = jest.fn().mockResolvedValue(new Response("ok"));
    const client = createHyperviewFetch("http://127.0.0.1:8000/hv/", implementation, "1.4.2");
    await client("settings/");
    expect(implementation.mock.calls[0][1].headers.get("X-App-Version")).toBe("1.4.2");
  });

  it("omits the version header when the app config has none", async () => {
    const implementation = jest.fn().mockResolvedValue(new Response("ok"));
    const client = createHyperviewFetch("http://127.0.0.1:8000/hv/", implementation, "");
    await client("settings/");
    expect(implementation.mock.calls[0][1].headers.get("X-App-Version")).toBeNull();
  });
});

// `this.fetch` in hyperview/src/services/dom/parser.ts (lines 147, 155, 160) is the
// ONLY fetch call site in the library, and the Parser is built from `props.fetch`
// for both documents (hv-doc.tsx:77) and fragments (hyperview.tsx:56). This wrapper
// therefore sees every response the server sends, which makes it the one place the
// theme header has to be read.
describe("server-driven theme header", () => {
  beforeEach(() => publishTheme("light"));
  afterEach(() => publishTheme("light"));

  function respondWith(headers: Record<string, string>): jest.Mock {
    return jest.fn().mockResolvedValue(new Response("<doc/>", { headers }));
  }

  it("adopts the palette the server painted the response with", async () => {
    const client = createHyperviewFetch(
      "http://127.0.0.1:8000/hv/",
      respondWith({ "X-HyperTodo-Theme": "dark" }),
    );

    await client("dashboard/");

    expect(getThemeName()).toBe("dark");
  });

  it("keeps the current palette for a response that names none or names nonsense", async () => {
    publishTheme("dark");

    await createHyperviewFetch("http://127.0.0.1:8000/hv/", respondWith({}))("dashboard/");
    expect(getThemeName()).toBe("dark");

    await createHyperviewFetch(
      "http://127.0.0.1:8000/hv/",
      respondWith({ "X-HyperTodo-Theme": "chartreuse" }),
    )("dashboard/");
    expect(getThemeName()).toBe("dark");
  });

  it("hands the parser back the very same Response, body unread", async () => {
    // parser.ts:175 calls response.text() AFTER this wrapper returns. Cloning or
    // reading here would hand hyperview a consumed body and every screen would
    // fail to parse.
    const response = new Response("<doc/>", { headers: { "X-HyperTodo-Theme": "dark" } });
    const client = createHyperviewFetch(
      "http://127.0.0.1:8000/hv/",
      jest.fn().mockResolvedValue(response),
    );

    const received = await client("dashboard/");

    expect(received).toBe(response);
    expect(received.bodyUsed).toBe(false);
    await expect(received.text()).resolves.toBe("<doc/>");
  });

  it("passes a failure through untouched and changes nothing", async () => {
    const offline = new TypeError("Network request failed");
    const client = createHyperviewFetch(
      "http://127.0.0.1:8000/hv/",
      jest.fn().mockRejectedValue(offline),
    );

    await expect(client("dashboard/")).rejects.toBe(offline);
    expect(getThemeName()).toBe("light");
  });
});
