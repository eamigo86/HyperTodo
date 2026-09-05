export type FetchImplementation = (
  input: RequestInfo | URL,
  init?: RequestInit
) => Promise<Response>;

function inputUrl(input: RequestInfo | URL): string {
  if (typeof input === "string" || input instanceof URL) {
    return input.toString();
  }
  return input.url;
}

export function createHyperviewFetch(
  baseUrl: string,
  implementation: FetchImplementation = fetch
): FetchImplementation {
  const base = new URL(baseUrl);
  return (input, init = {}) => {
    const headers = new Headers(init.headers);
    if (!headers.has("Accept")) {
      headers.set("Accept", "application/vnd.hyperview+xml");
    }
    if (!headers.has("Origin")) {
      headers.set("Origin", base.origin);
    }
    headers.set("Cache-Control", "no-store");
    return implementation(new URL(inputUrl(input), base).toString(), {
      ...init,
      headers,
      credentials: "include",
      cache: "no-store"
    });
  };
}
