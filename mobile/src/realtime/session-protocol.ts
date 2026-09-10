import {DOMParser} from "@instawork/xmldom";

export const SESSION_HEADERS = Object.freeze({
  contract:"X-HyperTodo-Client-Contract",
  expected:"X-HyperTodo-Expected-Session",
  binding:"X-HyperTodo-Session-Binding",
  outcome:"X-HyperTodo-Auth-Outcome",
});
export type AuthKind = "password" | "biometric" | "logout";
export type Observation = Readonly<{version:1;authenticated:boolean;binding:string}>;
export type CredentialEffect = Readonly<{kind:"store";token:string} | {kind:"clear"}>;
export type AuthBody = {kind:"success";effect:CredentialEffect|null} | {kind:"panel"|"refused";effect:CredentialEffect|null;body:string};
const BINDING=/^hvs1\.[A-Za-z0-9_-]{43}$/;
const TOKEN=/^[A-Za-z0-9_-]{43}$/;
const HV="https://hyperview.org/hyperview";

/** Count valid UTF-8 bytes without relying on a claimed Content-Length. */
export function utf8Bytes(value:string):number {
  let bytes=0;
  for(let i=0;i<value.length;i++) {
    const code=value.charCodeAt(i);
    if(code<0x80)bytes++;
    else if(code<0x800)bytes+=2;
    else if(code>=0xd800&&code<=0xdbff) {
      const next=value.charCodeAt(++i);
      if(!(next>=0xdc00&&next<=0xdfff))throw new Error("invalid-unicode");
      bytes+=4;
    } else if(code>=0xdc00&&code<=0xdfff)throw new Error("invalid-unicode");
    else bytes+=3;
  }
  return bytes;
}

export function validBinding(value:unknown):value is string {return typeof value==="string"&&BINDING.test(value);}

/** Classify auth by the configured origin, exact method and exact pathname. */
export function classifyAuth(value:string,method:string,origin:string):AuthKind|null {
  const url=new URL(value);
  if(url.origin!==origin||method.toUpperCase()!=="POST")return null;
  return ({"/hv/login/":"password","/hv/biometric/login/":"biometric","/hv/logout/":"logout"} as const)[url.pathname as "/hv/login/"]??null;
}

/** Accept only the bounded server observation and identical header binding. */
export function parseObservation(body:string,headers:Headers):Observation {
  if(utf8Bytes(body)>1024)throw new Error("observation-too-large");
  const value:unknown=JSON.parse(body);
  if(!value||typeof value!=="object"||Array.isArray(value))throw new Error("invalid-observation");
  const data=value as Record<string,unknown>;
  if(Object.keys(data).sort().join(",")!=="authenticated,binding,version"||data.version!==1||typeof data.authenticated!=="boolean"||!validBinding(data.binding)||headers.get(SESSION_HEADERS.binding)!==data.binding)throw new Error("invalid-observation");
  return Object.freeze({version:1,authenticated:data.authenticated,binding:data.binding});
}

function xml(body:string):Element {
  if(/<!\s*(DOCTYPE|ENTITY)\b/i.test(body))throw new Error("forbidden-auth-xml");
  const fail=()=>{throw new Error("invalid-auth-xml");};
  const root=new DOMParser({errorHandler:{warning:fail,error:fail,fatalError:fail}}).parseFromString(body,"application/xml").documentElement;
  if(!root||root.namespaceURI!==HV||root.localName!=="view")throw new Error("invalid-auth-root");
  return root;
}
function attributes(element:Element,expected:Record<string,string>):boolean {
  return element.namespaceURI===HV&&element.localName==="behavior"&&element.attributes.length===Object.keys(expected).length&&Object.entries(expected).every(([key,value])=>element.getAttribute(key)===value)&&!Array.from(element.childNodes).some(node=>node.nodeType===1||!!node.textContent?.trim());
}
const store=(token:string)=>({trigger:"load",action:"store-biometric-token",token,once:"true",immediate:"true"});

/** Validate only this auth handoff contract; it does not replace backend XSD validation. */
export function parseAuthBody(kind:AuthKind,status:number,outcome:string|null,body:string):AuthBody {
  if(utf8Bytes(body)>262144)throw new Error("auth-body-too-large");
  if(status===403&&outcome===null)return {kind:"refused",effect:null,body};
  const root=xml(body);
  const success=kind==="password"?"password-ok":kind==="biometric"?"biometric-ok":"logout-ok";
  if(status===200&&outcome===success) {
    const isLogout=kind==="logout";
    if(root.getAttribute("id")!==(isLogout?"logout-panel":"login-transition"))throw new Error("invalid-auth-transition");
    const children=Array.from(root.childNodes);
    if(children.some(node=>![1,3,8].includes(node.nodeType)||(node.nodeType===3&&!!node.textContent?.trim())))throw new Error("invalid-auth-transition");
    const behaviors=children.filter(node=>node.nodeType===1) as Element[];
    const effectNode=isLogout?undefined:behaviors.shift();
    let effect:CredentialEffect|null=null;
    if(!isLogout) {
      const token=effectNode?.getAttribute("token");
      if(token===null||token===undefined||(!TOKEN.test(token)&&!(kind==="password"&&token===""))||!attributes(effectNode!,store(token)))throw new Error("invalid-credential-effect");
      effect=token?Object.freeze({kind:"store",token}):Object.freeze({kind:"clear"});
    }
    if(behaviors.length!==2||!attributes(behaviors[0],{trigger:"load",action:"dispatch-event","event-name":"session-changed",once:"true"})||!attributes(behaviors[1],{trigger:"load",href:isLogout?"/hv/login/":"/hv/dashboard/",action:"reload"}))throw new Error("invalid-auth-transition");
    return {kind:"success",effect};
  }
  const panelOutcome=kind==="password"&&status===422&&outcome==="password-invalid"||kind==="biometric"&&status===401&&outcome==="biometric-invalid"||kind==="biometric"&&status===429&&outcome==="biometric-throttled";
  if(!panelOutcome||root.getAttribute("id")!=="login-panel")throw new Error("invalid-auth-outcome");
  const stores=Array.from(root.getElementsByTagNameNS(HV,"behavior")).filter(node=>node.getAttribute("action")==="store-biometric-token");
  const clears=kind==="biometric"&&status===401;
  if(stores.length!==(clears?1:0)||(clears&&!attributes(stores[0],store(""))))throw new Error("invalid-credential-effect");
  return {kind:"panel",effect:clears?Object.freeze({kind:"clear"}):null,body};
}
