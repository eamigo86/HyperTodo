import "react-native-gesture-handler/jestSetup";
import React from "react";
import {Text,StyleSheet,FlatList} from "react-native";
import {act,fireEvent,render,waitFor} from "@testing-library/react-native";
import {NavigationContainer,createNavigationContainerRef} from "@react-navigation/native";
import {createStackNavigator} from "@react-navigation/stack";
import type {HvComponentProps} from "hyperview";
import {createRealtimeGate} from "../src/realtime/gate";
import {parseResources,resourceReloadUrl} from "../src/realtime/resources";

jest.mock("react-native-webview",()=>({WebView:()=>null}));
const Stack=createStackNavigator(),HV="https://hyperview.org/hyperview",NS="https://hypertodo.app/components";
const BASE="https://hypertodo.test/hv/tasks/?status=active&category=7",PAGE1=BASE+"&page=1";
const es={changed:"Puede haber novedades.",resync:"Revisá el estado actual.",update:"Actualizar",dismiss:'Cerrar aviso',csrf:"No se pudo verificar el formulario.",error:"No se pudo actualizar."};
const en={changed:"Updates may be available.",resync:"Check the current state.",update:"Update",dismiss:'Dismiss notice',csrf:"Could not verify the form.",error:"Could not update."};
const id=(init?:RequestInit)=>new Headers(init?.headers).get("X-HyperTodo-Request-ID")!;
const doc=(requestId:string,{label="Before",resources="tasks categories ui",mode="list",page=1,extra="",color="#112233",href="/hv/tasks/?status=active&amp;category=7&amp;fragment=list"}={})=>`<doc xmlns="${HV}" xmlns:app="${NS}"><screen><styles><style id="heading" color="${color}"/></styles><body><app:realtime resources="${resources}" mode="${mode}" refresh-href="${href}" target="rows"><text style="heading">${label} count</text><app:watch/><list id="rows"><item key="one"><app:realtime-page request-id="${requestId}" page="${page}"/><text>${label} row</text></item></list><view href="/hv/tasks/?status=active&amp;category=7&amp;page=2&amp;fragment=items" action="append" target="rows"><text>More</text></view><view href="/hv/tasks/change/" verb="post" action="replace" target="row-panel"><text>Save ordinary</text></view><view id="row-panel"><text>Unchanged panel</text></view><form><text-field name="draft" placeholder="Draft" value="seed"/></form>${extra}</app:realtime></body></screen></doc>`;
const response=(body:string,url=BASE)=>({status:200,ok:true,url,headers:new Headers({"Content-Type":"application/vnd.hyperview+xml"}),text:async()=>body}) as Response;
const items=(requestId:string)=>`<items xmlns="${HV}" xmlns:app="${NS}"><item key="two"><app:realtime-page request-id="${requestId}" page="2"/><text>Second page</text></item></items>`;
function deferred<T>(){let resolve!:(value:T)=>void;const promise=new Promise<T>(yes=>{resolve=yes;});return{promise,resolve};}
function mount(gate:ReturnType<typeof createRealtimeGate>,transport:Parameters<typeof gate.wrapFetch>[0],components:React.ComponentProps<typeof gate.Root>["components"]=[],entrypointUrl=BASE){
 return render(<NavigationContainer><Stack.Navigator screenOptions={{animationEnabled:false}}><Stack.Screen name="fixture">{()=> <gate.Root entrypointUrl={entrypointUrl} fetch={gate.wrapFetch(transport)} formatDate={()=>undefined} onError={jest.fn()} components={[...gate.components,...(components??[])]}/>}</Stack.Screen></Stack.Navigator></NavigationContainer>);
}

it.each(['invalidate','local','resync'] as const)('automatically refreshes a readonly dashboard with ACK-only remote feedback: %s',async cause=>{
 const updated=jest.fn(),gate=createRealtimeGate({noticeLabels:()=>en,onResourceUpdated:updated}),pending=deferred<Response>();let requestId='';
 const transport=jest.fn(async(input:RequestInfo|URL,init?:RequestInit):Promise<Response>=>{requestId=id(init);return transport.mock.calls.length===1?response(doc(requestId,{mode:'readonly'}),String(input)):pending.promise;});
 const screen=mount(gate,transport);
 try{
  await screen.findByText('Before count');act(()=>gate.invalidateResources(gate.snapshot().epoch,['tasks'],cause));
  await waitFor(()=>expect(transport).toHaveBeenCalledTimes(2));expect(updated).not.toHaveBeenCalled();expect(screen.queryByText(en.changed)).toBeNull();
  await act(async()=>pending.resolve(response(doc(requestId,{mode:'readonly',label:'Current'}),BASE)));
  await screen.findByText('Current count');expect(gate.snapshot().lastTerminal).toMatchObject({outcome:'ack',reason:'reload-layout'});
  expect(updated).toHaveBeenCalledTimes(cause==='invalidate'?1:0);
 }finally{screen.unmount();}
});

it('refreshes the negotiated loaded prefix without replacing the FlatList instance or filters',async()=>{
 const gate=createRealtimeGate({noticeLabels:()=>en});
 const contextual=(body:string,url:string)=>{const result=response(body,url);result.headers.set('X-HyperTodo-Realtime-Features','changes-v2');return result;};
 const rows=(start:number,count:number)=>Array.from({length:count},(_,index)=>`<item key="task-${start+index}"><form><text-field hide="true" name="csrfmiddlewaretoken" value="rotated-${start+index}"/><text>Task ${start+index}</text></form></item>`).join('');
 const transport=jest.fn(async(input:RequestInfo|URL,init?:RequestInit):Promise<Response>=>{
  const url=String(input);if(transport.mock.calls.length===2)return contextual(items(id(init)).replace('<text>Second page</text>','<form><text-field hide="true" name="csrfmiddlewaretoken" value="rotated"/><text>Second page</text></form>').replace('</items>',rows(22,19)+'</items>'),url);
  let body=doc(id(init),{label:transport.mock.calls.length===1?'Before':'Prefix'});
  body=body.replace('</list>',rows(2,19)+'</list>');
  if(transport.mock.calls.length>2)body=body.replace('</list>',`<item key="two"><app:realtime-page request-id="${id(init)}" page="2"/><form><text-field hide="true" name="csrfmiddlewaretoken" value="fresh"/><text>Second page current</text></form></item>${rows(22,19)}</list>`);
  return contextual(body,url);
 });
 const screen=mount(gate,transport);
 try{
  await screen.findByText('Before count');fireEvent.press(screen.getByText('More'));await waitFor(()=>expect(gate.snapshot().routes[0].pages).toEqual([1,2]));
  const list=screen.UNSAFE_getByType(FlatList);expect(list.props.data).toHaveLength(40);
  act(()=>gate.invalidateResources(gate.snapshot().epoch,['tasks']));await screen.findByText('Prefix count');
  expect(String(transport.mock.calls[2][0])).toBe(BASE+'&through_page=2');expect(list.props.data).toHaveLength(40);expect(list.props.data.some((item:Element)=>item.textContent?.includes('Second page current'))).toBe(true);
  expect(screen.UNSAFE_getByType(FlatList)).toBe(list);expect(gate.snapshot().routes[0]).toMatchObject({pages:[1,2],notice:false});
 }finally{screen.unmount();}
});

it('bounds negotiated prefixes and never guesses unknown or sparse loaded pages',()=>{
 for(const pages of [[],[2],[1,3]])expect(()=>resourceReloadUrl(BASE,BASE,'list',pages,true)).toThrow('invalid-resource-prefix');
 expect(resourceReloadUrl(BASE+'&page=2&fragment=items',BASE,'list',[1,2],true)).toBe(BASE+'&through_page=2');
 expect(resourceReloadUrl(BASE,BASE,'list',[1,2],false)).toBe(PAGE1);
});

it('dismisses only the current card revision without acknowledging or destroying the draft',async()=>{
 const gate=createRealtimeGate({noticeLabels:()=>en}),transport=jest.fn(async(_url:RequestInfo|URL,init?:RequestInit):Promise<Response>=>response(doc(id(init),{mode:'form'})));
 const screen=mount(gate,transport);
 try{
  await screen.findByText('Before count');fireEvent.changeText(screen.getByPlaceholderText('Draft'),'retained text');
  act(()=>gate.invalidateResources(gate.snapshot().epoch,['tasks']));await screen.findByTestId('realtime-notice');
  fireEvent.press(screen.getByRole('button',{name:en.dismiss}));expect(screen.queryByText(en.changed)).toBeNull();
  expect(gate.snapshot().routes[0].notice).toBe(true);expect(screen.getByPlaceholderText('Draft').props.value).toBe('retained text');expect(transport).toHaveBeenCalledTimes(1);
  await act(async()=>gate.invalidateResources(gate.snapshot().epoch,['tasks'],'resync'));expect(screen.queryByText(en.changed)).toBeNull();
  act(()=>gate.invalidateResources(gate.snapshot().epoch,['tasks']));await screen.findByTestId('realtime-notice');
  expect(screen.getByPlaceholderText('Draft').props.value).toBe('retained text');expect(gate.snapshot().lastTerminal).toBeNull();
 }finally{screen.unmount();}
});

it('refreshes negotiated prefixes beyond 400 rows as an explicit fresh page1 fallback, not a truncated page20',async()=>{
 const gate=createRealtimeGate({noticeLabels:()=>en});
 const transport=jest.fn(async(input:RequestInfo|URL,init?:RequestInit):Promise<Response>=>{
  let body=doc(id(init),{label:transport.mock.calls.length===1?'Before':'Page one'});
  if(transport.mock.calls.length===1)body=body.replace('</list>',Array.from({length:419},(_,index)=>`<item key="row-${index+2}">${(index+1)%20===0?`<app:realtime-page request-id="${id(init)}" page="${Math.floor((index+1)/20)+1}"/>`:''}<form><text-field name="csrfmiddlewaretoken" hide="true" value="masked-${index}"/><text>Loaded row ${index+2}</text></form></item>`).join('')+'</list>');
  const result=response(body,String(input));result.headers.set('X-HyperTodo-Realtime-Features','changes-v2');return result;
 });
 const screen=mount(gate,transport);
 try{
  await screen.findByText('Before count');const list=screen.UNSAFE_getByType(FlatList);expect(gate.snapshot().routes[0].pages).toHaveLength(21);expect(list.props.data).toHaveLength(420);
  act(()=>gate.invalidateResources(gate.snapshot().epoch,['tasks']));await screen.findByText('Page one count');
  expect(String(transport.mock.calls[1][0])).toBe(PAGE1);expect(screen.UNSAFE_getByType(FlatList)).toBe(list);
  expect(gate.snapshot().routes[0]).toMatchObject({pages:[1],notice:false});expect(gate.snapshot().lastTerminal).toMatchObject({outcome:'ack',reason:'reload-layout'});
 }finally{screen.unmount();}
});

it('masks a retained stale readonly route before focus and reveals it only after fresh layout without a toast',async()=>{
 const updated=jest.fn(),gate=createRealtimeGate({noticeLabels:()=>en,onResourceUpdated:updated}),root='https://hypertodo.test/hv/',pending=deferred<Response>();let requestId='',loads=0;
 const navigation=`<doc xmlns="${HV}"><navigator id="main" type="stack"><nav-route id="root-route" href="/hv/tasks/" selected="true"/></navigator></doc>`;
 const transport=jest.fn(async(input:RequestInfo|URL,init?:RequestInit):Promise<Response>=>{
  const url=String(input);if(url===root)return response(navigation,url);
  if(url.includes('/edit/'))return response(doc(id(init),{label:'Editor',mode:'form',resources:'ui',extra:'<view action="back"><text>Return now</text></view>'}),url);
  loads++;if(loads>1){requestId=id(init);return pending.promise;}
  return response(doc(id(init),{mode:'readonly',resources:'tasks',extra:'<view action="navigate" href="/hv/tasks/one/edit/"><text>Open editor</text></view>'}),url);
 });
 const screen=mount(gate,transport,[],root);
 try{
  await screen.findByText('Before count');const list=screen.UNSAFE_getByType(FlatList);
  fireEvent.press(screen.getByText('Open editor'));await screen.findByText('Editor count');
  act(()=>gate.invalidateResources(gate.snapshot().epoch,['tasks']));expect(loads).toBe(1);
  fireEvent.press(screen.getByText('Return now'));await waitFor(()=>expect(loads).toBe(2));
  expect(screen.queryByText('Before count')).toBeNull();expect(screen.getByText('Before count',{includeHiddenElements:true})).toBeTruthy();
  expect(updated).not.toHaveBeenCalled();
  await act(async()=>pending.resolve(response(doc(requestId,{label:'Fresh return',mode:'readonly',resources:'tasks'}))));
  await screen.findByText('Fresh return count');expect(screen.UNSAFE_getByType(FlatList)).toBe(list);expect(updated).not.toHaveBeenCalled();
 }finally{screen.unmount();}
});

it('does not toast for remote changes first observed while the actual retained owner is paused',async()=>{
 const updated=jest.fn(),gate=createRealtimeGate({noticeLabels:()=>en,onResourceUpdated:updated});
 const transport=jest.fn(async(input:RequestInfo|URL,init?:RequestInit):Promise<Response>=>response(doc(id(init),{mode:'readonly',label:transport.mock.calls.length===1?'Before':'Resumed'}),String(input)));
 const screen=mount(gate,transport);
 try{
  await screen.findByText('Before count');act(()=>{gate.setRetainedPaused(gate.snapshot().epoch,true);gate.invalidateResources(gate.snapshot().epoch,['tasks']);});
  expect(transport).toHaveBeenCalledTimes(1);act(()=>gate.setRetainedPaused(gate.snapshot().epoch,false));await screen.findByText('Resumed count');
  expect(transport).toHaveBeenCalledTimes(2);expect(updated).not.toHaveBeenCalled();
 }finally{screen.unmount();}
});

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

it('does not auto-reload a list over a locally edited query/filter input',async()=>{
 const gate=createRealtimeGate({noticeLabels:()=>en});
 const transport=jest.fn(async(_url:RequestInfo|URL,init?:RequestInit):Promise<Response>=>response(doc(id(init),{label:transport.mock.calls.length===1?'Before':'After'})));
 const screen=mount(gate,transport);
 try{
  await screen.findByText('Before count');const field=screen.getByPlaceholderText('Draft');
  fireEvent.changeText(field,'query not applied yet');await act(async()=>gate.invalidateResources(gate.snapshot().epoch,['tasks']));
  expect(transport).toHaveBeenCalledTimes(1);expect(screen.getByPlaceholderText('Draft')).toBe(field);expect(field.props.value).toBe('query not applied yet');
  await screen.findByText(en.changed);
 }finally{screen.unmount();}
});

it('warns a dirty form for its actual entity, not another task owned by the same account',async()=>{
 const gate=createRealtimeGate({noticeLabels:()=>en}),epoch='a'.repeat(16),key='1'.repeat(64);
 const entities=JSON.stringify({epoch,items:[{resource:'tasks',key}]}).replaceAll('"','&quot;');
 const transport=jest.fn(async(_input:RequestInfo|URL,init?:RequestInit):Promise<Response>=>response(doc(id(init),{mode:'form'}).replace('mode="form"',`mode="form" entities="${entities}"`)));
 const screen=mount(gate,transport);
 try{
  await screen.findByText('Before count');fireEvent.changeText(screen.getByPlaceholderText('Draft'),'my task draft');
  await act(async()=>gate.invalidateResources(gate.snapshot().epoch,['tasks'],'invalidate',{mutationId:null,entities:{epoch,items:[{resource:'tasks',key:'2'.repeat(64)}]}}));
  expect(screen.queryByText(en.changed)).toBeNull();expect(gate.snapshot().routes[0].notice).toBe(false);expect(transport).toHaveBeenCalledTimes(1);
  act(()=>gate.invalidateResources(gate.snapshot().epoch,['tasks'],'invalidate',{mutationId:null,entities:{epoch,items:[{resource:'tasks',key}]}}));
  await screen.findByText(en.changed);expect(screen.getByPlaceholderText('Draft').props.value).toBe('my task draft');expect(transport).toHaveBeenCalledTimes(1);
 }finally{screen.unmount();}
});

it('requires confirmed discard for an edited form and rechecks the draft revision after the dialog',async()=>{
 const answer=deferred<boolean>(),confirmDiscard=jest.fn(()=>answer.promise);
 const gate=createRealtimeGate({noticeLabels:()=>en,confirmDiscard});
 const transport=jest.fn(async(input:RequestInfo|URL,init?:RequestInit):Promise<Response>=>response(doc(id(init),{mode:'form',label:transport.mock.calls.length===1?'Before':'After'}),String(input)));
 const screen=mount(gate,transport);
 try{
  await screen.findByText('Before count');fireEvent.changeText(screen.getByPlaceholderText('Draft'),'first edit');
  act(()=>gate.invalidateResources(gate.snapshot().epoch,['tasks']));await screen.findByText(en.changed);
  fireEvent.press(screen.getByRole('button',{name:en.update}));expect(confirmDiscard).toHaveBeenCalledTimes(1);expect(transport).toHaveBeenCalledTimes(1);
  fireEvent.changeText(screen.getByPlaceholderText('Draft'),'newer edit');await act(async()=>answer.resolve(true));
  expect(transport).toHaveBeenCalledTimes(1);expect(screen.getByPlaceholderText('Draft').props.value).toBe('newer edit');
  confirmDiscard.mockResolvedValueOnce(true);fireEvent.press(screen.getByRole('button',{name:en.update}));await screen.findByText('After count');
  expect(transport).toHaveBeenCalledTimes(2);expect(gate.snapshot().lastTerminal).toMatchObject({reason:'reload-layout',outcome:'ack'});
 }finally{screen.unmount();}
});

it('does not commit a queued readonly reload after the user starts editing its filter',async()=>{
 const gate=createRealtimeGate({noticeLabels:()=>en}),pending=deferred<Response>();let requestId='';
 const transport=jest.fn(async(input:RequestInfo|URL,init?:RequestInit):Promise<Response>=>{requestId=id(init);return transport.mock.calls.length===1?response(doc(requestId)):pending.promise;});
 const screen=mount(gate,transport);
 try{
  await screen.findByText('Before count');act(()=>gate.invalidateResources(gate.snapshot().epoch,['tasks']));await waitFor(()=>expect(transport).toHaveBeenCalledTimes(2));
  fireEvent.changeText(screen.getByPlaceholderText('Draft'),'typed during GET');
  await act(async()=>pending.resolve(response(doc(requestId,{label:'After'}),PAGE1)));
  expect(screen.queryByText('After count')).toBeNull();expect(screen.getByPlaceholderText('Draft').props.value).toBe('typed during GET');
  expect(gate.snapshot().routes[0].notice).toBe(true);expect(gate.snapshot().lastTerminal).not.toMatchObject({outcome:'ack'});
 }finally{screen.unmount();}
});

it.each(['accept','new-epoch','reverted','background','paused-delivery'])('retains a successful form POST after newer typing until owned discard: %s',async outcome=>{
 const confirm=deferred<boolean>(),confirmDiscard=jest.fn(()=>confirm.promise),pending=deferred<Response>();let postId='';
 const gate=createRealtimeGate({noticeLabels:()=>en,confirmDiscard}),effect=jest.fn();
 const Effect=Object.assign(()=>{effect();return null;},{localName:'effect',namespaceURI:NS});
 const form=(requestId:string)=>`<doc xmlns="${HV}" xmlns:app="${NS}"><screen><body><app:realtime resources="tasks ui" mode="form" refresh-href="/hv/tasks/edit/" target="form-panel"><app:realtime-page request-id="${requestId}" page="1"/><view id="form-panel"><form><text-field name="title" placeholder="Title" value="initial"/><view href="/hv/tasks/edit/" verb="post" action="replace" target="form-panel"><text>Save draft</text></view></form></view></app:realtime></body></screen></doc>`;
 const transport=jest.fn(async(input:RequestInfo|URL,init?:RequestInit):Promise<Response>=>{if(init?.method==='post'){postId=id(init);return pending.promise;}return response(form(id(init)),String(input));});
 const screen=mount(gate,transport,[Effect]);
 try{
  await screen.findByPlaceholderText('Title');fireEvent.changeText(screen.getByPlaceholderText('Title'),'submitted');
  fireEvent.press(screen.getByText('Save draft'));await waitFor(()=>expect(transport).toHaveBeenCalledTimes(2));
  const latest=outcome==='reverted'?'initial':'newer unsent';
  fireEvent.changeText(screen.getByPlaceholderText('Title'),latest);
  await act(async()=>pending.resolve(response(`<view xmlns="${HV}" xmlns:app="${NS}" id="form-panel"><app:realtime-page request-id="${postId}" page="1"/><app:effect/><text>Saved transition</text></view>`)));
  expect(screen.getByPlaceholderText('Title').props.value).toBe(latest);expect(effect).not.toHaveBeenCalled();expect(screen.queryByText('Saved transition')).toBeNull();
  fireEvent.press(screen.getByRole('button',{name:en.update}));expect(confirmDiscard).toHaveBeenCalledTimes(1);
  if(outcome==='new-epoch')act(()=>{const epoch=gate.resetEpoch();gate.resumeEpoch(epoch);});
  if(outcome==='background')act(()=>gate.setRetainedPaused(gate.snapshot().epoch,true));
  await act(async()=>{confirm.resolve(true);if(outcome==='paused-delivery'){await Promise.resolve();gate.setRetainedPaused(gate.snapshot().epoch,true);}});
  if(outcome==='paused-delivery'){
    expect(screen.getByPlaceholderText('Title').props.value).toBe(latest);expect(effect).not.toHaveBeenCalled();
    await act(async()=>gate.setRetainedPaused(gate.snapshot().epoch,false));expect(confirmDiscard).toHaveBeenCalledTimes(1);
  }
  if(outcome==='background'){
    expect(screen.getByPlaceholderText('Title').props.value).toBe(latest);expect(effect).not.toHaveBeenCalled();
    await act(async()=>gate.setRetainedPaused(gate.snapshot().epoch,false));expect(effect).not.toHaveBeenCalled();
    fireEvent.press(screen.getByRole('button',{name:en.update}));expect(confirmDiscard).toHaveBeenCalledTimes(2);
  }
  if(outcome!=='new-epoch'){await screen.findByText('Saved transition');expect(effect).toHaveBeenCalled();expect(gate.snapshot().lastTerminal).toMatchObject({outcome:'ack',reason:'remote-layout'});}
  else{expect(screen.queryByText('Saved transition')).toBeNull();expect(effect).not.toHaveBeenCalled();}
  expect(transport.mock.calls.filter(([,init])=>init?.method==='post')).toHaveLength(1);
 }finally{screen.unmount();}
});

it.each([{status:200,other:false},{status:422,other:false},{status:200,other:true}])('resets only the saved complete form at matching layout: %p',async({status,other})=>{
 const confirmDiscard=jest.fn(async()=>true),gate=createRealtimeGate({noticeLabels:()=>en,confirmDiscard});
 const panel=(requestId:string,value:string)=>`<view xmlns="${HV}" xmlns:app="${NS}" id="form-panel"><app:realtime-page request-id="${requestId}" page="1"/><form><text-field name="title" placeholder="Title" value="${value}"/><view href="/hv/task/edit/" verb="post" action="replace" target="form-panel"><text>Save form</text></view></form></view>`;
 const transport=jest.fn(async(input:RequestInfo|URL,init?:RequestInit):Promise<Response>=>{
  if(init?.method==='post'){const result=response(panel(id(init),'submitted'),String(input));return {...result,status};}
  return response(`<doc xmlns="${HV}" xmlns:app="${NS}"><screen><body><app:realtime mode="form" resources="tasks" refresh-href="/hv/task/edit/">${panel(id(init),transport.mock.calls.length===1?'initial':'current')}${other?'<form><text-field name="other" placeholder="Other draft" value="original"/></form>':''}</app:realtime></body></screen></doc>`,String(input));
 });
 const screen=mount(gate,transport);
 try{
  await screen.findByPlaceholderText('Title');fireEvent.changeText(screen.getByPlaceholderText('Title'),'submitted');if(other)fireEvent.changeText(screen.getByPlaceholderText('Other draft'),'unrelated unsaved');fireEvent.press(screen.getByText('Save form'));
  await waitFor(()=>expect(gate.snapshot().lastTerminal).toMatchObject({outcome:'ack',reason:'remote-layout'}));
  if(other)expect(screen.getByPlaceholderText('Other draft').props.value).toBe('unrelated unsaved');
  act(()=>gate.invalidateResources(gate.snapshot().epoch,['tasks']));await screen.findByText(en.changed);
  fireEvent.press(screen.getByRole('button',{name:en.update}));await waitFor(()=>expect(screen.getByPlaceholderText('Title').props.value).toBe('current'));
  expect(confirmDiscard).toHaveBeenCalledTimes(status===200&&!other?0:1);expect(transport.mock.calls.filter(([,init])=>init?.method==='post')).toHaveLength(1);
 }finally{screen.unmount();}
});

it.each(['post','dialog','focus-only'] as const)('tracks a real functional edit when form serialization stays unknown: %s',async timing=>{
 const large='x'.repeat(262145),later='y'+large,answer=deferred<boolean>(),pending=deferred<Response>();let postId='';
 const confirmDiscard=jest.fn(()=>answer.promise),gate=createRealtimeGate({noticeLabels:()=>en,confirmDiscard});
 const transport=jest.fn(async(input:RequestInfo|URL,init?:RequestInit):Promise<Response>=>{
  if(init?.method==='post'){postId=id(init);return pending.promise;}
  return response(`<doc xmlns="${HV}" xmlns:app="${NS}"><screen><body><app:realtime mode="form" resources="tasks" refresh-href="/hv/task/edit/"><app:realtime-page request-id="${id(init)}" page="1"/><view id="form-panel"><form><text-field name="notes" placeholder="Long notes" value="${large}"/><view href="/hv/task/edit/" verb="post" action="replace" target="form-panel"><text>Save long form</text></view></form></view></app:realtime></body></screen></doc>`,String(input));
 });
 const screen=mount(gate,transport);
 try{
  await screen.findByPlaceholderText('Long notes');
  if(timing==='dialog'){
   act(()=>gate.invalidateResources(gate.snapshot().epoch,['tasks']));await screen.findByText(en.changed);fireEvent.press(screen.getByRole('button',{name:en.update}));
   fireEvent.changeText(screen.getByPlaceholderText('Long notes'),later);await act(async()=>answer.resolve(true));
   expect(transport).toHaveBeenCalledTimes(1);expect(screen.getByPlaceholderText('Long notes').props.value).toBe(later);
  }else{
   fireEvent.press(screen.getByText('Save long form'));await waitFor(()=>expect(postId).not.toBe(''));
   if(timing==='post')fireEvent.changeText(screen.getByPlaceholderText('Long notes'),later);
   else{fireEvent(screen.getByPlaceholderText('Long notes'),'focus');fireEvent(screen.getByPlaceholderText('Long notes'),'blur');}
   await act(async()=>pending.resolve(response(`<view xmlns="${HV}" xmlns:app="${NS}" id="form-panel"><app:realtime-page request-id="${postId}" page="1"/><text>Long form response</text></view>`)));
   if(timing==='post'){expect(screen.queryByText('Long form response')).toBeNull();expect(screen.getByPlaceholderText('Long notes').props.value).toBe(later);}
   else await screen.findByText('Long form response');
  }
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
 const confirmDiscard=jest.fn(async()=>true),gate=createRealtimeGate({noticeLabels:()=>es,confirmDiscard});const transport=jest.fn(async(input:RequestInfo|URL,init?:RequestInit):Promise<Response>=>response(doc(id(init),{mode,page:mode==="list"?2:1,label:transport.mock.calls.length===1?"Before":"After"}),String(input)));const screen=mount(gate,transport);
 try{await screen.findByText("Before count");fireEvent.changeText(screen.getByPlaceholderText("Draft"),"keep unsaved");act(()=>gate.invalidateResources(gate.snapshot().epoch,["ui"]));
  await screen.findByText(es.changed);expect(screen.getByRole("alert")).toBeTruthy();for(const list of screen.UNSAFE_getAllByType(FlatList))expect(list.findAllByProps({accessibilityRole:"alert"})).toHaveLength(0);expect(screen.getByRole("button",{name:es.update})).toBeTruthy();expect(screen.getByPlaceholderText("Draft").props.value).toBe("keep unsaved");expect(transport).toHaveBeenCalledTimes(1);
  await act(async()=>gate.invalidateResources(gate.snapshot().epoch,["ui"]));expect(screen.getAllByText(es.changed)).toHaveLength(1);expect(screen.getByPlaceholderText("Draft").props.value).toBe("keep unsaved");
  fireEvent.press(screen.getByRole("button",{name:es.update}));await screen.findByText("After count");expect(confirmDiscard).toHaveBeenCalledTimes(mode==='list'?1:0);expect(transport).toHaveBeenCalledTimes(2);expect(transport.mock.calls[1][0]).toBe(mode==="list"?PAGE1:BASE);expect(screen.queryByText(es.changed)).toBeNull();
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

it("retains background drafts and admitted writes, then refreshes only after explicit discard without replay",async()=>{
 const confirmDiscard=jest.fn(async()=>true),gate=createRealtimeGate({noticeLabels:()=>es,confirmDiscard}),pending=deferred<Response>();let postId="";
 const transport=jest.fn(async(input:RequestInfo|URL,init?:RequestInit):Promise<Response>=>{if(transport.mock.calls.length===1)return response(doc(id(init)));if(transport.mock.calls.length===2){postId=id(init);return pending.promise;}return response(doc(id(init),{label:"Confirmed"}),String(input));});const screen=mount(gate,transport);
 try{await screen.findByText("Before count");fireEvent.changeText(screen.getByPlaceholderText("Draft"),"retained");fireEvent.press(screen.getByText("Save ordinary"));await waitFor(()=>expect(transport).toHaveBeenCalledTimes(2));act(()=>{gate.setRetainedPaused(gate.snapshot().epoch,true);gate.invalidateResources(gate.snapshot().epoch,["tasks"]);});await act(async()=>pending.resolve(response(`<view xmlns="${HV}" xmlns:app="${NS}" id="row-panel"><app:realtime-page request-id="${postId}" page="1"/><text>Saved</text></view>`)));expect(screen.getByPlaceholderText("Draft").props.value).toBe("retained");expect(screen.queryByText("Saved")).toBeNull();expect(transport).toHaveBeenCalledTimes(2);await act(async()=>gate.setRetainedPaused(gate.snapshot().epoch,false));await screen.findByText('Saved');expect(screen.getByPlaceholderText('Draft').props.value).toBe('retained');expect(transport).toHaveBeenCalledTimes(2);fireEvent.press(screen.getByRole('button',{name:es.update}));await screen.findByText("Confirmed count");expect(confirmDiscard).toHaveBeenCalledTimes(1);expect(transport).toHaveBeenCalledTimes(3);expect(transport.mock.calls.filter(call=>call[1]?.method==="post")).toHaveLength(1);
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
