import { createHyperviewFetch } from "../src/network";

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
});
