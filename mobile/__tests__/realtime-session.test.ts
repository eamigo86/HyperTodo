declare const __dirname:string;
const fs=jest.requireActual<{readFileSync:(name:string,encoding:"utf8")=>string}>("fs");
const path=jest.requireActual<{join:(...parts:string[])=>string}>("path");
import {createSessionSupervisor, type SessionClock} from "../src/realtime/session";
import {SESSION_HEADERS as H} from "../src/realtime/session-protocol";
const ORIGIN="https://app.test",A="hvs1."+"A".repeat(43),B="hvs1."+"B".repeat(43),TOKEN="t".repeat(43);
const login=fs.readFileSync(path.join(__dirname,"../../backend/hyperview/fragments/login_transition.xml"),"utf8").replace("{{ biometric_token }}",TOKEN);
const logout=fs.readFileSync(path.join(__dirname,"../../backend/hyperview/fragments/logout_transition.xml"),"utf8");
const panel=(clear=false)=>`<view xmlns="https://hyperview.org/hyperview" id="login-panel">${clear?'<behavior trigger="load" action="store-biometric-token" token="" once="true" immediate="true"/>':''}<form><text-field name="username" value="Kept draft"/></form></view>`;
function deferred<T>(){let resolve!:(value:T)=>void;let reject!:(error:Error)=>void;const promise=new Promise<T>((yes,no)=>{resolve=yes;reject=no;});return{promise,resolve,reject};}
const response=(body:string,binding=A,status=200,outcome?:string)=>({status,ok:status>=200&&status<300,redirected:false,url:ORIGIN+"/hv/",headers:new Headers({[H.binding]:binding,...(outcome?{[H.outcome]:outcome}:{}),"X-HyperTodo-Theme":"dark"}),text:jest.fn(async()=>body)}) as unknown as Response;
const observation=(binding=A,authenticated=true)=>response(JSON.stringify({version:1,authenticated,binding}),binding);
const tick=async()=>{for(let i=0;i<12;i++)await Promise.resolve();};
function fixture(onMutationSeed?: (seed:string,identity:import('../src/realtime/session').Identity)=>void){
 let binding=A;let authenticated=true;let authBody=login;let status=200;let outcome="password-ok";
 const timers:Array<{ms:number;run:()=>void;active:boolean}>=[];
 const clock:SessionClock={schedule:(run,ms)=>{const timer={ms,run,active:true};timers.push(timer);return()=>{timer.active=false;};},sleep:jest.fn(async(_ms:number)=>{})};
 const store={save:jest.fn(async(_token:string)=>{}),clear:jest.fn(async()=>{})};let tail=Promise.resolve();
 const storage={enqueue:(job:(value:typeof store)=>Promise<void>)=>{const result=tail.then(()=>job(store));tail=result.then(()=>{},()=>{});return result;}};
 const transport=jest.fn(async(url:string,_init:RequestInit):Promise<Response>=>{
  if(url.endsWith("/session-state/"))return observation(binding,authenticated);
  if(url.endsWith("/login/")||url.endsWith("/logout/")){if(status===200){binding=B;authenticated=outcome!=="logout-ok";}return response(authBody,binding,status,outcome);}
  return response("<view/>",binding);
 });
 const identity=jest.fn(),theme=jest.fn(),stop=jest.fn();
 const supervisor=createSessionSupervisor({origin:ORIGIN,transport,storage,clock,onIdentity:identity,onTheme:theme,stopStream:stop,onMutationSeed});
 return{supervisor,transport,store,identity,theme,stop,clock,timers,setBinding:(next:string)=>{binding=next;},setAuth:(code:number,tag:string,body:string)=>{status=code;outcome=tag;authBody=body;}};
}

it("bootstraps only the bounded observation and configures same-origin credentialed requests",async()=>{
 const {supervisor,transport,identity}=fixture();await expect(supervisor.bootstrap()).resolves.toBe("ready");
 expect(supervisor.snapshot()).toMatchObject({availability:"foreground",identity:{binding:A,authenticated:true,generation:1},rootReady:false});
 const init=transport.mock.calls[0][1];expect(init).toMatchObject({credentials:"include",redirect:"error",cache:"no-store",method:"GET"});expect(new Headers(init.headers).get(H.contract)).toBe("realtime-v1");
 expect(identity).toHaveBeenCalledTimes(1);expect(supervisor.markRootReady(0)).toBe(false);expect(supervisor.markRootReady(1)).toBe(true);
});

it("does not publish a confirmation completed after explicit revocation",async()=>{
 const f=fixture(),pending=deferred<Response>();
 f.transport.mockImplementationOnce(()=>pending.promise);
 const bootstrap=f.supervisor.bootstrap();await tick();
 f.supervisor.invalidate();pending.resolve(observation());
 await expect(bootstrap).resolves.toBe("stale");
 expect(f.supervisor.snapshot()).toMatchObject({identity:null,reason:"revoked"});
 expect(f.identity).toHaveBeenCalledTimes(1);
 expect(f.identity).toHaveBeenCalledWith(null);
});

it("ignores an observation body that settles after its confirmation deadline",async()=>{
 const f=fixture();await f.supervisor.bootstrap();
 const body=deferred<string>(),late=observation(B);
 late.text=jest.fn(()=>body.promise);
 f.transport.mockResolvedValueOnce(late);
 f.supervisor.pause();
 const foreground=f.supervisor.foreground();
 await tick();
 expect(late.text).toHaveBeenCalledTimes(1);
 f.timers.find(timer=>timer.active&&timer.ms===2000)!.run();
 await expect(foreground).resolves.toMatchObject({kind:"held"});
 body.resolve(JSON.stringify({version:1,authenticated:true,binding:B}));
 await tick();
 expect(f.supervisor.snapshot()).toMatchObject({identity:{binding:A,generation:1},observedBinding:A,availability:"foreground"});
 expect(f.identity).toHaveBeenCalledTimes(1);
});

it("does not retry an initial observation after revocation during retry backoff",async()=>{
 const f=fixture(),backoff=deferred<void>();
 f.transport.mockResolvedValueOnce(response("unavailable",A,503));
 jest.spyOn(f.clock,"sleep").mockImplementationOnce(()=>backoff.promise);
 const initial=f.supervisor.bootstrap();
 await tick();
 expect(f.clock.sleep).toHaveBeenCalledWith(1000);
 f.supervisor.invalidate();
 backoff.resolve();
 await expect(initial).resolves.toBe("stale");
 expect(f.transport).toHaveBeenCalledTimes(1);
 expect(f.supervisor.snapshot()).toMatchObject({identity:null,reason:"revoked"});
});

it("requires a current foreground owner for root readiness and ordinary requests",async()=>{
 const f=fixture();
 await expect(f.supervisor.authenticate("/hv/login/",{method:"POST"})).resolves.toMatchObject({kind:"stale"});
 await expect(f.supervisor.request("/hv/tasks/")).rejects.toThrow("session-unavailable");
 await f.supervisor.bootstrap();f.supervisor.pause();
 expect(f.supervisor.markRootReady(f.supervisor.snapshot().generation)).toBe(false);
 await expect(f.supervisor.request("/hv/tasks/")).rejects.toThrow("session-unavailable");
 await f.supervisor.foreground();
 expect(f.supervisor.markRootReady(f.supervisor.snapshot().generation)).toBe(true);
 expect(f.supervisor.snapshot().rootReady).toBe(true);
});

it("bounds admitted credential clears while native storage is still busy",async()=>{
 const f=fixture(),blocked=deferred<void>();
 await f.supervisor.bootstrap();
 const lease=f.supervisor.lease(()=>true);
 f.store.clear.mockImplementationOnce(()=>blocked.promise);
 const receipts=Array.from({length:64},()=>({}));
 const admitted=receipts.map(receipt=>lease.clearCredential(receipt));
 await tick();
 expect(f.store.clear).toHaveBeenCalledTimes(1);
 await expect(lease.clearCredential({})).resolves.toBe("capacity");
 expect(f.store.clear).toHaveBeenCalledTimes(1);
 blocked.resolve();
 await expect(Promise.all(admitted)).resolves.toEqual(Array(64).fill("cleared"));
 expect(f.store.clear).toHaveBeenCalledTimes(64);
 await expect(lease.clearCredential({})).resolves.toBe("cleared");
 expect(f.store.clear).toHaveBeenCalledTimes(65);
});


it('delivers negotiated seed only for the published identity and checked ordinary response, with no extra request',async()=>{
 const seed=jest.fn(),f=fixture(seed),boot=observation();boot.headers.set('X-HyperTodo-Realtime-Features','changes-v2');boot.headers.set('X-HyperTodo-Mutation-Seed','a'.repeat(32));f.transport.mockResolvedValueOnce(boot);
 await f.supervisor.bootstrap();expect(seed).toHaveBeenCalledWith('a'.repeat(32),f.supervisor.snapshot().identity);
 expect(new Headers(f.transport.mock.calls[0][1].headers).get('X-HyperTodo-Realtime-Features')).toBe('changes-v2');
 const next=response('<view/>');next.headers.set('X-HyperTodo-Realtime-Features','changes-v2');next.headers.set('X-HyperTodo-Mutation-Seed','b'.repeat(32));f.transport.mockResolvedValueOnce(next);
 await f.supervisor.request('/hv/tasks/');expect(seed).toHaveBeenLastCalledWith('b'.repeat(32),f.supervisor.snapshot().identity);expect(f.transport).toHaveBeenCalledTimes(2);
});

it.each(['foreign','binding','old-generation','no-feature'])('does not admit ordinary seed from %s',async kind=>{
 const seed=jest.fn(),f=fixture(seed);await f.supervisor.bootstrap();
 const bad=response('<view/>',kind==='binding'?B:A);bad.headers.set('X-HyperTodo-Mutation-Seed','b'.repeat(32));
 if(kind!=='no-feature')bad.headers.set('X-HyperTodo-Realtime-Features','changes-v2');
 if(kind==='foreign')Object.defineProperty(bad,'url',{value:'https://foreign.test/hv/tasks/'});
 const pending=deferred<Response>();f.transport.mockImplementationOnce(()=>pending.promise);
 const request=f.supervisor.request('/hv/tasks/');await tick();if(kind==='old-generation')f.supervisor.invalidate();pending.resolve(bad);await request.catch(()=>{});
 expect(seed).not.toHaveBeenCalled();
});

it("rejects foreign origins and auth POSTs on the ordinary port before transport",async()=>{
 const {supervisor,transport}=fixture();await supervisor.bootstrap();
 for(const url of ["https://foreign.test/hv/tasks/","https://user:secret@app.test/hv/tasks/","/admin/"])await expect(supervisor.request(url)).rejects.toThrow();
 await expect(supervisor.request("/hv/login/",{method:"POST"})).rejects.toThrow();expect(transport).toHaveBeenCalledTimes(1);
});

it("rejects fragments and out-of-scope paths before admitting an ordinary request",async()=>{
 const {supervisor,transport}=fixture();await supervisor.bootstrap();
 for(const url of ["/hv/tasks/#private","/hv/../admin/","https://user@app.test/hv/tasks/"]){
  await expect(supervisor.request(url)).rejects.toThrow("unsupported-request");
 }
 expect(transport).toHaveBeenCalledTimes(1);
});

it("preserves caller Origin and Accept while still enforcing the session headers",async()=>{
 const {supervisor,transport}=fixture();await supervisor.bootstrap();
 await supervisor.request("/hv/tasks/",{headers:{Origin:ORIGIN,Accept:"application/custom+xml"}});
 const headers=new Headers(transport.mock.calls[1][1].headers);
 expect(headers.get("Origin")).toBe(ORIGIN);
 expect(headers.get("Accept")).toBe("application/custom+xml");
 expect(headers.get(H.expected)).toBe(A);
 expect(headers.get("Cache-Control")).toBe("no-store");
});

it("forwards a signal that was already aborted before a request starts",async()=>{
 const {supervisor,transport}=fixture();await supervisor.bootstrap();
 const controller=new AbortController();controller.abort();
 transport.mockImplementationOnce(async(_url,init)=>{
  expect(init.signal?.aborted).toBe(true);
  throw new Error("caller cancelled");
 });
 await expect(supervisor.request("/hv/tasks/",{signal:controller.signal})).rejects.toThrow("caller cancelled");
 expect(transport).toHaveBeenCalledTimes(2);
});

it("rejects a response without its final URL before exposing its body or theme",async()=>{
 const {supervisor,transport,theme}=fixture();await supervisor.bootstrap();
 const invalid={...response("private"),url:""} as Response;
 transport.mockResolvedValueOnce(invalid);
 await expect(supervisor.request("/hv/tasks/")).rejects.toThrow("untrusted-response");
 expect(invalid.text).not.toHaveBeenCalled();
 expect(theme).not.toHaveBeenCalled();
});

it("does not publish an initial identity if the app pauses while observation is in flight",async()=>{
 const {supervisor,transport,identity}=fixture();
 const pending=deferred<Response>();transport.mockImplementationOnce(()=>pending.promise);
 const bootstrap=supervisor.bootstrap();await tick();supervisor.pause();
 pending.resolve(observation());
 await expect(bootstrap).resolves.toBe("uncertain");
 expect(supervisor.snapshot()).toMatchObject({identity:null,availability:"paused"});
 expect(identity).not.toHaveBeenCalled();
});

it("does not let a throwing source predicate authorize a native lease",async()=>{
 const {supervisor,store}=fixture();await supervisor.bootstrap();
 const lease=supervisor.lease(()=>{throw new Error("source removed");});
 expect(lease.isCurrent()).toBe(false);
 await expect(lease.clearCredential({})).resolves.toBe("stale");
 expect(store.clear).not.toHaveBeenCalled();
});

it("returns a retired effect for unknown receipts and a stale lease before bootstrap",async()=>{
 const {supervisor,store}=fixture();
 await expect(supervisor.consumeEffect({})).resolves.toBe("retired");
 const lease=supervisor.lease(()=>true);
 expect(lease.isCurrent()).toBe(false);
 await expect(lease.clearCredential({})).resolves.toBe("stale");
 expect(store.clear).not.toHaveBeenCalled();
});

it("checks response ownership before body or theme, preserving request metadata",async()=>{
 const {supervisor,transport,theme}=fixture();await supervisor.bootstrap();const wrong=response("private B",B);transport.mockResolvedValueOnce(wrong);
 await expect(supervisor.request("/hv/tasks/?tag=a&tag=b",{method:"POST",body:"csrf=kept&a=%2B",headers:{"X-App-Version":"v","X-CSRFToken":"csrf",[H.expected]:B}})).rejects.toThrow();
 const init=transport.mock.calls[1][1];expect(init.body).toBe("csrf=kept&a=%2B");expect(new Headers(init.headers).get(H.expected)).toBe(A);expect(new Headers(init.headers).get("X-App-Version")).toBe("v");
 expect(wrong.text).not.toHaveBeenCalled();expect(theme).not.toHaveBeenCalled();
});

// The backend runs each /hv/ request in the zone named by X-Timezone (backend/todo/middleware.py), so the supervisor, which
// prepares every request the app sends, states the device zone itself and never relays one a caller supplied.
function deviceZone(zone:unknown){return jest.spyOn(Intl,"DateTimeFormat").mockImplementation(()=>({resolvedOptions:()=>({timeZone:zone})}) as unknown as Intl.DateTimeFormat);}

it("sends the device time zone on the observation, ordinary and authentication requests",async()=>{
 const spy=deviceZone("Europe/Madrid");
 try{
  const {supervisor,transport}=fixture();await supervisor.bootstrap();await supervisor.request("/hv/tasks/");
  await expect(supervisor.authenticate("/hv/login/",{method:"POST",body:"username=a&password=b"})).resolves.toMatchObject({kind:"transition"});
  const urls=transport.mock.calls.map(([url])=>new URL(url).pathname);
  expect(urls).toEqual(expect.arrayContaining(["/hv/session-state/","/hv/tasks/","/hv/login/"]));
  for(const [,init] of transport.mock.calls)expect(new Headers(init.headers).get("X-Timezone")).toBe("Europe/Madrid");
 }finally{spy.mockRestore();}
});

it("replaces a caller-supplied time zone with the device zone",async()=>{
 const spy=deviceZone("Europe/Madrid");
 try{
  const {supervisor,transport}=fixture();await supervisor.bootstrap();await supervisor.request("/hv/tasks/",{headers:{"X-Timezone":"Asia/Tokyo"}});
  expect(new Headers(transport.mock.calls[1][1].headers).get("X-Timezone")).toBe("Europe/Madrid");
 }finally{spy.mockRestore();}
});

it.each([undefined,"","Europe/Mad rid","+01:00","Europe/"+"a".repeat(58)])("sends no time zone, not even a caller-supplied one, when the device reports %j",async(value)=>{
 const spy=deviceZone(value);
 try{
  const {supervisor,transport}=fixture();await supervisor.bootstrap();await supervisor.request("/hv/tasks/",{headers:{"X-Timezone":"Asia/Tokyo"}});
  expect(transport).toHaveBeenCalledTimes(2);
  for(const [,init] of transport.mock.calls)expect(new Headers(init.headers).has("X-Timezone")).toBe(false);
 }finally{spy.mockRestore();}
});

it.each(["redirected","foreign-url"])("rejects %s responses before body or effects",async(kind)=>{
 const {supervisor,transport,theme}=fixture();await supervisor.bootstrap();const bad={...response("private"),...(kind==="redirected"?{redirected:true}:{url:"https://foreign.test/hv/"})} as Response;transport.mockResolvedValueOnce(bad);
 await expect(supervisor.request("/hv/tasks/")).rejects.toThrow();expect(bad.text).not.toHaveBeenCalled();expect(theme).not.toHaveBeenCalled();
});

it("returns an unread genuine response and rejects its old body after identity invalidation",async()=>{
 const {supervisor,transport,theme}=fixture();await supervisor.bootstrap();const body=deferred<string>();const raw={...response(""),text:jest.fn(()=>body.promise)} as Response;transport.mockResolvedValueOnce(raw);
 const result=await supervisor.request("/hv/tasks/");expect(raw.text).not.toHaveBeenCalled();expect(theme).toHaveBeenCalledWith("dark");const reading=result.text();supervisor.invalidate();body.resolve("old XML");await expect(reading).rejects.toThrow();
});

it("auth waits for admitted ordinary POST settlement, snapshots form/options and never replays",async()=>{
 const {supervisor,transport,store}=fixture();await supervisor.bootstrap();const post=deferred<Response>();transport.mockImplementationOnce(()=>post.promise);
 const ordinary=supervisor.request("/hv/settings/",{method:"POST",body:"avatar=kept"});const options={method:"POST",body:"username=B&csrf=kept",headers:{"X-CSRFToken":"original"}};
 const auth=supervisor.authenticate("/hv/login/",options);options.body="mutated";options.headers["X-CSRFToken"]="mutated";await tick();expect(transport).toHaveBeenCalledTimes(2);
 await expect(supervisor.authenticate("/hv/login/",{method:"POST"})).resolves.toMatchObject({kind:"busy"});
 post.resolve(response("old settings"));await ordinary.catch(()=>{});const result=await auth;
 expect(result).toMatchObject({kind:"transition",identity:{binding:B,generation:2}});expect(store.save).toHaveBeenCalledTimes(1);
 const sent=transport.mock.calls.find(([url])=>url.endsWith("/login/"))![1];expect(sent.body).toBe("username=B&csrf=kept");expect(new Headers(sent.headers).get("X-CSRFToken")).toBe("original");
 expect(transport.mock.calls.filter(([url])=>url.endsWith("/login/"))).toHaveLength(1);expect(result).not.toHaveProperty("body");
});

it("awaits the accepted credential effect before final confirmation and publication",async()=>{
 const {supervisor,store,transport,identity}=fixture();await supervisor.bootstrap();const native=deferred<void>();store.save.mockImplementationOnce(()=>native.promise);
 const auth=supervisor.authenticate("/hv/login/",{method:"POST"});await tick();expect(store.save).toHaveBeenCalledWith(TOKEN);expect(transport.mock.calls.filter(([url])=>url.endsWith("/session-state/"))).toHaveLength(1);expect(identity).toHaveBeenCalledTimes(1);
 native.resolve();await expect(auth).resolves.toMatchObject({kind:"transition",storage:"stored"});expect(identity).toHaveBeenCalledTimes(2);
});

it("never adopts unexpected A after capturing successful B, nor executes another POST",async()=>{
 const {supervisor,transport,store,identity}=fixture();await supervisor.bootstrap();transport.mockImplementationOnce(async()=>response(login,B,200,"password-ok"));
 await expect(supervisor.authenticate("/hv/login/",{method:"POST"})).resolves.toMatchObject({kind:"uncertain"});
 expect(identity.mock.calls.filter(([value])=>value?.binding===B)).toHaveLength(0);expect(supervisor.snapshot()).toMatchObject({availability:"uncertain",identity:null,observedBinding:A});expect(store.save).toHaveBeenCalledTimes(1);
 expect(transport.mock.calls.filter(([url])=>url.endsWith("/login/"))).toHaveLength(1);
});

it.each([["password",422,"password-invalid",false],["password",429,"password-throttled",false],["password",403,"",false],["biometric",401,"biometric-invalid",true],["biometric",429,"biometric-throttled",false]] as const)("preserves %s/%s panels and credential clear policy",async(kind,status,outcome,clear)=>{
 const {supervisor,setAuth,store,identity}=fixture();await supervisor.bootstrap();const body=status===403?"CSRF refusal":panel(clear);setAuth(status,outcome,body);
 const result=await supervisor.authenticate(kind==="password"?"/hv/login/":"/hv/biometric/login/",{method:"POST"});expect(result).toMatchObject({kind:status===403?"refused":"panel",status,body});
 expect(store.save).not.toHaveBeenCalled();expect(store.clear).toHaveBeenCalledTimes(clear?1:0);expect(identity).toHaveBeenCalledTimes(1);expect(supervisor.snapshot().identity?.binding).toBe(A);
 // A refused attempt is an ordinary panel: no uncertainty shield, same owner.
 expect(supervisor.snapshot()).toMatchObject({availability:"foreground",reason:null,generation:1});
 if(result.kind==="panel"&&clear){await supervisor.consumeEffect(result.receipt);expect(store.clear).toHaveBeenCalledTimes(1);}
});

it("fails closed on a 429 without the exact throttle outcome: shielded, no panel, nothing stored or published",async()=>{
 const {supervisor,setAuth,store,identity}=fixture();await supervisor.bootstrap();setAuth(429,"password-unknown",panel());
 await expect(supervisor.authenticate("/hv/login/",{method:"POST"})).resolves.toMatchObject({kind:"uncertain"});
 expect(supervisor.snapshot()).toMatchObject({availability:"uncertain",reason:"network-uncertain"});
 expect(store.save).not.toHaveBeenCalled();expect(store.clear).not.toHaveBeenCalled();expect(identity).toHaveBeenCalledTimes(1);
});

it("retains biometric enrollment on logout and clears password opt-out only once",async()=>{
 const first=fixture();await first.supervisor.bootstrap();first.setAuth(200,"logout-ok",logout);await expect(first.supervisor.authenticate("/hv/logout/",{method:"POST"})).resolves.toMatchObject({kind:"transition"});expect(first.store.clear).not.toHaveBeenCalled();
 const second=fixture();await second.supervisor.bootstrap();second.setAuth(200,"password-ok",login.replace(TOKEN,""));await second.supervisor.authenticate("/hv/login/",{method:"POST"});expect(second.store.clear).toHaveBeenCalledTimes(1);
});

it.each(["oversized","wrong-outcome","missing-binding"])("invalid auth %s cannot store or publish and never trusts Content-Length",async(kind)=>{
 const {supervisor,transport,store,identity}=fixture();await supervisor.bootstrap();const bad=response(kind==="oversized"?login+"é".repeat(131072):login,kind==="missing-binding"?"":B,200,kind==="wrong-outcome"?"biometric-ok":"password-ok");bad.headers.set("Content-Length","1");transport.mockResolvedValueOnce(bad);
 await expect(supervisor.authenticate("/hv/login/",{method:"POST"})).resolves.toMatchObject({kind:"uncertain"});expect(store.save).not.toHaveBeenCalled();expect(store.clear).not.toHaveBeenCalled();expect(identity.mock.calls.filter(([value])=>value?.binding===B)).toHaveLength(0);
});

it("holds background success B, confirms B before storage and again before publish",async()=>{
 const {supervisor,transport,store,identity,setBinding}=fixture();await supervisor.bootstrap();const post=deferred<Response>();transport.mockImplementationOnce(()=>post.promise);const auth=supervisor.authenticate("/hv/login/",{method:"POST"});await tick();supervisor.pause();setBinding(B);post.resolve(response(login,B,200,"password-ok"));
 await expect(auth).resolves.toMatchObject({kind:"held"});expect(store.save).not.toHaveBeenCalled();expect(identity).toHaveBeenCalledTimes(1);
 const order:string[]=[];transport.mockImplementation(async()=>{order.push("confirm");return observation(B);});store.save.mockImplementation(async()=>{order.push("store");});
 await expect(supervisor.foreground()).resolves.toMatchObject({kind:"transition"});expect(order).toEqual(["confirm","store","confirm"]);expect(identity).toHaveBeenCalledTimes(2);
});

it("does not store held B when foreground confirms a different identity",async()=>{
 const {supervisor,transport,store}=fixture();await supervisor.bootstrap();const post=deferred<Response>();transport.mockImplementationOnce(()=>post.promise);const auth=supervisor.authenticate("/hv/login/",{method:"POST"});await tick();supervisor.pause();post.resolve(response(login,B,200,"password-ok"));await auth;
 await expect(supervisor.foreground()).resolves.toMatchObject({kind:"uncertain"});expect(store.save).not.toHaveBeenCalled();expect(supervisor.snapshot().identity).toBeNull();
});

it("pause retains generation/tree and admitted writes, confirms before releasing theme or body",async()=>{
 const {supervisor,transport,theme,identity}=fixture();await supervisor.bootstrap();const post=deferred<Response>();transport.mockImplementationOnce(()=>post.promise);const pending=supervisor.request("/hv/preferences/",{method:"POST",body:"theme=dark"});supervisor.pause();post.resolve(response("kept draft response"));await tick();
 expect(theme).not.toHaveBeenCalled();expect(supervisor.snapshot()).toMatchObject({availability:"paused",identity:{generation:1,binding:A}});
 await supervisor.foreground();expect(await (await pending).text()).toBe("kept draft response");expect(identity).toHaveBeenCalledTimes(1);expect(theme).toHaveBeenCalledTimes(1);
});

it("native leases resume only for same identity and live source; old completions cannot affect B",async()=>{
 const {supervisor}=fixture();await supervisor.bootstrap();let alive=true;const lease=supervisor.lease(()=>alive);expect(lease.isCurrent()).toBe(true);supervisor.pause();expect(lease.isCurrent()).toBe(false);await supervisor.foreground();expect(lease.isCurrent()).toBe(true);alive=false;expect(lease.isCurrent()).toBe(false);
 const old=supervisor.lease(()=>true);await supervisor.authenticate("/hv/login/",{method:"POST"});expect(old.isCurrent()).toBe(false);
});

it("auth deadline shields immediately but confirms only after actual transport settles",async()=>{
 const {supervisor,transport,timers,store}=fixture();await supervisor.bootstrap();const post=deferred<Response>();transport.mockImplementationOnce(()=>post.promise);const result=supervisor.authenticate("/hv/login/",{method:"POST"});await tick();timers.find(timer=>timer.ms===30000&&timer.active)!.run();
 expect(supervisor.snapshot().availability).toBe("uncertain");expect(transport).toHaveBeenCalledTimes(2);expect(transport.mock.calls[1][1].signal?.aborted).toBe(true);await expect(supervisor.authenticate("/hv/login/",{method:"POST"})).resolves.toMatchObject({kind:"busy"});
 post.resolve(response(login,B,200,"password-ok"));await expect(result).resolves.toMatchObject({kind:"uncertain"});expect(store.save).not.toHaveBeenCalled();expect(transport.mock.calls.filter(([url])=>url.endsWith("/login/"))).toHaveLength(1);
});

it("bounds failed reconciliation at three real GET attempts without adopting any identity",async()=>{
 const {supervisor,transport,clock}=fixture();await supervisor.bootstrap();transport.mockRejectedValue(new Error("offline"));
 await expect(supervisor.authenticate("/hv/login/",{method:"POST"})).resolves.toMatchObject({kind:"uncertain"});
 expect(transport.mock.calls.filter(([url])=>url.endsWith("/session-state/"))).toHaveLength(4);expect(clock.sleep).toHaveBeenCalledWith(1000);expect(clock.sleep).toHaveBeenCalledWith(2000);expect(supervisor.snapshot().availability).toBe("uncertain");
});

it("holds an unread response across pause until foreground confirmation, rather than failing a retained draft",async()=>{
 const {supervisor,transport}=fixture();await supervisor.bootstrap();const raw=response("kept XML");transport.mockResolvedValueOnce(raw);const result=await supervisor.request("/hv/tasks/");supervisor.pause();const body=result.text();await tick();expect(raw.text).not.toHaveBeenCalled();await supervisor.foreground();await expect(body).resolves.toBe("kept XML");
});

it("a queued accepted effect waits for foreground confirmation, not merely foreground notification",async()=>{
 const queued:Array<(store:{save:(token:string)=>Promise<void>;clear:()=>Promise<void>})=>Promise<void>>=[];const done=deferred<void>();
 let binding=A;const order:string[]=[];const store={save:jest.fn(async()=>{order.push("store");}),clear:jest.fn(async()=>{})};
 const transport=jest.fn(async(url:string)=>{if(url.endsWith("/session-state/")){order.push("confirm");return observation(binding);}binding=B;return response(login,B,200,"password-ok");});
 const supervisor=createSessionSupervisor({origin:ORIGIN,transport,storage:{enqueue:job=>{queued.push(job);return done.promise;}},stopStream:()=>{},onIdentity:()=>{},onTheme:()=>{}});
 await supervisor.bootstrap();order.length=0;const auth=supervisor.authenticate("/hv/login/",{method:"POST"});await tick();supervisor.pause();
 const job=queued[0](store);await tick();expect(store.save).not.toHaveBeenCalled();const foreground=supervisor.foreground();await job;done.resolve();
 await expect(auth).resolves.toMatchObject({kind:"transition"});await foreground;expect(order).toEqual(["confirm","store","confirm"]);
});

it("allows explicit abandonment only after auth/native settlement, not as rollback or replay",async()=>{
 const {supervisor,store,transport}=fixture();await supervisor.bootstrap();const native=deferred<void>();store.save.mockImplementationOnce(()=>native.promise);
 const auth=supervisor.authenticate("/hv/login/",{method:"POST"});await tick();expect(supervisor.abandonTransition()).toBe(false);
 supervisor.pause();native.resolve();await expect(auth).resolves.toMatchObject({kind:"held"});expect(supervisor.abandonTransition()).toBe(true);
 expect(transport.mock.calls.filter(([url])=>url.endsWith("/login/"))).toHaveLength(1);expect(supervisor.snapshot().availability).toBe("paused");
});

it("rejects stale auth body and never clears the newer owner's credential",async()=>{
 const {supervisor,transport,store}=fixture();await supervisor.bootstrap();const body=deferred<string>();transport.mockResolvedValueOnce({...response("",B,200,"password-ok"),text:()=>body.promise} as Response);
 const old=supervisor.authenticate("/hv/login/",{method:"POST"});await tick();supervisor.invalidate();body.resolve(login);await expect(old).resolves.toMatchObject({kind:"stale"});expect(store.save).not.toHaveBeenCalled();expect(store.clear).not.toHaveBeenCalled();
});

it("owns a same-session settings credential clear exactly once without advancing identity",async()=>{
 const {supervisor,store,identity}=fixture();await supervisor.bootstrap();const lease=supervisor.lease(()=>true),receipt={};
 await expect(lease.clearCredential(receipt)).resolves.toBe("cleared");await expect(lease.clearCredential(receipt)).resolves.toBe("cleared");expect(store.clear).toHaveBeenCalledTimes(1);expect(identity).toHaveBeenCalledTimes(1);
});

it("auth waits for an already admitted native clear, so A cannot clear B after publication",async()=>{
 const {supervisor,store,transport}=fixture();await supervisor.bootstrap();const native=deferred<void>();store.clear.mockImplementationOnce(()=>native.promise);const old=supervisor.lease(()=>true);
 const clear=old.clearCredential({});await tick();const auth=supervisor.authenticate("/hv/login/",{method:"POST"});await tick();expect(transport).toHaveBeenCalledTimes(1);
 native.resolve();await clear;await auth;expect(store.clear).toHaveBeenCalledTimes(1);expect(store.save).toHaveBeenCalledTimes(1);await expect(old.clearCredential({})).resolves.toBe("stale");expect(store.clear).toHaveBeenCalledTimes(1);
});

it("ignores a confirmation that completes after its deadline and a newer confirmed observation",async()=>{
 const {supervisor,transport,timers}=fixture();await supervisor.bootstrap();supervisor.pause();const late=deferred<Response>();transport.mockImplementationOnce(()=>late.promise);const resumed=supervisor.foreground();await tick();timers.find(timer=>timer.active&&timer.ms===2000)!.run();await resumed;
 expect(supervisor.snapshot().identity?.binding).toBe(A);late.resolve(observation(B));await tick();expect(supervisor.snapshot()).toMatchObject({identity:{binding:A,generation:1},observedBinding:A,availability:"foreground"});
});

it("a queued settings clear remains held until foreground confirms the same binding",async()=>{
 let job!:(store:{save:(token:string)=>Promise<void>;clear:()=>Promise<void>})=>Promise<void>;const done=deferred<void>();let binding=A;
 const store={save:jest.fn(async()=>{}),clear:jest.fn(async()=>{})};const transport=jest.fn(async()=>observation(binding));
 const supervisor=createSessionSupervisor({origin:ORIGIN,transport,storage:{enqueue:value=>{job=value;return done.promise;}},stopStream:()=>{},onIdentity:()=>{},onTheme:()=>{}});
 await supervisor.bootstrap();const clear=supervisor.lease(()=>true).clearCredential({});supervisor.pause();const running=job(store);await tick();binding=B;await supervisor.foreground();await running;done.resolve();await clear;
 expect(store.clear).not.toHaveBeenCalled();expect(supervisor.snapshot().identity).toBeNull();
});

it("foreground confirms the pre-auth owner while an admitted paused settings effect holds the mutation barrier",async()=>{
 const start=deferred<void>();let tail=Promise.resolve();let first=true,binding=A;const order:string[]=[];
 const store={save:jest.fn(async()=>{order.push("store");}),clear:jest.fn(async()=>{order.push("clear");})};
 const storage={enqueue:(job:(value:typeof store)=>Promise<void>)=>{const delay=first;first=false;const result=tail.then(async()=>{if(delay)await start.promise;await job(store);});tail=result.then(()=>{},()=>{});return result;}};
 const transport=jest.fn(async(url:string)=>{if(url.endsWith("/session-state/")){order.push("confirm");return observation(binding);}order.push("post");binding=B;return response(login,B,200,"password-ok");});
 const supervisor=createSessionSupervisor({origin:ORIGIN,transport,storage,stopStream:()=>{},onIdentity:()=>{},onTheme:()=>{}});
 await supervisor.bootstrap();order.length=0;const clear=supervisor.lease(()=>true).clearCredential({});const auth=supervisor.authenticate("/hv/login/",{method:"POST"});supervisor.pause();start.resolve();await tick();await supervisor.foreground();await clear;await auth;
 expect(order).toEqual(["confirm","clear","post","store","confirm"]);
});


it.each(["password","logout"] as const)("requires confirmed authentication state to agree with %s success",async(kind)=>{
 const {supervisor,transport,identity}=fixture();await supervisor.bootstrap();
 transport.mockImplementation(async(url)=>url.endsWith("/session-state/")?observation(B,kind==="logout"):response(kind==="logout"?logout:login,B,200,kind==="logout"?"logout-ok":"password-ok"));
 await expect(supervisor.authenticate(kind==="logout"?"/hv/logout/":"/hv/login/",{method:"POST"})).resolves.toMatchObject({kind:"uncertain"});
 expect(identity.mock.calls.filter(([value])=>value?.binding===B)).toHaveLength(0);
});


it("keeps the unsettled auth POST barrier after privacy invalidation",async()=>{
 const {supervisor,transport}=fixture();await supervisor.bootstrap();const late=deferred<Response>();transport.mockImplementationOnce(()=>late.promise);
 const first=supervisor.authenticate("/hv/login/",{method:"POST",body:"username=first"});await tick();supervisor.invalidate();
 const second=supervisor.authenticate("/hv/login/",{method:"POST",body:"username=second"});await tick();
 const postsBeforeSettlement=transport.mock.calls.filter(([url])=>url.endsWith("/login/")).length;
 late.resolve(response(login,B,200,"password-ok"));const [old,next]=await Promise.all([first,second]);
 expect(postsBeforeSettlement).toBe(1);expect(old.kind).toBe("stale");expect(next.kind).toBe("busy");
 await expect(supervisor.authenticate("/hv/login/",{method:"POST",body:"username=unowned"})).resolves.toMatchObject({kind:"stale"});
 const recovery=await supervisor.beginRecovery();expect(recovery.kind).toBe("recovery");if(recovery.kind!=="recovery")throw new Error("Expected explicit recovery");
 const deliberate=await recovery.handle.authenticate("/hv/login/",{method:"POST",body:"username=deliberate"});
 expect(deliberate.kind).toBe("transition");expect(transport.mock.calls.filter(([url])=>url.endsWith("/login/"))).toHaveLength(2);
});

it("does not start queued settings clear during unconfirmed identity reconciliation",async()=>{
 const confirm=deferred<Response>(),completion=deferred<void>();let observations=0;
 const jobs:Array<(store:{save(token:string):Promise<void>;clear():Promise<void>})=>Promise<void>>=[];
 const store={save:jest.fn(async(_token:string)=>{}),clear:jest.fn(async()=>{})},theme=jest.fn();
 const transport=jest.fn(async(url:string)=>url.endsWith("/session-state/")?(++observations===1?observation(A):confirm.promise):response("unexpected B",B));
 const supervisor=createSessionSupervisor({origin:ORIGIN,transport,storage:{enqueue:job=>{jobs.push(job);return completion.promise;}},clock:{schedule:()=>()=>{},sleep:async()=>{}},onIdentity:()=>{},onTheme:theme,stopStream:()=>{}});
 await supervisor.bootstrap();const clear=supervisor.lease(()=>true).clearCredential({});const request=supervisor.request("/hv/tasks/").catch(()=>{});await tick();
 expect(supervisor.snapshot().availability).toBe("uncertain");const running=jobs[0](store);await tick();const writesBeforeConfirmation=store.clear.mock.calls.length;
 confirm.resolve(observation(B));await running;completion.resolve();await Promise.all([clear,request]);
 expect(writesBeforeConfirmation).toBe(0);expect(store.clear).not.toHaveBeenCalled();expect(theme).not.toHaveBeenCalled();
});

it.each([A,B])("confirms %s after pause during an already started biometric panel clear",async(binding)=>{
 const {supervisor,transport,store,setBinding,setAuth}=fixture();await supervisor.bootstrap();setAuth(401,"biometric-invalid",panel(true));
 const native=deferred<void>();store.clear.mockImplementationOnce(()=>native.promise);
 const auth=supervisor.authenticate("/hv/biometric/login/",{method:"POST"});await tick();expect(store.clear).toHaveBeenCalledTimes(1);
 supervisor.pause();setBinding(binding);const resumed=supervisor.foreground();await tick();native.resolve();const [result]=await Promise.all([auth,resumed]);
 expect(transport.mock.calls.filter(([url])=>url.endsWith("/session-state/"))).toHaveLength(2);
 expect(result.kind).toBe(binding===A?"panel":"uncertain");
 if(binding===A){expect(supervisor.snapshot().identity?.binding).toBe(A);expect(supervisor.snapshot().availability).toBe("foreground");}
 else expect(supervisor.snapshot().identity).toBeNull();
 expect(store.clear).toHaveBeenCalledTimes(1);
});

it("publishes language only alongside an owned ordinary response, never stale A or observation/auth headers",async()=>{
 const language=jest.fn(),pending=deferred<Response>();let binding=A;
 const transport=jest.fn(async(url:string):Promise<Response>=>url.endsWith('/session-state/')?observation(binding):pending.promise);
 const supervisor=createSessionSupervisor({origin:ORIGIN,transport,storage:{enqueue:async job=>job({save:async()=>{},clear:async()=>{}})},stopStream:()=>{},onIdentity:()=>{},onTheme:()=>{},onLanguage:language});
 await supervisor.bootstrap();expect(language).not.toHaveBeenCalled();const first=supervisor.request('/hv/tasks/');await tick();const owned=response('<view/>',A);owned.headers.set('Content-Language','es');pending.resolve(owned);await first;expect(language).toHaveBeenCalledWith('es');
 const stale=deferred<Response>();transport.mockImplementationOnce(()=>stale.promise);const request=supervisor.request('/hv/tasks/');await tick();supervisor.invalidate();binding=B;const late=response('<view/>',A);late.headers.set('Content-Language','en');stale.resolve(late);await expect(request).rejects.toThrow();expect(language.mock.calls).toEqual([['es']]);
});

// Ordinary HXML requests need a deadline of their own: the platform adds none, and a
// request whose headers never arrive would hold the in-flight set, and with it logout
// and recovery, forever.
const settle=(pending:Promise<unknown>)=>pending.then(()=>"settled",(error:Error)=>error.message);

it("bounds an ordinary request: the stalled transport is aborted at the deadline and logout is no longer held",async()=>{
 const {supervisor,transport,timers,setAuth}=fixture();await supervisor.bootstrap();
 transport.mockImplementationOnce(()=>new Promise<Response>(()=>{}));
 const stalled=settle(supervisor.request("/hv/tasks/"));await tick();
 const signal=transport.mock.calls[1][1].signal!;expect(signal.aborted).toBe(false);
 setAuth(200,"logout-ok",logout);const signOut=supervisor.authenticate("/hv/logout/",{method:"POST"});await tick();
 expect(transport.mock.calls.filter(([url])=>url.endsWith("/logout/"))).toHaveLength(0);
 timers.find(timer=>timer.ms===30000&&timer.active)!.run();
 await expect(stalled).resolves.toBe("request-timeout");expect(signal.aborted).toBe(true);
 await expect(signOut).resolves.toMatchObject({kind:"transition"});
 expect(transport.mock.calls.filter(([url])=>url.endsWith("/logout/"))).toHaveLength(1);
});

it("reports the deadline, not the transport's AbortError, when the transport honours the signal",async()=>{
 const {supervisor,transport,timers}=fixture();await supervisor.bootstrap();
 transport.mockImplementationOnce((_url,init)=>new Promise<Response>((_resolve,reject)=>{init.signal!.addEventListener("abort",()=>reject(new Error("AbortError")));}));
 const stalled=settle(supervisor.request("/hv/tasks/"));await tick();
 timers.find(timer=>timer.ms===30000&&timer.active)!.run();
 await expect(stalled).resolves.toBe("request-timeout");expect(supervisor.snapshot()).toMatchObject({availability:"foreground",reason:null});
});

it("lets recovery start again once a stalled request has hit its deadline",async()=>{
 const {supervisor,transport,timers}=fixture();await supervisor.bootstrap();
 transport.mockImplementationOnce(()=>new Promise<Response>(()=>{}));
 const stalled=settle(supervisor.request("/hv/tasks/"));await tick();
 await expect(supervisor.beginRecovery()).resolves.toMatchObject({kind:"busy"});
 timers.find(timer=>timer.ms===30000&&timer.active)!.run();await stalled;
 await expect(supervisor.beginRecovery()).resolves.toMatchObject({kind:"recovery"});
});

it("keeps the caller's own abort working and cancels the deadline once the headers arrive",async()=>{
 const {supervisor,transport,timers}=fixture();await supervisor.bootstrap();
 transport.mockImplementationOnce((_url,init)=>new Promise<Response>((_resolve,reject)=>{init.signal!.addEventListener("abort",()=>reject(new Error("caller-aborted")));}));
 const caller=new AbortController(),aborted=settle(supervisor.request("/hv/tasks/",{signal:caller.signal}));await tick();
 caller.abort();await expect(aborted).resolves.toBe("caller-aborted");
 await supervisor.request("/hv/tasks/");
 expect(timers.filter(timer=>timer.ms===30000&&timer.active)).toHaveLength(0);
});

it("bounds the neutral recovery GET too, so a stalled one cannot block the recovery sign-in",async()=>{
 const {supervisor,transport,timers}=fixture();await supervisor.bootstrap();
 const recovery=await supervisor.beginRecovery();if(recovery.kind!=="recovery")throw new Error("Expected explicit recovery");
 transport.mockImplementationOnce(()=>new Promise<Response>(()=>{}));
 const stalled=settle(recovery.handle.fetch("/hv/recovery/"));await tick();
 const signIn=recovery.handle.authenticate("/hv/login/",{method:"POST"});await tick();
 expect(transport.mock.calls.filter(([url])=>url.endsWith("/login/"))).toHaveLength(0);
 timers.find(timer=>timer.ms===30000&&timer.active)!.run();
 await expect(stalled).resolves.toBe("request-timeout");
 await expect(signIn).resolves.toMatchObject({kind:"transition"});
});

// A response with no binding header at all (a gateway error, a WAF or portal page) says
// nothing about who owns the session. It is rejected, then the owner is re-observed.
it("rejects a binding-less gateway response, then restores the unchanged owner without a manual retry",async()=>{
 const {supervisor,transport,theme,identity}=fixture();await supervisor.bootstrap();
 const gateway=response("<html>Bad gateway</html>",A,502);gateway.headers.delete(H.binding);transport.mockResolvedValueOnce(gateway);
 await expect(supervisor.request("/hv/tasks/")).rejects.toThrow("untrusted-response");
 expect(gateway.text).not.toHaveBeenCalled();expect(theme).not.toHaveBeenCalled();
 expect(supervisor.snapshot()).toMatchObject({availability:"foreground",reason:null,identity:{binding:A,generation:1}});expect(identity).toHaveBeenCalledTimes(1);
 await expect(supervisor.request("/hv/tasks/")).resolves.toBeDefined();
});

it("still revokes the owner when the re-observation after a binding-less response shows another binding",async()=>{
 const {supervisor,transport,setBinding,identity}=fixture();await supervisor.bootstrap();
 const mismatch=response('{"error":"session-binding-mismatch"}',A,409);mismatch.headers.delete(H.binding);transport.mockResolvedValueOnce(mismatch);setBinding(B);
 await expect(supervisor.request("/hv/tasks/")).rejects.toThrow("untrusted-response");
 expect(supervisor.snapshot()).toMatchObject({availability:"uncertain",reason:"identity-mismatch",identity:null});expect(identity).toHaveBeenLastCalledWith(null);
});

it.each([["a different binding",B,200],["a 401 that names the owner",A,401],["a binding-less 401",null,401]] as const)("keeps the shield after %s until an explicit retry confirms the owner",async(_label,binding,status)=>{
 const {supervisor,transport}=fixture();await supervisor.bootstrap();
 const refused=response("<view/>",binding??A,status);if(binding===null)refused.headers.delete(H.binding);transport.mockResolvedValueOnce(refused);
 await expect(supervisor.request("/hv/tasks/")).rejects.toThrow("untrusted-response");
 expect(supervisor.snapshot()).toMatchObject({availability:"uncertain",reason:"identity-mismatch"});
 await expect(supervisor.retryConfirmation()).resolves.toMatchObject({kind:"held"});expect(supervisor.snapshot()).toMatchObject({availability:"foreground",reason:null});
});

it.each([["a 401",A,401],["a different binding",B,200]] as const)("revokes the owner on %s once the observation shows another binding",async(_label,binding,status)=>{
 const {supervisor,transport,setBinding,identity}=fixture();await supervisor.bootstrap();
 transport.mockResolvedValueOnce(response("<view/>",binding,status));setBinding(B);
 await expect(supervisor.request("/hv/tasks/")).rejects.toThrow("untrusted-response");
 expect(supervisor.snapshot()).toMatchObject({availability:"uncertain",reason:"identity-mismatch",identity:null});expect(identity).toHaveBeenLastCalledWith(null);
});

it("rejects unsupported origins and non-string HXML bodies before transport",async()=>{
 const f=fixture();
 expect(()=>createSessionSupervisor({
  origin:"ftp://app.test",transport:f.transport,
  storage:{enqueue:async job=>job({save:async()=>{},clear:async()=>{}})},
  stopStream:()=>{},onIdentity:()=>{},onTheme:()=>{},
 })).toThrow("unsupported-origin");
 await f.supervisor.bootstrap();
 await expect(f.supervisor.request("/hv/tasks/",{method:"POST",body:new FormData()})).rejects.toThrow("unsupported-request-body");
 expect(f.transport).toHaveBeenCalledTimes(1);
 expect(f.supervisor.snapshot()).toMatchObject({availability:"foreground",identity:{binding:A}});
});

it("keeps auth paths explicit and leaves the current identity untouched on an unsupported action",async()=>{
 const f=fixture();
 await expect(f.supervisor.authenticate("/hv/login/",{method:"POST"})).resolves.toMatchObject({kind:"stale"});
 await f.supervisor.bootstrap();
 await expect(f.supervisor.authenticate("/hv/tasks/",{method:"POST"})).rejects.toThrow("auth-unavailable");
 await expect(f.supervisor.authenticate("/hv/login/",{method:"GET"})).rejects.toThrow("auth-unavailable");
 expect(f.transport).toHaveBeenCalledTimes(1);
 expect(f.supervisor.snapshot()).toMatchObject({availability:"foreground",identity:{binding:A}});
});

it("retries malformed and unavailable observations before publishing one confirmed identity",async()=>{
 const f=fixture(), unavailable=response("busy",A,503), malformed=response("not-json",A);
 f.transport.mockResolvedValueOnce(unavailable).mockResolvedValueOnce(malformed);
 await expect(f.supervisor.bootstrap()).resolves.toBe("ready");
 expect(f.transport.mock.calls.filter(([url])=>url.endsWith("/session-state/"))).toHaveLength(3);
 expect(f.clock.sleep).toHaveBeenNthCalledWith(1,1000);
 expect(f.clock.sleep).toHaveBeenNthCalledWith(2,2000);
 expect(unavailable.text).not.toHaveBeenCalled();
 expect(f.identity).toHaveBeenCalledTimes(1);
 expect(f.supervisor.snapshot()).toMatchObject({identity:{binding:A,generation:1},availability:"foreground"});
});

it("never publishes an observation from a redirected response",async()=>{
 const f=fixture(), redirected={...observation(),redirected:true} as Response;
 f.transport.mockResolvedValue(redirected);
 await expect(f.supervisor.bootstrap()).resolves.toBe("uncertain");
 expect(f.transport).toHaveBeenCalledTimes(3);
 expect(redirected.text).not.toHaveBeenCalled();
 expect(f.identity).not.toHaveBeenCalled();
 expect(f.supervisor.snapshot()).toMatchObject({identity:null,availability:"uncertain"});
});

it("contains adapter callback failures without granting request authority",async()=>{
 const f=fixture();
 f.stop.mockImplementation(()=>{throw new Error("stream adapter failed");});
 f.identity.mockImplementationOnce(()=>{throw new Error("UI adapter failed");});
 await f.supervisor.bootstrap();
 expect(f.supervisor.snapshot()).toMatchObject({identity:{binding:A},availability:"uncertain",reason:"invalid-response"});
 await expect(f.supervisor.request("/hv/tasks/")).rejects.toThrow("session-unavailable");
 expect(f.transport).toHaveBeenCalledTimes(1);
 f.supervisor.pause();
 expect(f.supervisor.snapshot().availability).toBe("paused");
});

it("contains a failing optional mutation-seed listener after confirmation",async()=>{
 const seed=jest.fn(()=>{throw new Error("UI observer failed");});
 const f=fixture(seed),observed=observation();
 observed.headers.set("X-HyperTodo-Realtime-Features","changes-v2");
 observed.headers.set("X-HyperTodo-Mutation-Seed","a".repeat(32));
 f.transport.mockResolvedValueOnce(observed);
 await expect(f.supervisor.bootstrap()).resolves.toBe("ready");
 expect(seed).toHaveBeenCalledTimes(1);
 await expect(f.supervisor.request("/hv/tasks/")).resolves.toBeDefined();
 expect(f.supervisor.snapshot()).toMatchObject({availability:"foreground",identity:{binding:A}});
});

it("unsubscribes a session listener before later pause and invalidation notifications",async()=>{
 const f=fixture(),listener=jest.fn(),unsubscribe=f.supervisor.subscribe(listener);
 await f.supervisor.bootstrap();
 expect(listener).toHaveBeenCalled();
 const before=listener.mock.calls.length;
 unsubscribe();f.supervisor.pause();f.supervisor.invalidate();
 expect(listener).toHaveBeenCalledTimes(before);
 expect(f.supervisor.snapshot()).toMatchObject({identity:null,availability:"paused",reason:"revoked"});
});

it("shields a caller-aborted authentication until its real POST settles, without storing credentials",async()=>{
 const f=fixture(),pending=deferred<Response>(),caller=new AbortController();
 await f.supervisor.bootstrap();
 f.transport.mockImplementationOnce(()=>pending.promise);
 const attempt=f.supervisor.authenticate("/hv/login/",{method:"POST",signal:caller.signal});
 await tick();expect(f.transport.mock.calls.filter(([url])=>url.endsWith("/login/"))).toHaveLength(1);
 caller.abort();
 expect(f.supervisor.snapshot()).toMatchObject({availability:"uncertain",reason:"network-uncertain"});
 await expect(f.supervisor.authenticate("/hv/login/",{method:"POST"})).resolves.toMatchObject({kind:"busy"});
 pending.resolve(response(login,B,200,"password-ok"));
 await expect(attempt).resolves.toMatchObject({kind:"uncertain"});
 expect(f.store.save).not.toHaveBeenCalled();expect(f.store.clear).not.toHaveBeenCalled();
 expect(f.transport.mock.calls.filter(([url])=>url.endsWith("/login/"))).toHaveLength(1);
});
