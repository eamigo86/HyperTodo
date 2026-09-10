import "react-native-gesture-handler/jestSetup";
import React from "react";
import {Text,StyleSheet,FlatList} from "react-native";
import {act,fireEvent,render,waitFor} from "@testing-library/react-native";
import {NavigationContainer,createNavigationContainerRef} from "@react-navigation/native";
import {createStackNavigator} from "@react-navigation/stack";
import type {HvComponentProps} from "hyperview";
import {createRealtimeGate} from "../src/realtime/gate";
import {parseResources} from "../src/realtime/resources";

jest.mock("react-native-webview",()=>({WebView:()=>null}));
const Stack=createStackNavigator(),HV="https://hyperview.org/hyperview",NS="https://hypertodo.app/components";
const BASE="https://hypertodo.test/hv/tasks/?status=active&category=7",PAGE1=BASE+"&page=1";
const es={changed:"Puede haber novedades.",resync:"Revisá el estado actual.",update:"Actualizar",csrf:"No se pudo verificar el formulario.",error:"No se pudo actualizar."};
const en={changed:"Updates may be available.",resync:"Check the current state.",update:"Update",csrf:"Could not verify the form.",error:"Could not update."};
const id=(init?:RequestInit)=>new Headers(init?.headers).get("X-HyperTodo-Request-ID")!;
const doc=(requestId:string,{label="Before",resources="tasks categories ui",mode="list",page=1,extra="",color="#112233",href="/hv/tasks/?status=active&amp;category=7&amp;fragment=list"}={})=>`<doc xmlns="${HV}" xmlns:app="${NS}"><screen><styles><style id="heading" color="${color}"/></styles><body><app:realtime resources="${resources}" mode="${mode}" refresh-href="${href}" target="rows"><text style="heading">${label} count</text><app:watch/><list id="rows"><item key="one"><app:realtime-page request-id="${requestId}" page="${page}"/><text>${label} row</text></item></list><view href="/hv/tasks/?status=active&amp;category=7&amp;page=2&amp;fragment=items" action="append" target="rows"><text>More</text></view><view href="/hv/tasks/change/" verb="post" action="replace" target="row-panel"><text>Save ordinary</text></view><view id="row-panel"><text>Unchanged panel</text></view><form><text-field name="draft" placeholder="Draft" value="seed"/></form>${extra}</app:realtime></body></screen></doc>`;
const response=(body:string,url=BASE)=>({status:200,ok:true,url,headers:new Headers({"Content-Type":"application/vnd.hyperview+xml"}),text:async()=>body}) as Response;
const items=(requestId:string)=>`<items xmlns="${HV}" xmlns:app="${NS}"><item key="two"><app:realtime-page request-id="${requestId}" page="2"/><text>Second page</text></item></items>`;
function deferred<T>(){let resolve!:(value:T)=>void;const promise=new Promise<T>(yes=>{resolve=yes;});return{promise,resolve};}
function mount(gate:ReturnType<typeof createRealtimeGate>,transport:Parameters<typeof gate.wrapFetch>[0],components:React.ComponentProps<typeof gate.Root>["components"]=[],entrypointUrl=BASE){
 return render(<NavigationContainer><Stack.Navigator screenOptions={{animationEnabled:false}}><Stack.Screen name="fixture">{()=> <gate.Root entrypointUrl={entrypointUrl} fetch={gate.wrapFetch(transport)} formatDate={()=>undefined} onError={jest.fn()} components={[...gate.components,...(components??[])]}/>}</Stack.Screen></Stack.Navigator></NavigationContainer>);
}

it("refreshes dependency-matching whole documents, outside-list styles/counts and canonical filters",async()=>{
 const gate=createRealtimeGate({noticeLabels:()=>es}),before:unknown[]=[];
 const Watch=Object.assign(()=>{before.push(gate.snapshot());return null;},{localName:"watch",namespaceURI:NS});
 const transport=jest.fn(async(input:RequestInfo|URL,init?:RequestInit):Promise<Response>=>response(doc(id(init),{label:transport.mock.calls.length===1?"Before":"After",color:transport.mock.calls.length===1?"#112233":"#00aa44"}),String(input)));
 const screen=mount(gate,transport,[Watch]);
 try{await screen.findByText("Before count");before.length=0;const key=gate.snapshot().routes[0].key;act(()=>expect(gate.invalidateResources(gate.snapshot().epoch,["tasks"])).toBe(true));await screen.findByText("After count");
  expect(transport).toHaveBeenCalledTimes(2);expect(transport.mock.calls[1][0]).toBe(PAGE1);expect(new Headers(transport.mock.calls[1][1]?.headers).get("Accept")).not.toContain("fragment");expect(StyleSheet.flatten(screen.getByText("After count").props.style).color).toBe("#00aa44");
  expect(before).toContainEqual(expect.objectContaining({operations:1,lastTerminal:null}));expect(gate.snapshot()).toMatchObject({operations:0,lastTerminal:{outcome:"ack",reason:"reload-layout"},routes:[{key,notice:false}]});
 }finally{screen.unmount();}
});

it("filters by dependencies rather than route names, including category task counts",async()=>{
 const gate=createRealtimeGate({noticeLabels:()=>es});const transport=jest.fn(async(_u:RequestInfo|URL,init?:RequestInit):Promise<Response>=>response(doc(id(init),{resources:"tasks",label:transport.mock.calls.length===1?"Categories before":"Categories after"})));
 const screen=mount(gate,transport,[],"https://hypertodo.test/hv/categories/");
 try{await screen.findByText("Categories before count");act(()=>expect(gate.invalidateResources(gate.snapshot().epoch,["ui"])).toBe(true));await act(async()=>{});expect(transport).toHaveBeenCalledTimes(1);expect(gate.snapshot().routes[0].notice).toBe(false);
  act(()=>gate.invalidateResources(gate.snapshot().epoch,["tasks"]));await screen.findByText("Categories after count");expect(transport).toHaveBeenCalledTimes(2);
 }finally{screen.unmount();}
});

it.each([[],["other"],["tasks","tasks"],["ui","tasks"],["tasks","ui","categories"],"tasks",null].map(value=>[value]))("rejects malformed resource hints without changing state: %p",async(value)=>{
 const gate=createRealtimeGate({noticeLabels:()=>es});const transport=jest.fn(async(_u:RequestInfo|URL,init?:RequestInit):Promise<Response>=>response(doc(id(init))));const screen=mount(gate,transport);
 try{await screen.findByText("Before count");const before=gate.snapshot();expect(gate.invalidateResources(before.epoch,value as never)).toBe(false);expect(gate.snapshot()).toEqual(before);expect(transport).toHaveBeenCalledTimes(1);}finally{screen.unmount();}
});

it.each(["list","notice"])("renders a persistent accessible translated notice and deliberate page1 update for %s",async(mode)=>{
 const gate=createRealtimeGate({noticeLabels:()=>es});const transport=jest.fn(async(input:RequestInfo|URL,init?:RequestInit):Promise<Response>=>response(doc(id(init),{mode,page:mode==="list"?2:1,label:transport.mock.calls.length===1?"Before":"After"}),String(input)));const screen=mount(gate,transport);
 try{await screen.findByText("Before count");fireEvent.changeText(screen.getByPlaceholderText("Draft"),"keep unsaved");act(()=>gate.invalidateResources(gate.snapshot().epoch,["ui"]));
  await screen.findByText(es.changed);expect(screen.getByRole("alert")).toBeTruthy();for(const list of screen.UNSAFE_getAllByType(FlatList))expect(list.findAllByProps({accessibilityRole:"alert"})).toHaveLength(0);expect(screen.getByRole("button",{name:es.update})).toBeTruthy();expect(screen.getByPlaceholderText("Draft").props.value).toBe("keep unsaved");expect(transport).toHaveBeenCalledTimes(1);
  await act(async()=>gate.invalidateResources(gate.snapshot().epoch,["ui"]));expect(screen.getAllByText(es.changed)).toHaveLength(1);expect(screen.getByPlaceholderText("Draft").props.value).toBe("keep unsaved");
  fireEvent.press(screen.getByRole("button",{name:es.update}));await screen.findByText("After count");expect(transport).toHaveBeenCalledTimes(2);expect(transport.mock.calls[1][0]).toBe(mode==="list"?PAGE1:BASE);expect(screen.queryByText(es.changed)).toBeNull();
 }finally{screen.unmount();}
});

it.each(["append","post"])("coalesces hints behind an admitted %s and waits for its actual layout",async(kind)=>{
 const gate=createRealtimeGate({noticeLabels:()=>es}),pending=deferred<Response>();let operationId="";const before:unknown[]=[];
 const Watch=Object.assign(()=>{before.push(gate.snapshot());return null;},{localName:"watch",namespaceURI:NS});
 const transport=jest.fn(async(input:RequestInfo|URL,init?:RequestInit):Promise<Response>=>{if(transport.mock.calls.length===1)return response(doc(id(init)));if(transport.mock.calls.length===2){operationId=id(init);return pending.promise;}return response(doc(id(init),{label:"Fresh"}),String(input));});const screen=mount(gate,transport,[Watch]);
 try{await screen.findByText("Before count");fireEvent.press(screen.getByText(kind==="append"?"More":"Save ordinary"));await waitFor(()=>expect(transport).toHaveBeenCalledTimes(2));act(()=>{gate.invalidateResources(gate.snapshot().epoch,["tasks"]);gate.invalidateResources(gate.snapshot().epoch,["categories"]);gate.invalidateResources(gate.snapshot().epoch,["tasks"]);});expect(transport).toHaveBeenCalledTimes(2);before.length=0;
  await act(async()=>pending.resolve(response(kind==="append"?items(operationId):`<view xmlns="${HV}" xmlns:app="${NS}" id="row-panel"><app:realtime-page request-id="${operationId}" page="1"/><app:watch/><text>Saved panel</text></view>`)));
  if(kind==="append"){await screen.findByText("Second page");expect(transport).toHaveBeenCalledTimes(2);await screen.findByText(es.changed);fireEvent.press(screen.getByRole("button",{name:es.update}));}
  await screen.findByText("Fresh count");expect(transport).toHaveBeenCalledTimes(3);expect(transport.mock.calls.filter(call=>call[1]?.method==="post")).toHaveLength(kind==="post"?1:0);expect(gate.snapshot()).toMatchObject({operations:0,lastTerminal:{reason:"reload-layout"}});
 }finally{screen.unmount();}
});

it.each(["append","post"])("keeps ordinary %s behind a resource reload's real layout",async(kind)=>{
 const gate=createRealtimeGate({noticeLabels:()=>es}),pending=deferred<Response>();let reloadId="";
 const transport=jest.fn(async(input:RequestInfo|URL,init?:RequestInit):Promise<Response>=>{if(transport.mock.calls.length===1)return response(doc(id(init)));if(transport.mock.calls.length===2){reloadId=id(init);return pending.promise;}return response(kind==="append"?items(id(init)):`<view xmlns="${HV}" xmlns:app="${NS}" id="row-panel"><app:realtime-page request-id="${id(init)}" page="1"/><text>Post after refresh</text></view>`,String(input));});const screen=mount(gate,transport);
 try{await screen.findByText("Before count");act(()=>gate.invalidateResources(gate.snapshot().epoch,["tasks"]));await waitFor(()=>expect(transport).toHaveBeenCalledTimes(2));fireEvent.press(screen.getByText(kind==="append"?"More":"Save ordinary"));await waitFor(()=>expect(gate.snapshot()).toMatchObject({operations:2,queued:1}));expect(transport).toHaveBeenCalledTimes(2);
  await act(async()=>pending.resolve(response(doc(reloadId,{label:"Fresh"}),PAGE1)));await screen.findByText(kind==="append"?"Second page":"Post after refresh");expect(transport).toHaveBeenCalledTimes(3);expect(gate.snapshot().routes[0]).toMatchObject({pages:kind==="append"?[1,2]:[1],notice:false});expect(transport.mock.calls.filter(call=>call[1]?.method==="post")).toHaveLength(kind==="post"?1:0);
 }finally{screen.unmount();}
});

it("coalesces hints during an active reload into one follow-up rather than one request per hint",async()=>{
 const gate=createRealtimeGate({noticeLabels:()=>es}),pending=deferred<Response>();let firstId="";
 const transport=jest.fn(async(input:RequestInfo|URL,init?:RequestInit):Promise<Response>=>{if(transport.mock.calls.length===1)return response(doc(id(init)));if(transport.mock.calls.length===2){firstId=id(init);return pending.promise;}return response(doc(id(init),{label:"Latest"}),String(input));});const screen=mount(gate,transport);
 try{await screen.findByText("Before count");act(()=>gate.invalidateResources(gate.snapshot().epoch,["tasks"]));await waitFor(()=>expect(transport).toHaveBeenCalledTimes(2));act(()=>{for(let i=0;i<8;i++)gate.invalidateResources(gate.snapshot().epoch,["tasks"]);});expect(transport).toHaveBeenCalledTimes(2);await act(async()=>pending.resolve(response(doc(firstId,{label:"Intermediate"}),PAGE1)));await screen.findByText("Latest count");expect(transport).toHaveBeenCalledTimes(3);expect(gate.snapshot().routes[0].notice).toBe(false);
 }finally{screen.unmount();}
});

it("isolates two gate instances and rejects an old captured epoch without affecting the new tree",async()=>{
 const first=createRealtimeGate({noticeLabels:()=>es}),second=createRealtimeGate({noticeLabels:()=>es});
 const transportA=jest.fn(async(_u:RequestInfo|URL,init?:RequestInit):Promise<Response>=>response(doc(id(init),{label:"First",mode:"notice"}))),transportB=jest.fn(async(_u:RequestInfo|URL,init?:RequestInit):Promise<Response>=>response(doc(id(init),{label:"Second",mode:"notice"})));
 const a=mount(first,transportA),b=mount(second,transportB);
 try{await a.findByText("First count");await b.findByText("Second count");const old=first.snapshot().epoch;act(()=>first.invalidateResources(old,["ui"]));expect(first.snapshot().routes[0].notice).toBe(true);expect(second.snapshot().routes[0].notice).toBe(false);act(()=>{const token=first.resetEpoch();first.resumeEpoch(token);});await a.findByText("First count");const before=first.snapshot();expect(first.invalidateResources(old,["tasks"])).toBe(false);expect(first.snapshot()).toEqual(before);expect(second.snapshot().routes[0].notice).toBe(false);
 }finally{a.unmount();b.unmount();}
});

it("defers hidden dependent routes and applies their policy on real SDK focus return",async()=>{
 const gate=createRealtimeGate({noticeLabels:()=>es}),root="https://hypertodo.test/hv/";
 const navigation=`<doc xmlns="${HV}"><navigator id="main" type="stack"><nav-route id="root-route" href="/hv/tasks/" selected="true"/></navigator></doc>`;
 let taskLoads=0;
 const transport=jest.fn(async(input:RequestInfo|URL,init?:RequestInit)=>{const url=String(input);if(url===root)return response(navigation,url);const detail=url.includes("/edit/");if(!detail)taskLoads++;return response(doc(id(init),{label:detail?"Edit":taskLoads===1?"Before":"Returned",resources:detail?"ui":"tasks",mode:detail?"notice":"list",extra:detail?'<view action="back"><text>Return</text></view>':'<view action="navigate" href="/hv/tasks/one/edit/"><text>Edit</text></view>'}),url);});const screen=mount(gate,transport,[],root);
 try{await screen.findByText("Before count");fireEvent.press(screen.getByText("Edit"));await screen.findByText("Edit count");act(()=>gate.invalidateResources(gate.snapshot().epoch,["tasks"]));await act(async()=>{});expect(taskLoads).toBe(1);expect(gate.snapshot().routes.find(route=>route.focused)?.notice).toBe(false);fireEvent.press(screen.getByText("Return"));await screen.findByText("Returned count");expect(taskLoads).toBe(2);expect(gate.snapshot().pending).toBe(1); // navigator scaffold is not a fake ACK or operation barrier.
 }finally{screen.unmount();}
});

it("retains background drafts and admitted writes, then refreshes after confirmation without replay",async()=>{
 const gate=createRealtimeGate({noticeLabels:()=>es}),pending=deferred<Response>();let postId="";
 const transport=jest.fn(async(input:RequestInfo|URL,init?:RequestInit):Promise<Response>=>{if(transport.mock.calls.length===1)return response(doc(id(init)));if(transport.mock.calls.length===2){postId=id(init);return pending.promise;}return response(doc(id(init),{label:"Confirmed"}),String(input));});const screen=mount(gate,transport);
 try{await screen.findByText("Before count");fireEvent.changeText(screen.getByPlaceholderText("Draft"),"retained");fireEvent.press(screen.getByText("Save ordinary"));await waitFor(()=>expect(transport).toHaveBeenCalledTimes(2));act(()=>{gate.setRetainedPaused(gate.snapshot().epoch,true);gate.invalidateResources(gate.snapshot().epoch,["tasks"]);});await act(async()=>pending.resolve(response(`<view xmlns="${HV}" xmlns:app="${NS}" id="row-panel"><app:realtime-page request-id="${postId}" page="1"/><text>Saved</text></view>`)));expect(screen.getByPlaceholderText("Draft").props.value).toBe("retained");expect(screen.queryByText("Saved")).toBeNull();expect(transport).toHaveBeenCalledTimes(2);await act(async()=>gate.setRetainedPaused(gate.snapshot().epoch,false));await screen.findByText("Confirmed count");expect(transport).toHaveBeenCalledTimes(3);expect(transport.mock.calls.filter(call=>call[1]?.method==="post")).toHaveLength(1);
 }finally{screen.unmount();}
});

it("relabels an already visible notice on App rerender without remounting its draft",async()=>{
 let labels=es;const gate=createRealtimeGate({noticeLabels:()=>labels});const transport=jest.fn(async(_u:RequestInfo|URL,init?:RequestInit):Promise<Response>=>response(doc(id(init),{mode:"notice"})));const fetch=gate.wrapFetch(transport),errors=jest.fn();
 const Host=({tick}:{tick:number})=><NavigationContainer><Stack.Navigator screenOptions={{animationEnabled:false}}><Stack.Screen name="fixture">{()=> <gate.Root entrypointUrl={BASE} fetch={fetch} formatDate={()=>undefined} onError={errors} components={gate.components}/>}</Stack.Screen></Stack.Navigator><Text>{tick}</Text></NavigationContainer>;
 const screen=render(<Host tick={0}/>);
 try{await screen.findByText("Before count");fireEvent.changeText(screen.getByPlaceholderText("Draft"),"borrador");act(()=>gate.invalidateResources(gate.snapshot().epoch,["ui"]));await screen.findByText(es.changed);labels=en;screen.rerender(<Host tick={1}/>);await screen.findByText(en.changed);expect(screen.queryByText(es.changed)).toBeNull();expect(screen.getByRole("button",{name:en.update})).toBeTruthy();expect(screen.getByPlaceholderText("Draft").props.value).toBe("borrador");expect(transport).toHaveBeenCalledTimes(1);
 }finally{screen.unmount();}
});

it.each([undefined,()=>({...es,update:""}),()=>({...es,changed:"x".repeat(513)}),()=>{throw new Error("private locale failure");}])("requires explicit bounded labels before admitting resource hints",async(noticeLabels)=>{
 const gate=createRealtimeGate({noticeLabels});const transport=jest.fn(async(_u:RequestInfo|URL,init?:RequestInit):Promise<Response>=>response(doc(id(init))));const screen=mount(gate,transport);
 try{await screen.findByText("Before count");const before=gate.snapshot();expect(gate.invalidateResources(before.epoch,["tasks"])).toBe(false);expect(gate.snapshot()).toEqual(before);expect(transport).toHaveBeenCalledTimes(1);}finally{screen.unmount();}
});

it("renders a distinct translated CSRF notice without an action that discards the draft",async()=>{
 const gate=createRealtimeGate({noticeLabels:()=>es,authenticate:async()=>({kind:"refused",status:403,body:"secret diagnostic",receipt:{}})});
 const transport=jest.fn(async(_u:RequestInfo|URL,init?:RequestInit):Promise<Response>=>response(doc(id(init),{mode:"notice",extra:'<view id="login-panel"><text>Login</text></view><view href="/hv/login/" verb="post" action="replace" target="login-panel"><text>Submit login</text></view>'})));const screen=mount(gate,transport);
 try{await screen.findByText("Before count");fireEvent.changeText(screen.getByPlaceholderText("Draft"),"unchanged form");fireEvent.press(screen.getByText("Submit login"));await screen.findByText(es.csrf);expect(screen.getByRole("alert")).toBeTruthy();expect(screen.queryByRole("button",{name:es.update})).toBeNull();expect(screen.getByPlaceholderText("Draft").props.value).toBe("unchanged form");expect(screen.queryByText("secret diagnostic")).toBeNull();expect(transport).toHaveBeenCalledTimes(1);expect(gate.snapshot().lastTerminal).toMatchObject({reason:"auth-refused",outcome:"no-document"});
 }finally{screen.unmount();}
});

it.each([["tasks categories"],["tasks categories ui"]].map(value=>[value]))("rejects a combined string masquerading as one resource token: %p",async(value)=>{
 const gate=createRealtimeGate({noticeLabels:()=>es});const transport=jest.fn(async(_u:RequestInfo|URL,init?:RequestInit):Promise<Response>=>response(doc(id(init))));const screen=mount(gate,transport);
 try{await screen.findByText("Before count");expect(gate.invalidateResources(gate.snapshot().epoch,value as never)).toBe(false);expect(transport).toHaveBeenCalledTimes(1);expect(gate.snapshot().routes[0].notice).toBe(false);}finally{screen.unmount();}
});

it("keeps explicit keyed auth handlers live through two panels with notice UI configured",async()=>{
 let gate:ReturnType<typeof createRealtimeGate>;const current:boolean[]=[];
 const controls='<view href="/hv/login/" verb="post" action="replace" target="login-panel"><text>Retry login</text></view><view><behavior trigger="press" action="probe-current"/><text>Probe current</text></view>';
 const auth=jest.fn(async(_url:string,init:RequestInit)=>({kind:"panel" as const,status:422,body:`<view xmlns="${HV}" id="login-panel" key="auth-panel-${id(init)}">${controls}</view>`,receipt:{}}));
 gate=createRealtimeGate({noticeLabels:()=>es,authenticate:auth});const transport=jest.fn(async(_u:RequestInfo|URL,init?:RequestInit):Promise<Response>=>response(doc(id(init),{mode:"notice",extra:`<view id="login-panel">${controls}</view>`})));
 const fetch=gate.wrapFetch(transport);const behavior={action:"probe-current",callback:(element:Element,_update:unknown,getRoot:()=>Document|undefined,updateRoot:(doc:Document)=>void)=>{current.push(gate.bindSource(element,{getRoot,updateRoot})?.sourceIsCurrent()===true);}};
 const screen=render(<NavigationContainer><Stack.Navigator screenOptions={{animationEnabled:false}}><Stack.Screen name="fixture">{()=> <gate.Root entrypointUrl={BASE} fetch={fetch} formatDate={()=>undefined} components={gate.components} behaviors={[behavior]}/>}</Stack.Screen></Stack.Navigator></NavigationContainer>);
 try{await screen.findByText("Before count");for(let i=1;i<=2;i++){fireEvent.press(screen.getByText("Retry login"));await waitFor(()=>expect(auth).toHaveBeenCalledTimes(i));await waitFor(()=>expect(gate.snapshot().operations).toBe(0));await act(async()=>fireEvent.press(screen.getByText("Probe current")));}expect(current).toEqual([true,true]);expect(transport).toHaveBeenCalledTimes(1);}finally{screen.unmount();}
});

it("keeps a failed resource refresh visible without an automatic retry loop and retries only once per manual press",async()=>{
 const gate=createRealtimeGate({noticeLabels:()=>es}),retry=deferred<Response>();let retryId="";
 const transport=jest.fn(async(input:RequestInfo|URL,init?:RequestInit):Promise<Response>=>{if(transport.mock.calls.length===1)return response(doc(id(init)));if(transport.mock.calls.length===2)throw new Error("network detail not UI");retryId=id(init);return retry.promise;});const screen=mount(gate,transport);
 try{await screen.findByText("Before count");act(()=>gate.invalidateResources(gate.snapshot().epoch,["tasks"]));await screen.findByText(es.error);await act(async()=>{});expect(transport).toHaveBeenCalledTimes(2);fireEvent.press(screen.getByRole("button",{name:es.update}));fireEvent.press(screen.getByRole("button",{name:es.update}));await waitFor(()=>expect(transport).toHaveBeenCalledTimes(3));await act(async()=>retry.resolve(response(doc(retryId,{label:"Recovered"}),PAGE1)));await screen.findByText("Recovered count");expect(screen.queryByText(es.error)).toBeNull();expect(transport).toHaveBeenCalledTimes(3);
 }finally{screen.unmount();}
});

it("defers an in-flight automatic refresh on real blur and honors automatic policy on return",async()=>{
 const gate=createRealtimeGate({noticeLabels:()=>es}),pending=deferred<Response>();const navigation=createNavigationContainerRef<{Main:undefined;Other:undefined}>();let oldId="";
 const transport=jest.fn(async(input:RequestInfo|URL,init?:RequestInit):Promise<Response>=>{if(transport.mock.calls.length===1)return response(doc(id(init)));if(transport.mock.calls.length===2){oldId=id(init);return pending.promise;}return response(doc(id(init),{label:"Returned current"}),String(input));});const fetch=gate.wrapFetch(transport);
 const screen=render(<NavigationContainer ref={navigation}><Stack.Navigator screenOptions={{animationEnabled:false}}><Stack.Screen name="Main">{()=> <gate.Root entrypointUrl={BASE} fetch={fetch} formatDate={()=>undefined} components={gate.components}/>}</Stack.Screen><Stack.Screen name="Other">{()=> <Text>Other route</Text>}</Stack.Screen></Stack.Navigator></NavigationContainer>);
 try{await screen.findByText("Before count");act(()=>gate.invalidateResources(gate.snapshot().epoch,["tasks"]));await waitFor(()=>expect(transport).toHaveBeenCalledTimes(2));act(()=>navigation.navigate("Other"));await screen.findByText("Other route");expect(gate.snapshot().operations).toBe(0);act(()=>navigation.goBack());await screen.findByText("Returned current count");expect(transport).toHaveBeenCalledTimes(3);await act(async()=>pending.resolve(response(doc(oldId,{label:"Old cancelled"}),PAGE1)));expect(screen.queryByText("Old cancelled count")).toBeNull();expect(gate.snapshot()).toMatchObject({operations:0,lastTerminal:{reason:"reload-layout"}});
 }finally{screen.unmount();}
});


it.each([['tasks'],['categories'],['ui'],['tasks','categories'],['tasks','ui'],['categories','ui'],['tasks','categories','ui']].map(value=>[value]))("accepts and snapshots canonical resource combination %p",value=>{const copied=parseResources(value);expect(copied).toEqual(value);expect(copied).not.toBe(value);expect(Object.isFrozen(copied)).toBe(true);});
