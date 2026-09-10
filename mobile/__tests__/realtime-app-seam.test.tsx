import "react-native-gesture-handler/jestSetup";
import React from "react";
import {Text} from "react-native";
import {act,fireEvent,render,waitFor} from "@testing-library/react-native";
import {NavigationContainer} from "@react-navigation/native";
import {createStackNavigator} from "@react-navigation/stack";
import {DOMParser} from "@instawork/xmldom";
import type {HvBehavior,HvComponentProps} from "hyperview";
import {createRealtimeGate} from "../src/realtime/gate";
import type {AuthResult} from "../src/realtime/session";
import type {GateAuthPort} from "../src/realtime/auth";

jest.mock("react-native-webview",()=>({WebView:()=>null}));
const Stack=createStackNavigator();const BASE="https://hypertodo.test/hv/login/",HV="https://hyperview.org/hyperview",APP="https://hypertodo.app/components";
const TOKEN="A".repeat(43);
const requestId=(init:RequestInit)=>new Headers(init.headers).get("X-HyperTodo-Request-ID")!;
const panel=(message="Login",clear=false,scope:string|null=null,keyed=false)=>`<view xmlns="${HV}" xmlns:app="${APP}" id="login-panel" ${keyed?`key="auth-panel-${scope}"`:""}>${clear?'<behavior trigger="load" action="store-biometric-token" token="" once="true" immediate="true"/>':''}<text>${message}</text><form id="password-form"><text-field id="username" name="username" placeholder="Username" value="initial"/><text-field id="password" name="password" placeholder="Password" value=""/><text-field hide="true" name="csrfmiddlewaretoken" value="own-csrf"/><switch name="enable_biometrics" value="on"/><view href="/hv/login/" verb="post" action="replace" target="login-panel"><text>Sign in</text></view></form><app:watch/><form id="biometric-form"><text-field id="biometric-token" name="biometric_token" value="" hide="true"/><view><behavior trigger="press" action="capture-submit" target="biometric-token" event-name="biometric-authenticated"/><behavior trigger="on-event" event-name="biometric-authenticated" href="/hv/biometric/login/" verb="post" action="replace" target="login-panel"/><text>Unlock</text></view></form></view>`;
const doc=(id:string,controls="")=>`<doc xmlns="${HV}" xmlns:app="${APP}"><screen><body><app:realtime refresh-href="/hv/tasks/?fragment=list" target="rows" mode="notice"><list id="rows"><item key="one"><app:realtime-page request-id="${id}" page="1"/><text>Initial row</text></item></list>${panel()}<view href="/hv/tasks/next/" verb="post" action="append" target="rows"><text>Ordinary POST</text></view>${controls}</app:realtime></body></screen></doc>`;
const response=(body:string)=>({status:200,ok:true,url:BASE,headers:new Headers({"Content-Type":"application/vnd.hyperview+xml"}),text:async()=>body}) as Response;
const items=(id:string)=>`<items xmlns="${HV}" xmlns:app="${APP}"><item key="two"><app:realtime-page request-id="${id}" page="2"/><text>Added row</text></item></items>`;
function deferred<T>(){let resolve!:(value:T)=>void;const promise=new Promise<T>(yes=>{resolve=yes;});return{promise,resolve};}
function setup(authenticate:GateAuthPort,more:Partial<React.ComponentProps<ReturnType<typeof createRealtimeGate>["Root"]>>={},controls="",onReady=jest.fn()){
 const gate=createRealtimeGate({authenticate,onReady});const errors=jest.fn();
 const transport=jest.fn(async(_input:RequestInfo|URL,init?:RequestInit):Promise<Response>=>{const id=new Headers(init?.headers).get("X-HyperTodo-Request-ID")!;return response(transport.mock.calls.length===1?doc(id,controls):items(id));});
 const screen=render(<NavigationContainer><Stack.Navigator screenOptions={{animationEnabled:false}}><Stack.Screen name="fixture">{()=> <gate.Root entrypointUrl={BASE} fetch={gate.wrapFetch(transport)} formatDate={()=>undefined} onError={errors} {...more} components={[...gate.components,...(more.components??[])]}/>}</Stack.Screen></Stack.Navigator></NavigationContainer>);
 return{gate,screen,transport,errors,onReady};
}

it("uses actual Parser/FormData once and never executes successful transition HXML",async()=>{
 const effect=jest.fn();const authenticate=jest.fn(async():Promise<AuthResult>=>({kind:"transition",identity:{version:1,authenticated:true,binding:"hvs1."+"A".repeat(43),generation:1},storage:"stored"}));
 const {gate,screen,transport}=setup(authenticate,{behaviors:[{action:"store-biometric-token",callback:effect}]});
 try{await screen.findByText("Login");fireEvent.changeText(screen.getByPlaceholderText("Username"),"Ada é");fireEvent.changeText(screen.getByPlaceholderText("Password"),"draft-secret");fireEvent.press(screen.getByText("Sign in"));
  await waitFor(()=>expect(authenticate).toHaveBeenCalledTimes(1));const call=(authenticate.mock.calls as unknown as [string,RequestInit,unknown][])[0];
  expect(call[0]).toBe(BASE);expect(call[1].method).toBe("post");const form=call[1].body as unknown as {getParts?:()=>{fieldName:string;string:string}[];entries:()=>IterableIterator<[string,unknown]>};
  const pairs=form.getParts?form.getParts().map(p=>[p.fieldName,p.string]):Array.from(form.entries());
  expect(pairs).toEqual(expect.arrayContaining([["username","Ada é"],["password","draft-secret"],["csrfmiddlewaretoken","own-csrf"],["enable_biometrics","on"]]));
  expect(new Headers(call[1].headers).get("Accept")).toContain("fragment");expect(Object.getOwnPropertySymbols(call[1])).toHaveLength(0);
  expect(transport).toHaveBeenCalledTimes(1);expect(effect).not.toHaveBeenCalled();expect(gate.snapshot().lastTerminal).toMatchObject({outcome:"no-document",reason:"auth-transition"});
 }finally{screen.unmount();}
});

it.each([422,401,429])("commits the genuine %s panel by exact node layout and permits repeated submit",async(status)=>{
 const receipt={};let current:ReturnType<typeof createRealtimeGate>;const before:number[]=[];
 const Watch=Object.assign(()=>{if(current)before.push(current.snapshot().operations);return null;},{localName:"watch",namespaceURI:APP});
 const auth=jest.fn(async(_url:string,init:RequestInit):Promise<AuthResult>=>({kind:"panel",status,body:panel("Rejected input",false,requestId(init),true),receipt}));
 const {gate,screen,transport}=setup(auth,{components:[Watch]});current=gate;
 try{await screen.findByText("Login");before.length=0;fireEvent.press(screen.getByText("Sign in"));await screen.findByText("Rejected input");
  expect(before).toContain(1);expect(gate.snapshot()).toMatchObject({operations:0,lastTerminal:{outcome:"ack",reason:"auth-panel-layout"}});
  fireEvent.press(screen.getByText("Sign in"));await waitFor(()=>expect(auth).toHaveBeenCalledTimes(2));expect(transport).toHaveBeenCalledTimes(1);
 }finally{screen.unmount();}
});

it("keeps the entered draft and tree for403 without XML ACK or credential effects",async()=>{
 const auth=jest.fn(async():Promise<AuthResult>=>({kind:"refused",status:403,body:"<html>private refusal detail</html>",receipt:{}}));const {gate,screen}=setup(auth);
 try{await screen.findByText("Login");fireEvent.changeText(screen.getByPlaceholderText("Password"),"keep-me");fireEvent.press(screen.getByText("Sign in"));
  await waitFor(()=>expect(gate.snapshot().lastTerminal).toMatchObject({outcome:"no-document",reason:"auth-refused"}));
  expect(screen.getByPlaceholderText("Password").props.value).toBe("keep-me");expect(screen.queryByText("private refusal detail")).toBeNull();expect(gate.snapshot().routes[0]).toMatchObject({notice:true,noticeCode:"auth-refused"});
 }finally{screen.unmount();}
});

it("retains held auth for its exact resume closure and refuses reuse or an old epoch",async()=>{
 let id="";let resume!:(result:AuthResult)=>boolean;const auth=jest.fn(async(_u:string,_i:RequestInit,deliver:(result:AuthResult)=>boolean):Promise<AuthResult>=>{resume=deliver;id=requestId(_i);return{kind:"held"};});const {gate,screen}=setup(auth);
 try{await screen.findByText("Login");fireEvent.press(screen.getByText("Sign in"));await waitFor(()=>expect(auth).toHaveBeenCalledTimes(1));
  expect(gate.snapshot()).toMatchObject({operations:1,lastTerminal:null});await act(async()=>expect(resume({kind:"panel",status:422,body:panel("Held result",false,id,true),receipt:{}})).toBe(true));
  await screen.findByText("Held result");expect(resume({kind:"held"})).toBe(false);
  fireEvent.press(screen.getByText("Sign in"));await waitFor(()=>expect(auth).toHaveBeenCalledTimes(2));act(()=>{gate.resetEpoch();});expect(resume({kind:"panel",status:422,body:panel("Stale",false,id,true),receipt:{}})).toBe(false);expect(screen.queryByText("Stale")).toBeNull();
 }finally{screen.unmount();}
});

it("retains actual draft and admitted POST across pause, denies new taps, then commits once",async()=>{
 const request=deferred<Response>();const {gate,screen,transport}=setup(async()=>({kind:"busy"}));let id="";
 try{await screen.findByText("Login");fireEvent.changeText(screen.getByPlaceholderText("Username"),"retained draft");transport.mockImplementationOnce(async(_u,init)=>{id=new Headers(init?.headers).get("X-HyperTodo-Request-ID")!;return request.promise;});fireEvent.press(screen.getByText("Ordinary POST"));await waitFor(()=>expect(transport).toHaveBeenCalledTimes(2));
  act(()=>{expect(gate.setRetainedPaused(gate.snapshot().epoch,true)).toBe(true);});fireEvent.press(screen.getByText("Ordinary POST"));
  await act(async()=>request.resolve(response(items(id))));expect(screen.queryByText("Added row")).toBeNull();expect(screen.getByPlaceholderText("Username").props.value).toBe("retained draft");expect(transport).toHaveBeenCalledTimes(2);expect(gate.snapshot()).toMatchObject({operations:1,retainedPaused:true});
  await act(async()=>expect(gate.setRetainedPaused(gate.snapshot().epoch,false)).toBe(true));await screen.findByText("Added row");expect(gate.snapshot().operations).toBe(0);expect(transport).toHaveBeenCalledTimes(2);
 }finally{screen.unmount();}
});

it("captures source and one-use biometric submit before native await without global events",async()=>{
 let owned:ReturnType<ReturnType<typeof createRealtimeGate>["bindSource"]>;let submit:((token:string)=>boolean)|null=null;
 const auth=jest.fn(async(_url:string,init:RequestInit):Promise<AuthResult>=>({kind:"panel",status:429,body:panel("Try later",false,requestId(init),true),receipt:{}}));let gate:ReturnType<typeof createRealtimeGate>;
 const behavior:HvBehavior={action:"capture-submit",callback:(element,_update,getRoot,updateRoot)=>{owned=gate.bindSource(element,{getRoot,updateRoot});submit=owned!.bindBiometricSubmit();}};
 const mounted=setup(auth,{behaviors:[behavior]});gate=mounted.gate;
 try{await mounted.screen.findByText("Login");await act(async()=>fireEvent.press(mounted.screen.getByText("Unlock")));expect(owned!.sourceIsCurrent()).toBe(true);
  act(()=>gate.setRetainedPaused(gate.snapshot().epoch,true));expect(owned!.isAlive()).toBe(true);expect(owned!.sourceIsCurrent()).toBe(false);expect(submit!(TOKEN)).toBe(false);
  act(()=>gate.setRetainedPaused(gate.snapshot().epoch,false));await act(async()=>expect(submit!(TOKEN)).toBe(true));await mounted.screen.findByText("Try later");
  expect(auth).toHaveBeenCalledTimes(1);expect((auth.mock.calls as unknown as [string,RequestInit][])[0][0]).toBe("https://hypertodo.test/hv/biometric/login/");expect(submit!(TOKEN)).toBe(false);expect(owned!.isAlive()).toBe(false);
 }finally{mounted.screen.unmount();}
});

it("registers a401 receipt before its actual immediate load callback, without performing another effect",async()=>{
 const receipt=Object.freeze({});const observed:unknown[]=[];let gate:ReturnType<typeof createRealtimeGate>;
 const store:HvBehavior={action:"store-biometric-token",callback:(element,_update,getRoot,updateRoot)=>{const source=gate.bindSource(element,{getRoot,updateRoot});observed.push(source?.effectReceipt());}};
 const auth=jest.fn(async(_url:string,init:RequestInit):Promise<AuthResult>=>({kind:"panel",status:401,body:panel("Reset biometric",true,requestId(init),true),receipt}));const mounted=setup(auth,{behaviors:[store]});gate=mounted.gate;
 try{await mounted.screen.findByText("Login");fireEvent.press(mounted.screen.getByText("Sign in"));await mounted.screen.findByText("Reset biometric");expect(observed).toEqual([receipt]);expect(gate.snapshot().lastTerminal).toMatchObject({reason:"auth-panel-layout"});}
 finally{mounted.screen.unmount();}
});

it("request-scoped public panel keys preserve live biometric callbacks after repeated panel swaps",async()=>{
 let submit:((token:string)=>boolean)|null=null;let gate:ReturnType<typeof createRealtimeGate>;
 const behavior:HvBehavior={action:"capture-submit",callback:(element,_update,getRoot,updateRoot)=>{const source=gate.bindSource(element,{getRoot,updateRoot});if(!source)throw new Error(JSON.stringify({rejection:gate.snapshot().lastRejection,root:getRoot()?.documentElement.localName,boundaries:getRoot()?.getElementsByTagNameNS(APP,"realtime").length,sourceLive:Array.from(getRoot()?.getElementsByTagName("*")??[]).includes(element)}));submit=source.bindBiometricSubmit();}};
 const auth=jest.fn(async(_url:string,init:RequestInit):Promise<AuthResult>=>({kind:"panel",status:429,body:panel("Retry later",false,new Headers(init.headers).get("X-HyperTodo-Request-ID"),true),receipt:{}}));const mounted=setup(auth,{behaviors:[behavior]});gate=mounted.gate;
 try{await mounted.screen.findByText("Login");fireEvent.press(mounted.screen.getByText("Sign in"));await mounted.screen.findByText("Retry later");await act(async()=>fireEvent.press(mounted.screen.getByText("Unlock")));
  await act(async()=>expect(submit!(TOKEN)).toBe(true));await waitFor(()=>expect(auth).toHaveBeenCalledTimes(2));expect(gate.snapshot()).toMatchObject({operations:0,lastTerminal:{reason:"auth-panel-layout"}});
  await act(async()=>fireEvent.press(mounted.screen.getByText("Unlock")));await act(async()=>expect(submit!(TOKEN)).toBe(true));await waitFor(()=>expect(auth).toHaveBeenCalledTimes(3));
 }finally{mounted.screen.unmount();}
});

it("waits for a real matching layout again when pause starts inside the caller onEnd",async()=>{
 let gate:ReturnType<typeof createRealtimeGate>;const ended=jest.fn(()=>{gate.setRetainedPaused(gate.snapshot().epoch,true);});
 const Submit=Object.assign(({onUpdate,element}:HvComponentProps)=><Text onPress={()=>onUpdate("/hv/login/","replace",element,{verb:"post",targetId:"login-panel",onEnd:ended})}>Controlled submit</Text>,{localName:"controlled-submit",namespaceURI:APP});
 const mounted=setup(async(_url,init)=>({kind:"panel",status:422,body:panel("Submitted panel",false,requestId(init),true),receipt:{}}),{components:[Submit]},'<app:controlled-submit/>');gate=mounted.gate;
 try{await mounted.screen.findByText("Login");fireEvent.press(mounted.screen.getByText("Controlled submit"));await mounted.screen.findByText("Submitted panel");
  expect(ended).toHaveBeenCalledTimes(1);expect(gate.snapshot()).toMatchObject({operations:1,retainedPaused:true,lastTerminal:null});
  await act(async()=>gate.setRetainedPaused(gate.snapshot().epoch,false));await waitFor(()=>expect(gate.snapshot()).toMatchObject({operations:0,lastTerminal:{reason:"auth-panel-layout"}}));expect(ended).toHaveBeenCalledTimes(1);
 }finally{mounted.screen.unmount();}
});

it("defers already admitted delayed ordinary work without resubmission",async()=>{
 const auth=jest.fn(async():Promise<AuthResult>=>({kind:"busy"}));const mounted=setup(auth,{},'<view href="/hv/tasks/delayed/" action="append" target="rows" verb="post" delay="20"><text>Delayed POST</text></view>');const {gate,screen,transport}=mounted;
 try{await screen.findByText("Login");await act(async()=>fireEvent.press(screen.getByText("Delayed POST")));expect(gate.snapshot().operations).toBe(1);act(()=>gate.setRetainedPaused(gate.snapshot().epoch,true));
  await act(async()=>{await new Promise(resolve=>setTimeout(resolve,35));});expect(transport).toHaveBeenCalledTimes(1);expect(gate.snapshot().operations).toBe(1);
  await act(async()=>gate.setRetainedPaused(gate.snapshot().epoch,false));await screen.findByText("Added row");expect(transport).toHaveBeenCalledTimes(2);
 }finally{screen.unmount();}
});

it("exposes readiness only after the focused initial boundary's actual layout",async()=>{
 const observations:number[]=[];const onReady=jest.fn();const Watch=Object.assign(()=>{observations.push(onReady.mock.calls.length);return null;},{localName:"watch",namespaceURI:APP});
 const mounted=setup(async()=>({kind:"busy"}),{components:[Watch]},"",onReady);
 try{await mounted.screen.findByText("Login");expect(observations[0]).toBe(0);expect(onReady).toHaveBeenCalledTimes(1);expect(onReady.mock.calls[0][0]).toMatchObject({epoch:mounted.gate.snapshot().epoch,routeKey:expect.any(String)});}
 finally{mounted.screen.unmount();}
});

it("a stale pause capability cannot resume the replacement epoch",async()=>{
 const mounted=setup(async()=>({kind:"busy"}));
 try{await mounted.screen.findByText("Login");const before=mounted.gate.snapshot().epoch;act(()=>{mounted.gate.resetEpoch();});expect(mounted.gate.setRetainedPaused(before,false)).toBe(false);expect(mounted.gate.snapshot().suspended).toBe(true);}
 finally{mounted.screen.unmount();}
});

it.each(["<broken","<view xmlns='https://hyperview.org/hyperview' id='login-transition'/>"])("rejects a malformed or transition-shaped panel without replacing the draft: %s",async(body)=>{
 const mounted=setup(async()=>({kind:"panel",status:422,body,receipt:{}}));
 try{await mounted.screen.findByText("Login");fireEvent.changeText(mounted.screen.getByPlaceholderText("Password"),"stay");fireEvent.press(mounted.screen.getByText("Sign in"));await waitFor(()=>expect(mounted.errors).toHaveBeenCalledTimes(1));expect(mounted.screen.getByPlaceholderText("Password").props.value).toBe("stay");expect(mounted.gate.snapshot()).toMatchObject({operations:0,lastTerminal:{outcome:"error"}});}
 finally{mounted.screen.unmount();}
});

it("rejects the SDK's removed cached behavior after equivalent public swaps outside auth",async()=>{
 let source:ReturnType<ReturnType<typeof createRealtimeGate>["bindSource"]>|undefined;let gate:ReturnType<typeof createRealtimeGate>;
 const behavior:HvBehavior={action:"capture-submit",callback:(element,_update,getRoot,updateRoot)=>{source=gate.bindSource(element,{getRoot,updateRoot});}};
 const Swap=Object.assign(({onUpdate,options}:HvComponentProps)=><Text onPress={()=>{const root=options.onUpdateCallbacks!.getDoc()!;const target=Array.from(root.getElementsByTagName("*")).find(node=>node.getAttribute("id")==="login-panel")!;const replacement=new DOMParser().parseFromString(panel("Repeat validation"),"application/xml").documentElement;onUpdate(null,"swap",target,{newElement:replacement});}}>Public swap</Text>,{localName:"public-swap",namespaceURI:APP});
 const mounted=setup(async()=>({kind:"busy"}),{behaviors:[behavior],components:[Swap]},'<app:public-swap/>');gate=mounted.gate;
 try{await mounted.screen.findByText("Login");await act(async()=>fireEvent.press(mounted.screen.getByText("Public swap")));await mounted.screen.findByText("Repeat validation");await act(async()=>fireEvent.press(mounted.screen.getByText("Public swap")));
  await act(async()=>fireEvent.press(mounted.screen.getByText("Unlock")));expect(source).toBeNull();expect(gate.snapshot().lastRejection).toMatchObject({reason:"missing-origin"});
 }finally{mounted.screen.unmount();}
});

it.each(["absent","wrong"])("rejects an auth panel with %s request key before changing the form",async(kind)=>{
 const mounted=setup(async()=>({kind:"panel",status:422,body:panel("Invalid key",false,kind==="wrong"?"other-attempt":null,kind==="wrong"),receipt:{}}));
 try{await mounted.screen.findByText("Login");fireEvent.changeText(mounted.screen.getByPlaceholderText("Password"),"unchanged");fireEvent.press(mounted.screen.getByText("Sign in"));await waitFor(()=>expect(mounted.gate.snapshot().lastTerminal).toMatchObject({outcome:"error"}));expect(mounted.screen.queryByText("Invalid key")).toBeNull();expect(mounted.screen.getByPlaceholderText("Password").props.value).toBe("unchanged");}
 finally{mounted.screen.unmount();}
});

it("clears the prior refusal notice after a later valid panel is really committed",async()=>{
 const auth=jest.fn(async(_url:string,init:RequestInit):Promise<AuthResult>=>auth.mock.calls.length===1?{kind:"refused",status:403,body:"Refused",receipt:{}}:{kind:"panel",status:422,body:panel("Valid retry",false,requestId(init),true),receipt:{}});
 const mounted=setup(auth);
 try{await mounted.screen.findByText("Login");fireEvent.press(mounted.screen.getByText("Sign in"));await waitFor(()=>expect(mounted.gate.snapshot().routes[0].noticeCode).toBe("auth-refused"));fireEvent.press(mounted.screen.getByText("Sign in"));await mounted.screen.findByText("Valid retry");expect(mounted.gate.snapshot().routes[0]).toMatchObject({notice:false,noticeCode:undefined});}
 finally{mounted.screen.unmount();}
});

it("buffers exactly one foreground result arriving before Parser registers held",async()=>{
 const admissions:boolean[]=[];let resume!:(result:AuthResult)=>boolean;let id="";
 const auth=jest.fn(async(_url:string,init:RequestInit,deliver:(result:AuthResult)=>boolean):Promise<AuthResult>=>{
  resume=deliver;id=requestId(init);
  const result:AuthResult={kind:"panel",status:422,body:panel("Early foreground",false,id,true),receipt:{}};
  admissions.push(deliver(result),deliver(result));
  return{kind:"held"};
 });
 const mounted=setup(auth);
 try{await mounted.screen.findByText("Login");fireEvent.press(mounted.screen.getByText("Sign in"));await waitFor(()=>expect(auth).toHaveBeenCalledTimes(1));
  expect(admissions).toEqual([true,false]);await mounted.screen.findByText("Early foreground");expect(mounted.gate.snapshot()).toMatchObject({operations:0,lastTerminal:{outcome:"ack",reason:"auth-panel-layout"}});expect(resume({kind:"held"})).toBe(false);expect(mounted.transport).toHaveBeenCalledTimes(1);
 }finally{mounted.screen.unmount();}
});

it("revokes a buffered auth continuation before the delayed held result settles",async()=>{
 const pending=deferred<AuthResult>();let admitted=false;
 const auth=jest.fn((_url:string,init:RequestInit,deliver:(result:AuthResult)=>boolean)=>{admitted=deliver({kind:"panel",status:422,body:panel("Revoked early result",false,requestId(init),true),receipt:{}});return pending.promise;});
 const mounted=setup(auth);
 try{await mounted.screen.findByText("Login");fireEvent.press(mounted.screen.getByText("Sign in"));await waitFor(()=>expect(auth).toHaveBeenCalledTimes(1));expect(admitted).toBe(true);expect(mounted.screen.queryByText("Revoked early result")).toBeNull();act(()=>{mounted.gate.resetEpoch();});await act(async()=>pending.resolve({kind:"held"}));expect(mounted.screen.queryByText("Revoked early result")).toBeNull();expect(mounted.gate.snapshot()).toMatchObject({operations:0,suspended:true});}
 finally{mounted.screen.unmount();}
});

it.each([
 ["accepted", "/hv/settings/", "post",200,"settings-form-panel",'token="" once="true" immediate="true"',true],
 ["other endpoint","/hv/tasks/","post",200,"settings-form-panel",'token="" once="true" immediate="true"',false],
 ["GET response","/hv/settings/","get",200,"settings-form-panel",'token="" once="true" immediate="true"',false],
 ["validation failure","/hv/settings/","post",422,"settings-form-panel",'token="" once="true" immediate="true"',false],
 ["other panel","/hv/settings/","post",200,"other-panel",'token="" once="true" immediate="true"',false],
 ["nonempty token","/hv/settings/","post",200,"settings-form-panel",'token="arbitrary" once="true" immediate="true"',false],
 ["missing once","/hv/settings/","post",200,"settings-form-panel",'token="" immediate="true"',false],
 ["missing immediate","/hv/settings/","post",200,"settings-form-panel",'token="" once="true"',false],
] as const)("grants settings clear only to the live own successful POST node: %s",async(_name,href,verb,status,rootId,attributes,accepted)=>{
 let gate:ReturnType<typeof createRealtimeGate>;const observed:boolean[]=[];const forged:boolean[]=[];let captured:Element|undefined;let authority:NonNullable<ReturnType<typeof gate.bindSource>>|undefined;
 const store:HvBehavior={action:"store-biometric-token",callback:(element,_update,getRoot,updateRoot)=>{captured=element;authority=gate.bindSource(element,{getRoot,updateRoot})!;observed.push(gate.isSettingsClear(element,authority));forged.push(gate.isSettingsClear(element,{...authority}));}};
 const controls=`<view id="settings-form-panel"><text>Settings draft</text></view><view href="${href}" verb="${verb}" action="replace" target="settings-form-panel"><text>Save settings</text></view>`;
 const mounted=setup(async()=>({kind:"busy"}),{behaviors:[store]},controls);gate=mounted.gate;
 try{await mounted.screen.findByText("Login");mounted.transport.mockImplementationOnce(async(_u,init)=>({...response(`<view xmlns="${HV}" xmlns:app="${APP}" id="${rootId}"><app:realtime-page request-id="${requestId(init!)}" page="1"/><behavior trigger="load" action="store-biometric-token" ${attributes}/><text>Settings result</text></view>`),status}));
  await act(async()=>fireEvent.press(mounted.screen.getByText("Save settings")));await mounted.screen.findByText("Settings result");await waitFor(()=>expect(observed).toEqual([accepted]));expect(forged).toEqual([false]);expect(gate.snapshot().lastTerminal).toMatchObject({outcome:"ack",reason:"remote-layout"});
  act(()=>gate.setRetainedPaused(gate.snapshot().epoch,true));expect(gate.isSettingsClear(captured!,authority!)).toBe(false);
  act(()=>gate.resetEpoch());expect(gate.isSettingsClear(captured!,authority!)).toBe(false);
 }finally{mounted.screen.unmount();}
});
