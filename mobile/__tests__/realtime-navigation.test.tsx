import "react-native-gesture-handler/jestSetup";
import React from "react";
import {Text, StyleSheet} from "react-native";
import {act, fireEvent, render, waitFor} from "@testing-library/react-native";
import {NavigationContainer} from "@react-navigation/native";
import {createStackNavigator} from "@react-navigation/stack";
import type {HvComponentProps} from "hyperview";
import {createRealtimeGate} from "../src/realtime/gate";

jest.mock("react-native-webview",()=>({WebView:()=>null}));
const Stack=createStackNavigator();
const NS="https://hypertodo.app/components", HV="https://hyperview.org/hyperview";
const BASE="https://hypertodo.test/hv/tasks/?status=active&category=7";
const NEXT="https://hypertodo.test/hv/tasks/?status=done&category=7";
const document=(id:string,label="Initial tasks",color="#112233",controls="")=>`<doc xmlns="${HV}" xmlns:app="${NS}"><screen><styles><style id="heading" color="${color}"/></styles><body><app:realtime refresh-href="/hv/tasks/?fragment=list" target="rows" mode="notice"><list id="rows"><item key="one"><app:realtime-page request-id="${id}" page="1"/><text style="heading">${label}</text><app:reload-watch/></item></list><view href="/hv/tasks/?status=done&amp;category=7" action="reload"><text>Reload tasks</text></view>${controls}</app:realtime></body></screen></doc>`;
const response=(body:string,url=BASE)=>({status:200,ok:true,url,headers:new Headers({"Content-Type":"application/vnd.hyperview+xml"}),text:async()=>body}) as Response;
const items=(id:string)=>`<items xmlns="${HV}" xmlns:app="${NS}"><item key="two"><app:realtime-page request-id="${id}" page="2"/><text>Added task</text></item></items>`;
function deferred<T>(){let resolve!:(value:T)=>void;const promise=new Promise<T>(yes=>{resolve=yes;});return{promise,resolve};}
function mount(gate:ReturnType<typeof createRealtimeGate>,transport:Parameters<ReturnType<typeof createRealtimeGate>["wrapFetch"]>[0],components:React.ComponentProps<ReturnType<typeof createRealtimeGate>["Root"]>["components"]=[],entrypointUrl=BASE){
 return render(<NavigationContainer><Stack.Navigator screenOptions={{animationEnabled:false}}><Stack.Screen name="fixture">{()=> <gate.Root entrypointUrl={entrypointUrl} fetch={gate.wrapFetch(transport)} formatDate={()=>undefined} onError={jest.fn()} components={[...gate.components,...(components??[])]}/>}</Stack.Screen></Stack.Navigator></NavigationContainer>);
}

it("owns canonical screen reload through actual supplied callbacks and waits for real layout",async()=>{
 const gate=createRealtimeGate();const beforeLayout:unknown[]=[];
 const Watch=Object.assign(({options}:HvComponentProps)=>{beforeLayout.push({url:options.screenUrl,state:gate.snapshot()});return null;},{localName:"reload-watch",namespaceURI:NS});
 const transport=jest.fn(async(input:RequestInfo|URL,init?:RequestInit):Promise<Response>=>{const id=new Headers(init?.headers).get("X-HyperTodo-Request-ID")!;return response(document(id,transport.mock.calls.length===1?"Initial tasks":"Reloaded tasks",transport.mock.calls.length===1?"#112233":"#00aa44"),String(input));});
 const screen=mount(gate,transport,[Watch]);
 try{
  await screen.findByText("Initial tasks");beforeLayout.length=0;
  fireEvent.press(screen.getByText("Reload tasks"));await screen.findByText("Reloaded tasks");
  expect(transport).toHaveBeenCalledTimes(2);expect(transport.mock.calls[1][0]).toBe(NEXT);
  expect(Object.getOwnPropertySymbols(transport.mock.calls[1][1]??{})).toHaveLength(0);
  expect(beforeLayout).toContainEqual(expect.objectContaining({url:NEXT,state:expect.objectContaining({operations:1,pending:1,lastTerminal:null})}));
  expect(StyleSheet.flatten(screen.getByText("Reloaded tasks").props.style).color).toBe("#00aa44");
  expect(gate.snapshot()).toMatchObject({operations:0,pending:0,lastTerminal:{outcome:"ack",reason:"reload-layout"}});
  // HvScreen's own public no-op refresh effect must not cause another load.
  await act(async()=>{});expect(transport).toHaveBeenCalledTimes(2);
 }finally{screen.unmount();}
});

it("old public layout cannot ACK a pending reload or admit its queued append early",async()=>{
 const gate=createRealtimeGate();const reload=deferred<Response>();let reloadId="";
 const Control=Object.assign(({options}:HvComponentProps)=><Text onPress={()=>options.onUpdateCallbacks!.setState({})}>Old layout</Text>,{localName:"old-layout",namespaceURI:NS});
 const controls='<view><app:old-layout/></view><view href="/hv/tasks/next/" action="append" target="rows"><text>Append tasks</text></view>';
 const transport=jest.fn(async(input:RequestInfo|URL,init?:RequestInit):Promise<Response>=>{const id=new Headers(init?.headers).get("X-HyperTodo-Request-ID")!;if(transport.mock.calls.length===1)return response(document(id,"Initial tasks","#112233",controls));if(transport.mock.calls.length===2){reloadId=id;return reload.promise;}return response(items(id),String(input));});
 const screen=mount(gate,transport,[Control]);
 try{
  await screen.findByText("Initial tasks");fireEvent.press(screen.getByText("Reload tasks"));await waitFor(()=>expect(transport).toHaveBeenCalledTimes(2));
  await act(async()=>fireEvent.press(screen.getByText("Old layout")));
  fireEvent.press(screen.getByText("Append tasks"));
  await waitFor(()=>expect(gate.snapshot()).toMatchObject({operations:2,queued:1,pending:1,lastTerminal:null}));
  expect(transport).toHaveBeenCalledTimes(2);
  await act(async()=>reload.resolve(response(document(reloadId,"Reloaded tasks","#00aa44",controls),NEXT)));
  await screen.findByText("Added task");expect(transport).toHaveBeenCalledTimes(3);
  expect(gate.snapshot()).toMatchObject({operations:0,pending:0});
 }finally{screen.unmount();}
});

it("rejects a navigator document for ordinary reload instead of nesting a new root",async()=>{
 const gate=createRealtimeGate();
 const transport=jest.fn(async(_input:RequestInfo|URL,init?:RequestInit):Promise<Response>=>{const id=new Headers(init?.headers).get("X-HyperTodo-Request-ID")!;return response(transport.mock.calls.length===1?document(id):`<doc xmlns="${HV}"><navigator id="unexpected" type="stack"><nav-route id="root-route" href="/hv/dashboard/" selected="true"/></navigator></doc>`);});
 const screen=mount(gate,transport);
 try{
  await screen.findByText("Initial tasks");fireEvent.press(screen.getByText("Reload tasks"));
  await waitFor(()=>expect(gate.snapshot()).toMatchObject({operations:0,lastTerminal:{outcome:"error",reason:"unsupported-document"}}));
  expect(screen.getByText("Initial tasks")).toBeTruthy();expect(transport).toHaveBeenCalledTimes(2);
 }finally{screen.unmount();}
});

it("keeps SDK canonical navigation/back stack and reports state changes without XML ACK",async()=>{
 const gate=createRealtimeGate();const ROOT="https://hypertodo.test/hv/";
 const root=`<doc xmlns="${HV}"><navigator id="main" type="stack"><nav-route id="root-route" href="/hv/tasks/" selected="true"/></navigator></doc>`;
 const transport=jest.fn(async(input:RequestInfo|URL,init?:RequestInit):Promise<Response>=>{const id=new Headers(init?.headers).get("X-HyperTodo-Request-ID")!;const url=String(input);if(url===ROOT)return response(root,url);const detail=url.includes("/edit/");return response(document(id,detail?"Edit task":"Task list","#112233",detail?'<view action="back"><text>Back to tasks</text></view>':'<view action="navigate" href="/hv/tasks/one/edit/"><text>Edit task route</text></view><view action="navigate" href="#root-route"><text>Home noop</text></view><view action="navigate" href="#missing-route"><text>Missing route</text></view>'),url);});
 const screen=mount(gate,transport,[],ROOT);
 try{
  await screen.findByText("Task list");fireEvent.press(screen.getByText("Edit task route"));await screen.findByText("Edit task");
  expect(gate.snapshot().lastTerminal).toMatchObject({outcome:"no-document",reason:"navigation-changed"});
  expect(transport.mock.calls.map(call=>call[0])).toEqual([ROOT,"https://hypertodo.test/hv/tasks/","https://hypertodo.test/hv/tasks/one/edit/"]);
  fireEvent.press(screen.getByText("Back to tasks"));await screen.findByText("Task list");
  expect(gate.snapshot().routes.filter(route=>route.focused)).toHaveLength(1);
  expect(transport).toHaveBeenCalledTimes(3);
  await act(async()=>fireEvent.press(screen.getByText("Home noop")));
  expect(gate.snapshot().lastTerminal).toMatchObject({outcome:"no-document",reason:"navigation-no-op"});
  await act(async()=>fireEvent.press(screen.getByText("Missing route")));
  expect(gate.snapshot().lastTerminal).toMatchObject({outcome:"no-document",reason:"missing-destination"});
  expect(transport).toHaveBeenCalledTimes(3);
 }finally{screen.unmount();}
});

it("preserves once for an in-flight owned reload without duplicate HTTP",async()=>{
 const gate=createRealtimeGate(),pending=deferred<Response>();let id="";
 const controls='<view href="/hv/tasks/?status=done&amp;category=7" action="reload" once="true"><text>Once reload</text></view>';
 const transport=jest.fn(async(_input:RequestInfo|URL,init?:RequestInit):Promise<Response>=>{id=new Headers(init?.headers).get("X-HyperTodo-Request-ID")!;return transport.mock.calls.length===1?response(document(id,"Initial tasks","#112233",controls)):pending.promise;});
 const screen=mount(gate,transport);
 try{
  await screen.findByText("Initial tasks");fireEvent.press(screen.getByText("Once reload"));await waitFor(()=>expect(transport).toHaveBeenCalledTimes(2));
  await act(async()=>fireEvent.press(screen.getByText("Once reload")));
  expect(gate.snapshot()).toMatchObject({operations:1,queued:0,lastTerminal:{outcome:"no-document",reason:"once"}});
  await act(async()=>pending.resolve(response(document(id,"Reloaded tasks"),NEXT)));
  await screen.findByText("Reloaded tasks");expect(transport).toHaveBeenCalledTimes(2);
 }finally{screen.unmount();}
});

it.each(["success","failure"])("preserves public loading indicators through reload %s",async(outcome)=>{
 const gate=createRealtimeGate(),pending=deferred<Response>();let id="";let reject!:(error:Error)=>void;
 const request=new Promise<Response>((resolve,no)=>{reject=no;pending.promise.then(resolve);});
 const controls='<text id="loading" hide="true">Loading tasks</text><text id="idle">Ready tasks</text><view href="/hv/tasks/?status=done&amp;category=7" action="reload" show-during-load="loading" hide-during-load="idle"><text>Reload indicators</text></view>';
 const transport=jest.fn(async(_input:RequestInfo|URL,init?:RequestInit):Promise<Response>=>{id=new Headers(init?.headers).get("X-HyperTodo-Request-ID")!;return transport.mock.calls.length===1?response(document(id,"Initial tasks","#112233",controls)):request;});
 const screen=mount(gate,transport);
 try{
  await screen.findByText("Initial tasks");fireEvent.press(screen.getByText("Reload indicators"));
  await screen.findByText("Loading tasks");expect(screen.queryByText("Ready tasks")).toBeNull();
  if(outcome==="success")await act(async()=>pending.resolve(response(document(id,"Reloaded tasks","#00aa44",controls),NEXT)));
  else await act(async()=>reject(new Error("Controlled reload failure")));
  await screen.findByText("Ready tasks");expect(screen.queryByText("Loading tasks")).toBeNull();
  expect(gate.snapshot()).toMatchObject({operations:0,pending:0,lastTerminal:{outcome:outcome==="success"?"ack":"error"}});
  expect(gate.snapshot().routes[0].notice).toBe(outcome==="failure");
 }finally{screen.unmount();}
});

it("reports an owned reload abort as cancelled, not ACK or successful rollback",async()=>{
 const gate=createRealtimeGate();const transport=jest.fn(async(_input:RequestInfo|URL,init?:RequestInit):Promise<Response>=>{const id=new Headers(init?.headers).get("X-HyperTodo-Request-ID")!;if(transport.mock.calls.length===1)return response(document(id));const error=new Error("Controlled abort");error.name="AbortError";throw error;});
 const screen=mount(gate,transport);
 try{
  await screen.findByText("Initial tasks");fireEvent.press(screen.getByText("Reload tasks"));
  await waitFor(()=>expect(gate.snapshot()).toMatchObject({operations:0,pending:0,lastTerminal:{outcome:"cancelled"}}));
  expect(screen.getByText("Initial tasks")).toBeTruthy();expect(gate.snapshot().routes[0].notice).toBe(true);
  expect(transport).toHaveBeenCalledTimes(2);
 }finally{screen.unmount();}
});

it("never delivers old reload XML after identity reset",async()=>{
 const gate=createRealtimeGate(),pending=deferred<Response>();let id="";
 const transport=jest.fn(async(_input:RequestInfo|URL,init?:RequestInit):Promise<Response>=>{id=new Headers(init?.headers).get("X-HyperTodo-Request-ID")!;return transport.mock.calls.length===1?response(document(id)):pending.promise;});
 const screen=mount(gate,transport);
 try{
  await screen.findByText("Initial tasks");fireEvent.press(screen.getByText("Reload tasks"));await waitFor(()=>expect(transport).toHaveBeenCalledTimes(2));
  act(()=>{gate.resetEpoch();});
  await act(async()=>pending.resolve(response(document(id,"Obsolete private tasks"),NEXT)));
  expect(screen.queryByText("Obsolete private tasks")).toBeNull();
  expect(gate.snapshot()).toMatchObject({operations:0,pending:0,suspended:true,lastTerminal:null});
 }finally{screen.unmount();}
});

it("retains canonical filters for a second blank reload after a public rerender",async()=>{
 const gate=createRealtimeGate();const controls='<view action="reload"><text>Reload current URL</text></view><app:old-layout/>';
 const Control=Object.assign(({options}:HvComponentProps)=><Text onPress={()=>options.onUpdateCallbacks!.setState({})}>Render current screen</Text>,{localName:"old-layout",namespaceURI:NS});
 const transport=jest.fn(async(input:RequestInfo|URL,init?:RequestInit):Promise<Response>=>{const id=new Headers(init?.headers).get("X-HyperTodo-Request-ID")!;return response(document(id,`Screen ${transport.mock.calls.length}`,"#112233",controls),String(input));});
 const screen=mount(gate,transport,[Control]);
 try{
  await screen.findByText("Screen 1");fireEvent.press(screen.getByText("Reload tasks"));await screen.findByText("Screen 2");
  await act(async()=>fireEvent.press(screen.getByText("Render current screen")));
  expect(transport).toHaveBeenCalledTimes(2);fireEvent.press(screen.getByText("Reload current URL"));await screen.findByText("Screen 3");
  expect(transport.mock.calls.map(call=>call[0])).toEqual([BASE,NEXT,NEXT]);
  expect(gate.snapshot()).toMatchObject({operations:0,pending:0,lastTerminal:{outcome:"ack",reason:"reload-layout"}});
 }finally{screen.unmount();}
});

it.each(["empty","wrong-echo"])("keeps the old screen and frees only its reload after %s",async(kind)=>{
 const gate=createRealtimeGate();
 const transport=jest.fn(async(input:RequestInfo|URL,init?:RequestInit):Promise<Response>=>{const id=new Headers(init?.headers).get("X-HyperTodo-Request-ID")!;return response(transport.mock.calls.length===1?document(id):kind==="empty"?"":document("unrelated-old-attempt","Unowned screen"),String(input));});
 const screen=mount(gate,transport);
 try{
  await screen.findByText("Initial tasks");fireEvent.press(screen.getByText("Reload tasks"));
  await waitFor(()=>expect(gate.snapshot()).toMatchObject({operations:0,pending:0,lastTerminal:{outcome:kind==="empty"?"no-document":"error",reason:kind==="empty"?"empty-response":"unsupported-document"}}));
  expect(screen.queryByText("Unowned screen")).toBeNull();expect(screen.getByText("Initial tasks")).toBeTruthy();
  expect(gate.snapshot().routes[0].notice).toBe(true);expect(transport).toHaveBeenCalledTimes(2);
 }finally{screen.unmount();}
});
