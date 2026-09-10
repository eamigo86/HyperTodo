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

function prepareRequest(base:URL,input:RequestInfo|URL,init:RequestInit,appVersion:string):[string,RequestInit] {
  const headers=new Headers(init.headers);
  if(!headers.has("Accept"))headers.set("Accept","application/vnd.hyperview+xml");
  if(!headers.has("Origin"))headers.set("Origin",base.origin);
  headers.set("Cache-Control","no-store");
  if(appVersion)headers.set("X-App-Version",appVersion);
  return [new URL(inputUrl(input),base).toString(),{...init,headers,credentials:"include",cache:"no-store"}];
}

/** Bare modern HTTP: preserve metadata, never read the body or publish theme. */
export function createHyperviewHttpPort(
  baseUrl:string,
  implementation:FetchImplementation=fetch,
  appVersion:string=getAppVersion(),
):FetchImplementation {
  const base=new URL(baseUrl);
  return async(input,init={})=>{
    const [url,prepared]=prepareRequest(base,input,init,appVersion);
    const target=new URL(url);
    if(target.origin!==base.origin||target.username||target.password||!["http:","https:"].includes(target.protocol))throw new Error("unsupported-http-origin");
    return implementation(url,{...prepared,redirect:"error"});
  };
}

/** Legacy wrapper retains its existing theme and cross-origin behavior. */
export function createHyperviewFetch(
  baseUrl:string,
  implementation:FetchImplementation=fetch,
  appVersion:string=getAppVersion(),
):FetchImplementation {
  const base=new URL(baseUrl);
  return (input,init={})=>{
    const [url,prepared]=prepareRequest(base,input,init,appVersion);
    return implementation(url,prepared).then(response=>{
      // Headers only. The public Parser consumes the body later.
      publishTheme(response.headers?.get(THEME_HEADER));
      return response;
    });
  };
}
