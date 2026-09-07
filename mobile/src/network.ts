import { getAppVersion } from "./config";
import { publishTheme } from "./theme";

// The server names the palette it painted each response with. This wrapper is the
// single fetch the hyperview Parser is built from -- for documents (hv-doc.tsx:77)
// and for fragments (hyperview.tsx:56) -- and `this.fetch` in
// services/dom/parser.ts is the library's only call site, so reading it here
// catches every response with no per-screen wiring.
const THEME_HEADER = "X-HyperTodo-Theme";

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
  implementation: FetchImplementation = fetch,
  appVersion: string = getAppVersion()
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
    // Unconditional like Cache-Control above: the client is authoritative about its
    // own version, so a caller-supplied X-App-Version is not worth honouring.
    if (appVersion) {
      headers.set("X-App-Version", appVersion);
    }
    return implementation(new URL(inputUrl(input), base).toString(), {
      ...init,
      headers,
      credentials: "include",
      cache: "no-store"
    }).then((response) => {
      // Headers only. parser.ts:175 reads the body AFTER this resolves, so a clone
      // or a text() here would hand hyperview a consumed response. No catch
      // either: a rejection is the caller's to classify.
      publishTheme(response.headers?.get(THEME_HEADER));
      return response;
    });
  };
}
