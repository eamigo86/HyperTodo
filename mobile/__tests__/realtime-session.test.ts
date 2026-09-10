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
function fixture(){
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
 const supervisor=createSessionSupervisor({origin:ORIGIN,transport,storage,clock,onIdentity:identity,onTheme:theme,stopStream:stop});
 return{supervisor,transport,store,identity,theme,stop,clock,timers,setBinding:(next:string)=>{binding=next;},setAuth:(code:number,tag:string,body:string)=>{status=code;outcome=tag;authBody=body;}};
}

it("bootstraps only the bounded observation and configures same-origin credentialed requests",async()=>{
 const {supervisor,transport,identity}=fixture();await expect(supervisor.bootstrap()).resolves.toBe("ready");
 expect(supervisor.snapshot()).toMatchObject({availability:"foreground",identity:{binding:A,authenticated:true,generation:1},rootReady:false});
 const init=transport.mock.calls[0][1];expect(init).toMatchObject({credentials:"include",redirect:"error",cache:"no-store",method:"GET"});expect(new Headers(init.headers).get(H.contract)).toBe("realtime-v1");
 expect(identity).toHaveBeenCalledTimes(1);expect(supervisor.markRootReady(0)).toBe(false);expect(supervisor.markRootReady(1)).toBe(true);
});

it("rejects foreign origins and auth POSTs on the ordinary port before transport",async()=>{
 const {supervisor,transport}=fixture();await supervisor.bootstrap();
 for(const url of ["https://foreign.test/hv/tasks/","https://user:secret@app.test/hv/tasks/","/admin/"])await expect(supervisor.request(url)).rejects.toThrow();
 await expect(supervisor.request("/hv/login/",{method:"POST"})).rejects.toThrow();expect(transport).toHaveBeenCalledTimes(1);
});

it("checks response ownership before body or theme, preserving request metadata",async()=>{
 const {supervisor,transport,theme}=fixture();await supervisor.bootstrap();const wrong=response("private B",B);transport.mockResolvedValueOnce(wrong);
 await expect(supervisor.request("/hv/tasks/?tag=a&tag=b",{method:"POST",body:"csrf=kept&a=%2B",headers:{"X-App-Version":"v","X-CSRFToken":"csrf",[H.expected]:B}})).rejects.toThrow();
 const init=transport.mock.calls[1][1];expect(init.body).toBe("csrf=kept&a=%2B");expect(new Headers(init.headers).get(H.expected)).toBe(A);expect(new Headers(init.headers).get("X-App-Version")).toBe("v");
 expect(wrong.text).not.toHaveBeenCalled();expect(theme).not.toHaveBeenCalled();
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

it.each([["password",422,"password-invalid",false],["password",403,"",false],["biometric",401,"biometric-invalid",true],["biometric",429,"biometric-throttled",false]] as const)("preserves %s/%s panels and credential clear policy",async(kind,status,outcome,clear)=>{
 const {supervisor,setAuth,store,identity}=fixture();await supervisor.bootstrap();const body=status===403?"CSRF refusal":panel(clear);setAuth(status,outcome,body);
 const result=await supervisor.authenticate(kind==="password"?"/hv/login/":"/hv/biometric/login/",{method:"POST"});expect(result).toMatchObject({kind:status===403?"refused":"panel",status,body});
 expect(store.save).not.toHaveBeenCalled();expect(store.clear).toHaveBeenCalledTimes(clear?1:0);expect(identity).toHaveBeenCalledTimes(1);expect(supervisor.snapshot().identity?.binding).toBe(A);
 if(result.kind==="panel"&&clear){await supervisor.consumeEffect(result.receipt);expect(store.clear).toHaveBeenCalledTimes(1);}
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
