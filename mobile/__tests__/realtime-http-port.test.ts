import {createHyperviewHttpPort} from "../src/network";
import {getThemeName,publishTheme} from "../src/theme";
import {createSessionSupervisor} from "../src/realtime/session";
import {SESSION_HEADERS as H} from "../src/realtime/session-protocol";
jest.mock("expo-secure-store",()=>({getItem:()=>null,setItem:()=>undefined}));
const BASE="https://app.test/hv/",A="hvs1."+"A".repeat(43),B="hvs1."+"B".repeat(43);
function response(body:string,headers:Record<string,string>={}){const value=new Response(body,{headers});Object.defineProperty(value,"url",{value:BASE});return value;}
afterEach(()=>publishTheme("light"));

it("provides bare same-origin HTTP without consuming or repainting a genuine response",async()=>{
 publishTheme("light");const raw=response("<doc/>",{"X-HyperTodo-Theme":"dark"});const transport=jest.fn().mockResolvedValue(raw);const http=createHyperviewHttpPort(BASE,transport,"1.2.3");
 const received=await http("tasks/?filter=a&filter=b",{method:"POST",body:"csrf=kept&avatar=%2B",headers:{"X-CSRFToken":"csrf",Accept:"custom","Content-Type":"application/x-www-form-urlencoded"}});
 expect(received).toBe(raw);expect(raw.bodyUsed).toBe(false);expect(getThemeName()).toBe("light");
 const [url,init]=transport.mock.calls[0];expect(url).toBe(BASE+"tasks/?filter=a&filter=b");expect(init).toMatchObject({method:"POST",body:"csrf=kept&avatar=%2B",credentials:"include",redirect:"error",cache:"no-store"});
 expect(Object.fromEntries(init.headers.entries())).toMatchObject({accept:"custom",origin:"https://app.test","x-app-version":"1.2.3","x-csrftoken":"csrf","content-type":"application/x-www-form-urlencoded"});
});

it("denies foreign/userinfo HTTP destinations before forwarding cookies or headers",async()=>{
 const transport=jest.fn();const http=createHyperviewHttpPort(BASE,transport,"v");
 for(const url of ["https://foreign.test/hv/","https://user:secret@app.test/hv/","file:///hv/test"]){await expect(http(url,{headers:{[H.expected]:A}})).rejects.toThrow();}
 expect(transport).not.toHaveBeenCalled();
});

it("composes with the real supervisor so an untrusted binding cannot publish theme or body",async()=>{
 publishTheme("light");const ordinary=response("private B",{[H.binding]:B,"X-HyperTodo-Theme":"dark"});
 const raw=jest.fn(async(input:RequestInfo|URL,_init?:RequestInit)=>(typeof input==="string"?input:input instanceof URL?input.toString():input.url).endsWith("session-state/")?response(JSON.stringify({version:1,authenticated:true,binding:A}),{[H.binding]:A}):ordinary);
 const http=createHyperviewHttpPort(BASE,raw,"v");const supervisor=createSessionSupervisor({origin:"https://app.test",transport:http,storage:{enqueue:async()=>{}},stopStream:()=>{},onIdentity:()=>{},onTheme:publishTheme});
 await supervisor.bootstrap();await expect(supervisor.request(BASE+"tasks/")).rejects.toThrow();expect(ordinary.bodyUsed).toBe(false);expect(getThemeName()).toBe("light");
});

it("publishes theme only through the current supervisor and preserves the auth wire contract",async()=>{
 publishTheme("light");const ordinary=response("<view/>",{[H.binding]:A,"X-HyperTodo-Theme":"dark"});
 const raw=jest.fn(async(input:RequestInfo|URL,_init?:RequestInit)=>(typeof input==="string"?input:input instanceof URL?input.toString():input.url).endsWith("session-state/")?response(JSON.stringify({version:1,authenticated:true,binding:A}),{[H.binding]:A}):ordinary);
 const http=createHyperviewHttpPort(BASE,raw,"v");const supervisor=createSessionSupervisor({origin:"https://app.test",transport:http,storage:{enqueue:async()=>{}},stopStream:()=>{},onIdentity:()=>{},onTheme:publishTheme});
 await supervisor.bootstrap();const result=await supervisor.request(BASE+"tasks/",{headers:{"X-CSRFToken":"kept"}});expect(result.bodyUsed).toBe(false);expect(getThemeName()).toBe("dark");
 const init=raw.mock.calls[1][1] as RequestInit;expect(new Headers(init.headers).get(H.contract)).toBe("realtime-v1");expect(new Headers(init.headers).get(H.expected)).toBe(A);expect(new Headers(init.headers).get("X-CSRFToken")).toBe("kept");
});
