import "react-native-gesture-handler/jestSetup";
import React from "react";
import {Text} from "react-native";
import {act,fireEvent,render,waitFor} from "@testing-library/react-native";
import {NavigationContainer} from "@react-navigation/native";
import {createStackNavigator} from "@react-navigation/stack";
import {createRealtimeGate} from "../src/realtime/gate";

jest.mock("react-native-webview",()=>({WebView:()=>null}));
const Stack=createStackNavigator();
const BASE="https://hypertodo.test/hv/tasks/?status=active";
const NS="https://hypertodo.app/components";
const HV="https://hyperview.org/hyperview";
const doc=(id:string,controls:string="")=>`<doc xmlns="${HV}" xmlns:app="${NS}"><screen><body><app:realtime refresh-href="/hv/tasks/?fragment=list" target="rows" mode="notice"><list id="rows"><item key="one"><app:realtime-page request-id="${id}" page="1"/><text>Initial row</text></item></list><view href="/hv/tasks/next/" action="append" target="rows"><text>Next</text></view>${controls}</app:realtime></body></screen></doc>`;
const items=(id:string,text="Added row")=>`<items xmlns="${HV}" xmlns:app="${NS}"><item key="two"><app:realtime-page request-id="${id}" page="2"/><text>${text}</text></item></items>`;
const response=(body:string,status=200)=>({status,ok:status>=200&&status<300,url:BASE,headers:new Headers({"Content-Type":"application/vnd.hyperview+xml"}),text:async()=>body}) as Response;
function deferred<T>(){let resolve!:(value:T)=>void;let reject!:(reason:Error)=>void;const promise=new Promise<T>((yes,no)=>{resolve=yes;reject=no;});return{promise,resolve,reject};}
function setup(controls:string,run:(number:number,id:string,url:string)=>Promise<Response>,props:Partial<React.ComponentProps<ReturnType<typeof createRealtimeGate>["Root"]>>={}){
 const gate=createRealtimeGate(); const errors=jest.fn();
 const transport=jest.fn(async(input:RequestInfo|URL,init?:RequestInit):Promise<Response>=>{
  const id=new Headers(init?.headers).get("X-HyperTodo-Request-ID")!;
  return transport.mock.calls.length===1?response(doc(id,controls)):run(transport.mock.calls.length,id,String(input));
 });
 const screen=render(<NavigationContainer><Stack.Navigator screenOptions={{animationEnabled:false}}><Stack.Screen name="main">{()=> <gate.Root entrypointUrl={BASE} fetch={gate.wrapFetch(transport)} formatDate={()=>undefined} onError={errors} {...props} components={[...gate.components,...(props.components??[])]}/>}</Stack.Screen></Stack.Navigator></NavigationContainer>);
 return{gate,transport,screen,errors};
}

it.each(["append","replace"])("C2 serializes local %s with a real layout ACK, not its dispatch",async(action)=>{
 const renders:number[]=[]; let currentGate:ReturnType<typeof createRealtimeGate>;
 const Watch=Object.assign(()=>{renders.push(currentGate.snapshot().operations);return null;},{localName:"commit-watch",namespaceURI:NS});
 const {gate,screen,transport}=setup(`<view id="local-source"><app:commit-watch/></view><view id="local-target"><text>Before local</text></view><view href="#local-source" action="${action}" target="local-target"><text>Local</text></view>`,async(_n,id)=>response(items(id)),{components:[Watch]});
 currentGate=gate;
 await screen.findByText("Initial row");
 renders.length=0;
 await act(async()=>fireEvent.press(screen.getByText("Local")));
 expect(renders).toContain(1);
 await waitFor(()=>expect(gate.snapshot()).toMatchObject({operations:0,lastTerminal:{outcome:"ack"}}));
 expect(transport).toHaveBeenCalledTimes(1);
 fireEvent.press(screen.getByText("Next"));await screen.findByText("Added row");
 expect(gate.snapshot().pending).toBe(0);
});

it.each(["network","body","parse","empty","204","abort"])("C2 owns %s terminal without poisoning the next ordinary request",async(kind)=>{
 const {gate,screen,transport,errors}=setup('<view href="/hv/tasks/fail/" action="append" target="rows" verb="post"><text>Fail</text></view>',async(n,id)=>{
  if(n>2)return response(items(id));
  if(kind==="network"||kind==="abort"){const error=new Error("Controlled failure");if(kind==="abort")error.name="AbortError";throw error;}
  if(kind==="body")return {...response(""),text:async()=>{throw new Error("Body failure");}} as Response;
  return response(kind==="parse"?"<broken":"",kind==="204"?204:200);
 });
 await screen.findByText("Initial row");
 await act(async()=>fireEvent.press(screen.getByText("Fail")));
 await waitFor(()=>expect(gate.snapshot()).toMatchObject({operations:0,pending:0,blocked:false,lastTerminal:{outcome:kind==="abort"?"cancelled":kind==="empty"||kind==="204"?"no-document":"error"}}));
 expect(transport).toHaveBeenCalledTimes(2);
 if(!["empty","204","abort"].includes(kind))expect(errors).toHaveBeenCalledTimes(1);
 fireEvent.press(screen.getByText("Next"));await screen.findByText("Added row");
 expect(transport).toHaveBeenCalledTimes(3);
});

it("C2 drops a same-sync request before transport without leaving it queued",async()=>{
 const first=deferred<Response>();let firstId="";
 const buttons='<view href="/hv/tasks/sync-one/" action="append" target="rows" sync-id="rows" sync-method="drop"><text>Sync one</text></view><view href="/hv/tasks/sync-two/" action="append" target="rows" sync-id="rows" sync-method="drop"><text>Sync two</text></view>';
 const {gate,screen,transport}=setup(buttons,async(n,id)=>{if(n===2){firstId=id;return first.promise;}return response(items(id,"Next row"));});
 await screen.findByText("Initial row");fireEvent.press(screen.getByText("Sync one"));
 await waitFor(()=>expect(transport).toHaveBeenCalledTimes(2));
 await act(async()=>fireEvent.press(screen.getByText("Sync two")));
 expect(gate.snapshot()).toMatchObject({operations:1,queued:0,lastTerminal:{outcome:"dropped"}});
 await act(async()=>first.resolve(response(items(firstId))));await screen.findByText("Added row");
 fireEvent.press(screen.getByText("Next"));await screen.findByText("Next row");
 expect(transport).toHaveBeenCalledTimes(3);
});

it.each(["before-headers","during-body","after-parse"])("C2 replaces sync work %s without applying superseded XML",async(phase)=>{
 const headers=deferred<Response>();const body=deferred<string>();let firstId="";let replace=()=>{};let triggered=false;
 const buttons='<view href="/hv/tasks/sync-old/" action="append" target="rows" sync-id="rows" sync-method="replace"><text>Old</text></view><view href="/hv/tasks/sync-new/" action="append" target="rows" sync-id="rows" sync-method="replace"><text>New</text></view>';
 const {gate,screen,transport}=setup(buttons,async(n,id)=>{if(n===2){firstId=id;if(phase==="before-headers")return headers.promise;if(phase==="during-body")return {...response(""),text:()=>body.promise} as Response;return response(items(id,"Superseded row"));}return response(items(id,"Current row"));},{onParseAfter:url=>{if(phase==="after-parse"&&url.includes("sync-old")&&!triggered){triggered=true;replace();}}});
 await screen.findByText("Initial row");replace=()=>fireEvent.press(screen.getByText("New"));
 fireEvent.press(screen.getByText("Old"));
 await waitFor(()=>expect(transport.mock.calls.length).toBeGreaterThanOrEqual(2));
 if(phase!=="after-parse")replace();
 await screen.findByText("Current row");
 if(phase==="before-headers")await act(async()=>headers.resolve(response(items(firstId,"Superseded row"))));
 if(phase==="during-body")await act(async()=>body.resolve(items(firstId,"Superseded row")));
 expect(screen.queryByText("Superseded row")).toBeNull();
 expect(transport).toHaveBeenCalledTimes(3);
 expect(gate.snapshot()).toMatchObject({operations:0,pending:0,blocked:false});
});


it.each(["success","failure"])("C2 preserves show/hide indicators through %s",async(outcome)=>{
 const request=deferred<Response>();let id="";
 const {gate,screen,errors}=setup('<text id="loading" hide="true">Loading rows</text><text id="idle">Ready rows</text><view href="/hv/tasks/indicators/" action="append" target="rows" show-during-load="loading" hide-during-load="idle"><text>Load</text></view>',async(_n,value)=>{id=value;return request.promise;});
 await screen.findByText("Initial row");fireEvent.press(screen.getByText("Load"));
 await screen.findByText("Loading rows");expect(screen.queryByText("Ready rows")).toBeNull();
 if(outcome==="success")await act(async()=>request.resolve(response(items(id))));
 else await act(async()=>request.reject(new Error("Indicator failure")));
 await screen.findByText("Ready rows");expect(screen.queryByText("Loading rows")).toBeNull();
 await waitFor(()=>expect(gate.snapshot().operations).toBe(0));
 expect(errors).toHaveBeenCalledTimes(outcome==="success"?0:1);
});

it("C2 gives an explicit retry a fresh attempt without automatically replaying POST",async()=>{
 const attempts:string[]=[];
 const {gate,screen,transport}=setup('<view href="/hv/tasks/retry/" action="append" target="rows" verb="post"><text>Retry</text></view>',async(n,id)=>{attempts.push(id);if(n===2)throw new Error("Temporary failure");return response(items(id));});
 await screen.findByText("Initial row");await act(async()=>fireEvent.press(screen.getByText("Retry")));
 await waitFor(()=>expect(gate.snapshot()).toMatchObject({operations:0,lastTerminal:{outcome:"error"}}));
 expect(transport).toHaveBeenCalledTimes(2);
 fireEvent.press(screen.getByText("Retry"));await screen.findByText("Added row");
 expect(attempts).toHaveLength(2);expect(attempts[0]).not.toBe(attempts[1]);
 expect(transport).toHaveBeenCalledTimes(3);
});

it("C2 cancels a removed delayed origin without a document ACK",async()=>{
 jest.useFakeTimers({doNotFake:["queueMicrotask"]});
 const remove={action:"remove-delayed",callback:(_element:Element,_update:import("hyperview").HvComponentOnUpdate,getRoot:import("hyperview").HvGetRoot,updateRoot:import("hyperview").HvUpdateRoot)=>{
  const root=getRoot()!;const origin=Array.from(root.getElementsByTagName("*")).find(node=>node.getAttribute("id")==="delayed-origin")!;origin.parentNode!.removeChild(origin);updateRoot(root);
 }};
 const {gate,screen,transport}=setup('<view id="delayed-origin"><behavior trigger="press" href="/hv/tasks/delayed/" action="append" target="rows" delay="1000"/><text>Delay</text></view><view><behavior trigger="press" action="remove-delayed"/><text>Remove delayed</text></view>',async(_n,id)=>response(items(id)),{behaviors:[remove]});
 try {
  await screen.findByText("Initial row");await act(async()=>fireEvent.press(screen.getByText("Delay")));
  expect(gate.snapshot().operations).toBe(1);
  await act(async()=>fireEvent.press(screen.getByText("Remove delayed")));
  await act(async()=>jest.advanceTimersByTime(1000));
  expect(gate.snapshot()).toMatchObject({operations:0,pending:0,lastTerminal:{outcome:"cancelled"}});
  expect(transport).toHaveBeenCalledTimes(1);
  fireEvent.press(screen.getByText("Next"));await screen.findByText("Added row");
 } finally {screen.unmount();jest.useRealTimers();}
});

it("C2 cleans up even if the caller error callback throws, preserving uncertainty notice",async()=>{
 const onError=jest.fn(()=>{throw new Error("Caller error handler failed");});
 const {gate,screen,transport}=setup('<view href="/hv/tasks/fail-handler/" action="append" target="rows" verb="post"><text>Fail handler</text></view>',async(n,id)=>{if(n===2)throw new Error("Transport uncertain");return response(items(id));},{onError});
 await screen.findByText("Initial row");await act(async()=>fireEvent.press(screen.getByText("Fail handler")));
 await waitFor(()=>expect(gate.snapshot()).toMatchObject({operations:0,pending:0,blocked:false,routes:[{notice:true}]}));
 expect(onError).toHaveBeenCalledTimes(1);expect(transport).toHaveBeenCalledTimes(2);
 fireEvent.press(screen.getByText("Next"));await screen.findByText("Added row");
 expect(transport).toHaveBeenCalledTimes(3);
});

it("C2 preserves declared network-retry headers without replaying a POST",async()=>{
 const {screen,transport}=setup('<view href="/hv/tasks/retry-headers/" action="append" target="rows" verb="post" network-retry-action="reload" network-retry-event="retry-tasks"><text>Retry headers</text></view>',async(_n,id)=>response(items(id)));
 await screen.findByText("Initial row");fireEvent.press(screen.getByText("Retry headers"));await screen.findByText("Added row");
 const headers=new Headers(transport.mock.calls[1][1]?.headers);
 expect(headers.get("X-Network-Retry-Action")).toBe("reload");
 expect(headers.get("X-Network-Retry-Event")).toBe("retry-tasks");
 expect(transport).toHaveBeenCalledTimes(2);
});

it("C2 cancels its own delayed scheduler when authentication resets",async()=>{
 jest.useFakeTimers({doNotFake:["queueMicrotask"]});
 const {gate,screen,transport}=setup('<view><behavior trigger="press" href="/hv/tasks/delayed-reset/" action="append" target="rows" delay="100000"/><text>Delay reset</text></view>',async(_n,id)=>response(items(id)));
 try {
  await screen.findByText("Initial row");await act(async()=>jest.advanceTimersByTime(1000));
  const timers=jest.getTimerCount();await act(async()=>fireEvent.press(screen.getByText("Delay reset")));
  expect(jest.getTimerCount()).toBeGreaterThan(timers);
  act(()=>{gate.resetEpoch();});
  expect(jest.getTimerCount()).toBeLessThanOrEqual(timers);
  expect(gate.snapshot()).toMatchObject({operations:0,pending:0,suspended:true});expect(transport).toHaveBeenCalledTimes(1);
 } finally {screen.unmount();jest.useRealTimers();}
});


it("C2 never turns a throwing onEnd callback into a false pre-layout terminal",async()=>{
 const onEnd=jest.fn(()=>{throw new Error("Caller onEnd failed");});
 const Control=Object.assign(({element,onUpdate}:import("hyperview").HvComponentProps)=><Text onPress={()=>onUpdate("/hv/tasks/end/","append",element,{targetId:"rows",onEnd})}>Throw end</Text>,{localName:"throw-end",namespaceURI:NS});
 const {gate,screen,errors}=setup('<view><app:throw-end/></view>',async(_n,id)=>response(items(id)),{components:[Control]});
 await screen.findByText("Initial row");fireEvent.press(screen.getByText("Throw end"));await screen.findByText("Added row");
 expect(gate.snapshot()).toMatchObject({operations:0,pending:0,lastTerminal:{outcome:"ack"}});
 expect(onEnd).toHaveBeenCalledTimes(1);expect(errors).toHaveBeenCalledTimes(1);
});

it("C2 rejects a stale result echo before delivery and allows a fresh explicit request",async()=>{
 const {gate,screen,transport}=setup('<view href="/hv/tasks/stale/" action="append" target="rows"><text>Stale request</text></view>',async(n,id)=>response(items(n===2?"gate-obsolete-0-1":id,n===2?"Stale row":"Fresh row")));
 await screen.findByText("Initial row");await act(async()=>fireEvent.press(screen.getByText("Stale request")));
 await waitFor(()=>expect(gate.snapshot()).toMatchObject({operations:0,pending:0,lastTerminal:{outcome:"error"}}));
 expect(screen.queryByText("Stale row")).toBeNull();expect(transport).toHaveBeenCalledTimes(2);
 fireEvent.press(screen.getByText("Next"));await screen.findByText("Fresh row");expect(transport).toHaveBeenCalledTimes(3);
});

it("C2 once no-op cannot replace its own still-in-flight sync operation",async()=>{
 const first=deferred<Response>();let firstId="";
 const {gate,screen,transport}=setup('<view href="/hv/tasks/once-sync/" action="append" target="rows" sync-id="rows" sync-method="replace" once="true"><text>Once sync</text></view>',async(_n,id)=>{firstId=id;return first.promise;});
 await screen.findByText("Initial row");fireEvent.press(screen.getByText("Once sync"));await waitFor(()=>expect(transport).toHaveBeenCalledTimes(2));
 await act(async()=>fireEvent.press(screen.getByText("Once sync")));
 expect(gate.snapshot()).toMatchObject({operations:1,pending:1,lastTerminal:{outcome:"no-document",reason:"once"}});
 await act(async()=>first.resolve(response(items(firstId))));await screen.findByText("Added row");
 expect(transport).toHaveBeenCalledTimes(2);expect(gate.snapshot().operations).toBe(0);
});


it.each([['remote','replace'],['remote','drop'],['local','replace'],['local','drop']] as const)("C2 keeps an onEnd successor behind %s layout with sync %s",async(source,syncMethod)=>{
 const events:string[]=[];const beforeLayout:unknown[]=[];const atHttp:unknown[]=[];const next=deferred<Response>();let nextId="";
 const gate=createRealtimeGate();
 const Watch=Object.assign(()=>{React.useLayoutEffect(()=>{events.push("A-layout");},[]);return null;},{localName:"successor-watch",namespaceURI:NS});
 const Control=Object.assign(({element,onUpdate}:import("hyperview").HvComponentProps)=><Text onPress={()=>onUpdate(source==="local"?"#successor-source":"/hv/tasks/a/","append",element,{targetId:source==="local"?"local-target":"rows",syncId:"rows",syncMethod:"replace",onEnd:()=>{
  events.push("A-onEnd");
  let root:Node=element;while(root.parentNode)root=root.parentNode;
  const document=root as Document;
  onUpdate("/hv/tasks/b/","append",element,{targetId:"rows",syncId:"rows",syncMethod});
  beforeLayout.push({document:root.nodeType===9,boundaries:document.getElementsByTagNameNS(NS,"realtime").length,sourceLive:Array.from(document.getElementsByTagName("*")).includes(element),events:[...events],state:gate.snapshot()});
 }})}>Start successor</Text>,{localName:"successor-control",namespaceURI:NS});
 const transport=jest.fn(async(_input:RequestInfo|URL,init?:RequestInit):Promise<Response>=>{
  const id=new Headers(init?.headers).get("X-HyperTodo-Request-ID")!;
  if(transport.mock.calls.length===1)return response(doc(id,`<view><app:successor-control/></view>${source==="local"?'<view id="successor-source"><text>A local row</text><app:successor-watch/></view><view id="local-target"/>':''}`));
  if(source==="remote"&&transport.mock.calls.length===2)return response(items(id,"A remote row").replace('</item>','<app:successor-watch/></item>'));
  events.push("B-http");atHttp.push({events:[...events],state:gate.snapshot()});nextId=id;return next.promise;
 });
 const screen=render(<NavigationContainer><Stack.Navigator screenOptions={{animationEnabled:false}}><Stack.Screen name="main">{()=> <gate.Root entrypointUrl={BASE} fetch={gate.wrapFetch(transport)} formatDate={()=>undefined} onError={jest.fn()} components={[...gate.components,Control,Watch]}/>}</Stack.Screen></Stack.Navigator></NavigationContainer>);
 try {
  await screen.findByText("Initial row");events.length=0;
  await act(async()=>fireEvent.press(screen.getByText("Start successor")));
  // The original child is still in the real tree, not merely ownerDocument.
  expect(beforeLayout).toEqual([expect.objectContaining({document:true,boundaries:1,sourceLive:true,events:["A-onEnd"]})]);
  expect(gate.snapshot().lastRejection).toBeNull();
  // onEnd can enqueue B but cannot replace/drop A's already-submitted result or ACK it.
  expect(beforeLayout).toEqual([expect.objectContaining({state:expect.objectContaining({operations:2,queued:1,pending:source==="remote"?1:0,lastTerminal:null})})]);
  await waitFor(()=>expect(transport).toHaveBeenCalledTimes(source==="remote"?3:2));
  expect(atHttp).toEqual([{events:["A-onEnd","A-layout","B-http"],state:expect.objectContaining({operations:1,queued:0,lastTerminal:{outcome:"ack",reason:source==="remote"?"remote-layout":"local-layout",routeKey:expect.any(String)}})}]);
  await act(async()=>next.resolve(response(items(nextId,"B committed row"))));
  await screen.findByText("B committed row");
  expect(gate.snapshot()).toMatchObject({operations:0,pending:0,queued:0,lastTerminal:{outcome:"ack"}});
  expect(transport).toHaveBeenCalledTimes(source==="remote"?3:2);
 } finally {screen.unmount();}
});

it("C2 denies an onEnd successor whose origin was actually removed",async()=>{
 const gate=createRealtimeGate();const ends=jest.fn();
 const Control=Object.assign(({element,onUpdate}:import("hyperview").HvComponentProps)=><Text onPress={()=>onUpdate("/hv/tasks/remove-origin/","replace",element,{targetId:"origin-wrapper",onEnd:()=>{
  ends();onUpdate("/hv/tasks/forbidden-successor/","append",element,{targetId:"rows"});
 }})}>Remove own origin</Text>,{localName:"remove-origin",namespaceURI:NS});
 const transport=jest.fn(async(_input:RequestInfo|URL,init?:RequestInit):Promise<Response>=>{
  const id=new Headers(init?.headers).get("X-HyperTodo-Request-ID")!;
  return response(transport.mock.calls.length===1?doc(id,'<view id="origin-wrapper"><app:remove-origin/></view>'):`<view xmlns="${HV}" xmlns:app="${NS}" id="origin-wrapper"><app:realtime-page request-id="${id}" page="1"/><text>Origin removed</text></view>`);
 });
 const screen=render(<NavigationContainer><Stack.Navigator screenOptions={{animationEnabled:false}}><Stack.Screen name="main">{()=> <gate.Root entrypointUrl={BASE} fetch={gate.wrapFetch(transport)} formatDate={()=>undefined} onError={jest.fn()} components={[...gate.components,Control]}/>}</Stack.Screen></Stack.Navigator></NavigationContainer>);
 try {
  await screen.findByText("Initial row");fireEvent.press(screen.getByText("Remove own origin"));await screen.findByText("Origin removed");
  expect(ends).toHaveBeenCalledTimes(1);expect(transport).toHaveBeenCalledTimes(2);
  expect(gate.snapshot()).toMatchObject({operations:0,pending:0,lastTerminal:{outcome:"ack"}});
  expect(gate.snapshot().lastRejection).not.toBeNull();
 } finally {screen.unmount();}
});

it("C2 denies two genuinely live boundaries before dispatch",async()=>{
 const gate=createRealtimeGate();
 const Control=Object.assign(({element,onUpdate}:import("hyperview").HvComponentProps)=><Text onPress={()=>onUpdate("/hv/tasks/ambiguous/","append",element,{targetId:"rows"})}>Ambiguous dispatch</Text>,{localName:"ambiguous-dispatch",namespaceURI:NS});
 const transport=jest.fn(async(_input:RequestInfo|URL,init?:RequestInit):Promise<Response>=>{
  const id=new Headers(init?.headers).get("X-HyperTodo-Request-ID")!;
  const second=`<app:realtime refresh-href="/hv/second/" target="second" mode="notice"><list id="second"><item key="second"><app:realtime-page request-id="${id}" page="1"/><text>Second boundary</text></item></list></app:realtime>`;
  return response(doc(id,'<view><app:ambiguous-dispatch/></view>').replace('</body>',second+'</body>'));
 });
 const screen=render(<NavigationContainer><Stack.Navigator screenOptions={{animationEnabled:false}}><Stack.Screen name="main">{()=> <gate.Root entrypointUrl={BASE} fetch={gate.wrapFetch(transport)} formatDate={()=>undefined} onError={jest.fn()} components={[...gate.components,Control]}/>}</Stack.Screen></Stack.Navigator></NavigationContainer>);
 try {
  await screen.findByText("Initial row");await screen.findByText("Second boundary");
  await act(async()=>fireEvent.press(screen.getByText("Ambiguous dispatch")));
  expect(transport).toHaveBeenCalledTimes(1);expect(gate.snapshot().lastRejection).toMatchObject({reason:"ambiguous-owner"});
 } finally {screen.unmount();}
});
