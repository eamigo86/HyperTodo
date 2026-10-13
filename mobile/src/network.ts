import { getAppVersion } from "./config";

// The only HTTP port the App hands to the session supervisor. It prepares each
// request (absolute URL, Hyperview Accept, Origin, App version) and forwards it
// untouched. It never reads a response body and never publishes the theme header:
// the supervisor does both only after it has confirmed the response belongs to the
// current session (realtime/session.ts).

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
