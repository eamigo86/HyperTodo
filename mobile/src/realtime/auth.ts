import {DOMParser} from "@instawork/xmldom";
import type {NoticeLabels} from "./resources";
import type {AuthResult} from "./session";
import {utf8Bytes} from "./session-protocol";

export type AuthDelivery=(result:AuthResult)=>boolean;
/** Internal adapter receives the genuine Parser-prepared request, never a Response substitute. */
export type GateAuthPort=(url:string,init:RequestInit,resume:AuthDelivery)=>Promise<AuthResult>;
export type Outcome = "ack" | "no-document" | "error" | "cancelled" | "dropped";
export type TerminalReason = "owner-unavailable" | "sync-drop" | "sync-replaced" | "sdk-on-end" | "once" | "missing-target" | "removed-delayed-origin" | "missing-local-source" | "parser-no-op" | "empty-response" | "request-error" | "local-layout" | "remote-layout" | "caller-error" | "uncorrelated-result" | "reload-layout" | "unsupported-document" | "navigation-changed" | "navigation-no-op" | "missing-destination" | "auth-transition" | "auth-panel-layout" | "auth-refused" | "auth-busy" | "auth-uncertain";
/** Passive internal facts only; never a callback capable of acknowledging XML. */
export type GateObservation = Readonly<{kind:"ready";epoch:number;routeKey:string}> | Readonly<{kind:"terminal";epoch:number;routeKey:string;operation:string|null;outcome:Outcome;reason:TerminalReason}>;
export type GatePorts={onObservation?:(event:GateObservation)=>void;noticeLabels?:()=>NoticeLabels;authenticate?:GateAuthPort;onReady?:(ready:Readonly<{epoch:number;routeKey:string}>)=>void;admitMutation?:(operation:object)=>string|null;confirmDiscard?:()=>Promise<boolean>;onResourceUpdated?:()=>void};

/** Parse only the app's accepted login panels, without private SDK normalization. */
export function parseOwnedAuthPanel(result:Extract<AuthResult,{kind:"panel"|"refused"}>,requestId:string|undefined):Element {
  if(result.kind!=="panel"||![422,401,429].includes(result.status)||utf8Bytes(result.body)>262144||/<!\s*(DOCTYPE|ENTITY)\b/i.test(result.body))throw new Error("invalid-auth-panel");
  const fail=()=>{throw new Error("invalid-auth-panel");};
  const doc=new DOMParser({errorHandler:{warning:fail,error:fail,fatalError:fail}}).parseFromString(result.body,"application/xml");
  const root=doc.documentElement;
  if(root.namespaceURI!=="https://hyperview.org/hyperview"||root.localName!=="view"||root.getAttribute("id")!=="login-panel")throw new Error("invalid-auth-panel");
  if(!requestId||root.getAttribute("key")!==`auth-panel-${requestId}`)throw new Error("invalid-auth-panel-key");
  for(const node of Array.from(root.getElementsByTagName("*"))){
    if(node.namespaceURI==="https://hyperview.org/hyperview"&&["doc","screen","navigator","body"].includes(node.localName))throw new Error("invalid-auth-panel");
    if(node.localName==="behavior"&&node.getAttribute("action")==="store-biometric-token"&&(result.status!==401||node.getAttribute("token")!==""))throw new Error("invalid-auth-effect");
  }
  return root;
}
