import "react-native-gesture-handler/jestSetup";
declare const __dirname: string; // Supplied by this Jest module, not the native App.
import React from "react";
import {act, fireEvent, render, waitFor, within} from "@testing-library/react-native";
import {ActivityIndicator,Alert,AppState,FlatList} from "react-native";
import {createSessionApp,LoadingScreen} from "../App";
import {AppSessionSurface, type AppSessionOptions} from "../src/realtime/app-session";
import {createThemeStore} from "../src/theme";
import {SESSION_HEADERS as H} from "../src/realtime/session-protocol";

jest.mock("expo-splash-screen",()=>({preventAutoHideAsync:jest.fn(),hideAsync:jest.fn()}));
jest.mock("lottie-react-native",()=>{
  const React=jest.requireActual("react"),{View}=jest.requireActual("react-native");
  return {__esModule:true,default:React.forwardRef((props:any,ref:any)=>{
    React.useImperativeHandle(ref,()=>({play:()=>props.onAnimationFinish?.(false),reset:()=>{}}));
    return <View {...props}/>;
  })};
});
jest.mock("react-native-safe-area-context",()=>jest.requireActual("react-native-safe-area-context/jest/mock").default);
jest.mock("react-native-webview",()=>({WebView:()=>null}));
jest.mock("expo-secure-store",()=>({getItem:()=>null,setItem:()=>{}}));
const previousState=AppState.currentState;
beforeEach(()=>{AppState.currentState="active";});
afterEach(()=>{AppState.currentState=previousState;});

const ORIGIN="https://app.test",ENTRY=ORIGIN+"/hv/",STREAM=ORIGIN+"/realtime/events/";
const A="hvs1."+"A".repeat(43),B="hvs1."+"B".repeat(43),HV="https://hyperview.org/hyperview",NS="https://hypertodo.app/components";
const transition=jest.requireActual("fs").readFileSync(jest.requireActual("path").resolve(__dirname, "../../backend/hyperview/fragments/login_transition.xml"),"utf8").replace("{{ biometric_token }}","t".repeat(43));
const logout=jest.requireActual("fs").readFileSync(jest.requireActual("path").resolve(__dirname, "../../backend/hyperview/fragments/logout_transition.xml"),"utf8");
function response(body:BodyInit|null,url:string,binding:string,status=200,type="application/vnd.hyperview+xml") {
  const result=new Response(body,{status,headers:{[H.binding]:binding,"Content-Type":type}});
  Object.defineProperty(result,"url",{value:url});return result;
}
function deferred<T>(){let resolve!:(value:T)=>void;return {promise:new Promise<T>(yes=>{resolve=yes;}),resolve:(value:T)=>resolve(value)};}
const frame=(type:string,resources?:string[])=>`event: ${type}\ndata: ${JSON.stringify({version:1,...(resources?{resources}:{})})}\n\n`;
function stream(binding=A,status=200,negotiated=false) {
  const {ReadableStream}=jest.requireActual("node:stream/web");let control!:ReadableStreamDefaultController<Uint8Array>;
  const cancel=jest.fn(),body=new ReadableStream({start:(value:typeof control)=>{control=value;},cancel});
  let held:ReturnType<typeof deferred<void>>|undefined,waiting=false;
  const getReader=body.getReader.bind(body);
  body.getReader=()=>{
    const reader=getReader(),read=reader.read.bind(reader);
    reader.read=async()=>{
      const result=await read();
      if(held){waiting=true;await held.promise;}
      return result; // Deliver the genuine completed read, never synthetic XML/ACK.
    };
    return reader;
  };
  const result=response(body,STREAM,binding,status,"text/event-stream");
  if(negotiated){result.headers.set('X-HyperTodo-Realtime-Features','changes-v2');result.headers.set('X-HyperTodo-Mutation-Seed','d'.repeat(32));}
  return {response:result,cancel,push:(value:string)=>control.enqueue(new TextEncoder().encode(value)),
    holdRead:()=>{held=deferred<void>();return {waiting:()=>waiting,release:()=>{held?.resolve();held=undefined;}};}};
}
function fixture({authenticated=true,mode="list",page=1,streamStatus=200,negotiated=false,retainedDashboard=false}={}) {
  let binding=A,loads=0,hold=false,release:(()=>void)|undefined,reject:((error:Error)=>void)|undefined,seedSequence=0;
  const events:any[]=[],streams:ReturnType<typeof stream>[]=[],save=jest.fn(async()=>{}),clear=jest.fn(async()=>{}),notice=jest.fn();
  const storage={enqueue:async(job:any)=>job({save,clear})};
  const streamFetch=jest.fn(async(_url:string,_init:RequestInit)=>{const next=stream(binding,streamStatus,negotiated);streams.push(next);return next.response;});
  const document=(id:string)=>`<doc xmlns="${HV}" xmlns:app="${NS}"><screen><body><app:realtime mode="${mode}" resources="tasks categories ui" refresh-href="/hv/tasks/?status=active&amp;category=7" target="rows"><text>Owner ${authenticated?(binding===A?"A":"B"):"anonymous"}</text><text>Count ${loads}</text><list id="rows"><item key="one"><app:realtime-page request-id="${id}" page="${page}"/><text>Row</text></item></list><form><text-field name="draft" placeholder="Draft" value="seed"/><view href="/hv/task/change/" verb="post" action="replace" target="saved"><text>Save ordinary</text></view></form><view id="saved"/><view id="login-panel"><form><text-field name="username" value="synthetic" hide="true"/><text-field name="password" value="synthetic" hide="true"/><view href="/hv/login/" verb="post" action="replace" target="login-panel"><text>Sign in B</text></view></form></view><view id="logout-panel"><view href="/hv/logout/" verb="post" action="replace" target="logout-panel"><text>Sign out</text></view></view></app:realtime></body></screen></doc>`;
  const http=jest.fn(async(input:RequestInfo|URL,init?:RequestInit)=>{
    const url=String(input),id=new Headers(init?.headers).get("X-HyperTodo-Request-ID")!;
    if(url.endsWith("session-state/"))return response(JSON.stringify({version:1,authenticated,binding}),url,binding,200,"application/json");
    if(init?.method?.toUpperCase()==="POST") {
      if(url.endsWith("/login/")||url.endsWith("/logout/")) {
        const signingIn=url.endsWith("/login/");binding=B;authenticated=signingIn;
        const result=response(signingIn?transition:logout,url,binding);result.headers.set(H.outcome,signingIn?"password-ok":"logout-ok");return result;
      }
      return response(`<view xmlns="${HV}" xmlns:app="${NS}" id="saved"><app:realtime-page request-id="${id}" page="1"/><text>Saved once</text></view>`,url,binding);
    }
    if(url===ENTRY)return response(`<doc xmlns="${HV}"><navigator id="root" type="stack"><nav-route id="home" href="${retainedDashboard?'/hv/dashboard/':'/hv/tasks/?status=active&amp;category=7'}"/></navigator></doc>`,url,binding);
    if(retainedDashboard&&url.endsWith('/edit/'))return response(`<doc xmlns="${HV}" xmlns:app="${NS}"><screen><body><app:realtime mode="form" resources="ui" refresh-href="/hv/task/edit/" target="editor"><view id="editor"><app:realtime-page request-id="${id}" page="1"/><text>Editor</text><view action="back"><text>Return to Dashboard</text></view></view></app:realtime></body></screen></doc>`,url,binding);
    loads++;let xml=document(id).replace(`page="${page}"`, `page="${new URL(url).searchParams.get("page")==="1"?1:page}"`);
    if(retainedDashboard)xml=xml.replace('refresh-href="/hv/tasks/?status=active&amp;category=7"','refresh-href="/hv/dashboard/"').replace('</app:realtime>','<view action="navigate" href="/hv/task/edit/"><text>Open editor</text></view></app:realtime>');
    const result=response(xml,url,binding);
    if(hold){const text=result.text.bind(result);result.text=async()=>{await new Promise<void>((yes,no)=>{release=yes;reject=no;});return text();};}
    return result;
  });
  const options:AppSessionOptions={
    entrypointUrl:ENTRY,http:async(input,init)=>{
      const result=await http(input,init);
      if(negotiated){result.headers.set('X-HyperTodo-Realtime-Features','changes-v2');result.headers.set('X-HyperTodo-Mutation-Seed',(++seedSequence).toString(16).padStart(32,'0'));}
      return result;
    },credentials:{read:async()=>null,storage},
    native:{platform:"ios",hasHardware:async()=>false,isEnrolled:async()=>false,supportedTypes:async()=>[],readToken:async()=>null,unlock:async()=>({success:false}),pick:async()=>({canceled:true}),render:jest.fn(),save:jest.fn()},
    onTheme:()=>{},onNotice:notice,stopStream:jest.fn(),onGateObservation:event=>{events.push(event);},
    stream:{fetch:streamFetch},
  };
  const theme=createThemeStore({read:()=>"light",write:()=>{}});
  const App=createSessionApp(options,theme),ui=render(<App/>);fireEvent(ui.getByTestId("animated-splash"),"layout");
  const session=ui.UNSAFE_getByType(AppSessionSurface).props.session as ReturnType<typeof import("../src/realtime/app-session").createAppSession>;
  return {ui,session,theme,events,http,streamFetch,streams,save,clear,notice,
    hold:()=>{hold=true;},waiting:()=>!!release,release:()=>{hold=false;release?.();release=undefined;reject=undefined;},
    fail:()=>{hold=false;reject?.(new Error('Controlled unavailable response'));release=undefined;reject=undefined;},
    close:()=>{ui.unmount();},loads:()=>loads};
}

it.each(['light','dark'] as const)('uses the existing full-area branded loader on stale Dashboard return in %s without remounting or early ACK',async theme=>{
 const f=fixture({mode:'readonly',retainedDashboard:true});
 try{
  await f.ui.findByText('Count 1');await waitFor(()=>expect(f.streamFetch).toHaveBeenCalledTimes(1));
  act(()=>f.theme.publish(theme));
  const root=f.ui.UNSAFE_getByType(f.session.gate.Root),list=f.ui.UNSAFE_getByType(FlatList),generation=f.session.snapshot().session.generation,epoch=f.session.gate.snapshot().epoch;
  fireEvent.press(f.ui.getByText('Open editor'));await f.ui.findByText('Editor');
  act(()=>f.streams[0].push(frame('invalidate',['tasks'])));await act(async()=>{});
  expect(f.loads()).toBe(1);f.hold();fireEvent.press(f.ui.getByText('Return to Dashboard'));
  await waitFor(()=>expect(f.waiting()).toBe(true));
  expect(f.ui.queryByText('Count 1')).toBeNull();expect(f.ui.getByText('Count 1',{includeHiddenElements:true})).toBeTruthy();
  const loading=f.ui.getByLabelText('Loading HyperTodo');
  expect(f.ui.UNSAFE_getByType(LoadingScreen)).toBeTruthy();
  expect(within(loading).getByText('✓')).toBeTruthy();expect(within(loading).getByText('HyperTodo')).toBeTruthy();
  expect(loading).toHaveStyle({flex:1,alignItems:'center',justifyContent:'center',backgroundColor:theme==='dark'?'#0F1118':'#F7F8FC'});
  expect(f.ui.getByTestId('realtime-content')).toHaveStyle({flex:1});
  expect(f.ui.getByTestId('realtime-loading-overlay')).toHaveStyle({position:'absolute',top:0,right:0,bottom:0,left:0});
  expect(f.ui.UNSAFE_getAllByType(ActivityIndicator)).toHaveLength(1);
  expect(f.events.filter(event=>event.reason==='reload-layout')).toHaveLength(0);expect(f.notice).not.toHaveBeenCalled();
  expect(f.ui.UNSAFE_getByType(f.session.gate.Root)).toBe(root);expect(f.ui.UNSAFE_getByType(FlatList)).toBe(list);
  await act(async()=>f.release());await f.ui.findByText('Count 2');
  expect(f.events.at(-1)).toMatchObject({outcome:'ack',reason:'reload-layout'});
  expect(f.ui.queryByLabelText('Loading HyperTodo')).toBeNull();expect(f.ui.queryByTestId('realtime-loading-overlay')).toBeNull();
  expect(f.ui.UNSAFE_getByType(f.session.gate.Root)).toBe(root);expect(f.ui.UNSAFE_getByType(FlatList)).toBe(list);
  expect(f.session.snapshot().session.generation).toBe(generation);expect(f.session.gate.snapshot().epoch).toBe(epoch);
  expect(f.http.mock.calls.filter(([url])=>String(url)===ENTRY)).toHaveLength(1);
  expect(f.http.mock.calls.filter(([,init])=>init?.method?.toUpperCase()==='POST')).toHaveLength(0);
  expect(f.streamFetch).toHaveBeenCalledTimes(1);expect(f.notice).not.toHaveBeenCalled();
 }finally{f.close();}
});

it('keeps stale Dashboard concealed on reload error and reuses branded loading for explicit GET retry',async()=>{
 const f=fixture({mode:'readonly',retainedDashboard:true});
 try{
  await f.ui.findByText('Count 1');await waitFor(()=>expect(f.streamFetch).toHaveBeenCalledTimes(1));
  const list=f.ui.UNSAFE_getByType(FlatList),root=f.ui.UNSAFE_getByType(f.session.gate.Root);
  fireEvent.press(f.ui.getByText('Open editor'));await f.ui.findByText('Editor');
  act(()=>f.streams[0].push(frame('invalidate',['tasks'])));await act(async()=>{});
  f.hold();fireEvent.press(f.ui.getByText('Return to Dashboard'));await waitFor(()=>expect(f.waiting()).toBe(true));
  await act(async()=>f.fail());
  await f.ui.findByRole('button',{name:'Update'});
  expect(f.ui.queryByLabelText('Loading HyperTodo')).toBeNull();expect(f.ui.queryByTestId('realtime-loading-overlay')).toBeNull();
  expect(f.ui.queryByText('Count 1')).toBeNull();expect(f.ui.getByText('Count 1',{includeHiddenElements:true})).toBeTruthy();
  expect(f.events.at(-1)).toMatchObject({outcome:'error',reason:'request-error'});expect(f.loads()).toBe(2);
  f.hold();fireEvent.press(f.ui.getByRole('button',{name:'Update'}));await waitFor(()=>expect(f.waiting()).toBe(true));
  expect(f.ui.getByLabelText('Loading HyperTodo')).toBeTruthy();expect(f.ui.queryByText('Count 1')).toBeNull();
  expect(f.ui.getByRole('button',{name:'Update'})).toBeDisabled();
  await act(async()=>f.release());await f.ui.findByText('Count 3');
  expect(f.ui.queryByTestId('realtime-loading-overlay')).toBeNull();expect(f.ui.queryByRole('button',{name:'Update'})).toBeNull();
  expect(f.events.at(-1)).toMatchObject({outcome:'ack',reason:'reload-layout'});expect(f.notice).not.toHaveBeenCalled();
  expect(f.ui.UNSAFE_getByType(FlatList)).toBe(list);expect(f.ui.UNSAFE_getByType(f.session.gate.Root)).toBe(root);
  expect(f.streamFetch).toHaveBeenCalledTimes(1);expect(f.http.mock.calls.filter(([,init])=>init?.method?.toUpperCase()==='POST')).toHaveLength(0);
 }finally{f.close();}
});

it("opens only after authenticated real layout and keeps one connection across resync HTTP/layout, hint and theme",async()=>{
  const f=fixture();f.hold();
  try {
    await waitFor(()=>expect(f.waiting()).toBe(true));expect(f.streamFetch).not.toHaveBeenCalled();
    await act(async()=>f.release());await f.ui.findByText("Owner A");await waitFor(()=>expect(f.streamFetch).toHaveBeenCalledTimes(1));
    expect(f.events.some(event=>event.kind==="ready")).toBe(true);
    f.hold();act(()=>f.streams[0].push(frame("resync")));await waitFor(()=>expect(f.waiting()).toBe(true));
    expect(f.session.snapshot().session.rootReady).toBe(true);expect(f.ui.queryByText("Count 2")).toBeNull();expect(f.streamFetch).toHaveBeenCalledTimes(1);
    await act(async()=>f.release());await f.ui.findByText("Count 2");expect(f.events.at(-1)).toMatchObject({outcome:"ack",reason:"reload-layout"});
    expect(f.http.mock.calls.filter(([url])=>String(url).includes("page=1"))[0][0]).toBe(ORIGIN+"/hv/tasks/?status=active&category=7&page=1");
    act(()=>f.streams[0].push(frame("invalidate",["tasks"])));await f.ui.findByText("Count 3");
    act(()=>f.theme.publish("dark"));expect(f.streamFetch).toHaveBeenCalledTimes(1);
  } finally {f.close();}
});

it('reports a visible remote refresh only after real App layout, never bootstrap resync or HTTP completion alone',async()=>{
 const f=fixture({mode:'readonly'});
 try{
  await f.ui.findByText('Owner A');await waitFor(()=>expect(f.streamFetch).toHaveBeenCalledTimes(1));
  act(()=>f.streams[0].push(frame('resync')));await f.ui.findByText('Count 2');expect(f.notice).not.toHaveBeenCalled();
  f.hold();act(()=>f.streams[0].push(frame('invalidate',['tasks'])));await waitFor(()=>expect(f.waiting()).toBe(true));expect(f.notice).not.toHaveBeenCalled();
  await act(async()=>f.release());await f.ui.findByText('Count 3');
  expect(f.notice).toHaveBeenCalledTimes(1);expect(f.notice).toHaveBeenCalledWith({message:'Updated with recent changes',tone:'success'});
  expect(f.events.at(-1)).toMatchObject({outcome:'ack',reason:'reload-layout'});expect(f.streamFetch).toHaveBeenCalledTimes(1);
 }finally{f.close();}
});

it('keeps resync and this admitted mutation silent without discarding stale evidence or a draft',async()=>{
  const f=fixture({mode:'notice',negotiated:true});
  try{
    await f.ui.findByText('Owner A');await waitFor(()=>expect(f.streamFetch).toHaveBeenCalledTimes(1));
    fireEvent.changeText(f.ui.getByPlaceholderText('Draft'),'unsaved local text');
    await act(async()=>f.streams[0].push(frame('resync')));
    expect(f.ui.queryByText('We need to check the current state')).toBeNull();
    fireEvent.press(f.ui.getByText('Save ordinary'));await f.ui.findByText('Saved once');
    const post=f.http.mock.calls.find(([url,init])=>String(url).includes('/task/change/')&&init?.method==='POST')!;
    const mutationId=new Headers(post[1]?.headers).get('X-HyperTodo-Mutation-ID');
    expect(mutationId).toBe('d'.repeat(32)+'00000001');
    await act(async()=>f.streams[0].push(`event: invalidate\ndata: ${JSON.stringify({version:2,resources:['tasks'],mutation_id:mutationId,entities:null})}\n\n`));
    expect(f.ui.queryByText('There may be changes')).toBeNull();
    expect(f.session.gate.snapshot().routes[0].notice).toBe(true);
    expect(f.ui.getByPlaceholderText('Draft').props.value).toBe('unsaved local text');
    await act(async()=>f.streams[0].push(`event: invalidate\ndata: ${JSON.stringify({version:2,resources:['tasks'],mutation_id:'e'.repeat(40),entities:null})}\n\n`));
    await f.ui.findByText('There may be changes');
    expect(f.http.mock.calls.filter(([,init])=>init?.method==='POST')).toHaveLength(1);
  }finally{f.close();}
});

it('keeps a current own echo silent after more than32 negotiated HTTP responses in one real App owner',async()=>{
 const f=fixture({mode:'readonly',negotiated:true});
 try{
  await f.ui.findByText('Owner A');await waitFor(()=>expect(f.streamFetch).toHaveBeenCalledTimes(1));
  for(let index=2;index<=36;index++){act(()=>f.streams[0].push(frame('resync')));await f.ui.findByText('Count '+index);}
  expect(f.notice).not.toHaveBeenCalled();fireEvent.press(f.ui.getByText('Save ordinary'));await f.ui.findByText('Saved once');
  const post=f.http.mock.calls.find(([url,init])=>String(url).endsWith('/task/change/')&&init?.method==='POST')!;
  const mutationId=new Headers(post[1]?.headers).get('X-HyperTodo-Mutation-ID');expect(mutationId).toMatch(/^[a-f0-9]{40}$/);
  act(()=>f.streams[0].push(`event: invalidate\ndata: ${JSON.stringify({version:2,resources:['tasks'],mutation_id:mutationId,entities:null})}\n\n`));
  await f.ui.findByText('Count 37');expect(f.notice).not.toHaveBeenCalled();expect(f.ui.queryByText('There may be changes')).toBeNull();
  expect(f.http.mock.calls.filter(([,init])=>init?.method==='POST')).toHaveLength(1);expect(f.streamFetch).toHaveBeenCalledTimes(1);
 }finally{f.close();}
});

it.each(["notice","pages"])("keeps %s drafts with neutral resync; pending invalidate survives resync and matching ACK only covers admitted versions",async policy=>{
  const f=fixture({mode:policy==="notice"?"notice":"list",page:policy==="pages"?2:1});
  const dialog=jest.spyOn(Alert,'alert').mockImplementation(()=>{});
  try {
    await f.ui.findByText("Owner A");await waitFor(()=>expect(f.streamFetch).toHaveBeenCalledTimes(1));
    fireEvent.changeText(f.ui.getByPlaceholderText("Draft"),"retained draft");
    await act(async()=>f.streams[0].push(frame("resync")));expect(f.ui.queryByText("We need to check the current state")).toBeNull();
    expect(f.session.gate.snapshot().routes[0].notice).toBe(true);
    expect(f.loads()).toBe(1);expect(f.ui.getByPlaceholderText("Draft").props.value).toBe("retained draft");
    act(()=>f.streams[0].push(frame("invalidate",["tasks"])+frame("resync")));await f.ui.findByText("There may be changes");
    expect(f.ui.queryByText("We need to check the current state")).toBeNull();
    f.hold();fireEvent.press(f.ui.getByRole("button",{name:"Update"}));
    if(policy==='pages'){
      expect(dialog).toHaveBeenCalledWith('Discard unsaved edits?',expect.any(String),expect.any(Array),expect.any(Object));
      expect(f.waiting()).toBe(false);await act(async()=>dialog.mock.calls.at(-1)![2]!.find(button=>button.style==='destructive')!.onPress!());
    }
    await waitFor(()=>expect(f.waiting()).toBe(true));
    if(policy==="notice")act(()=>f.streams[0].push(frame("resync")));
    await act(async()=>f.release());await f.ui.findByText("Count 2");
    if(policy==="notice"){
      expect(f.ui.queryByText("We need to check the current state")).toBeNull();expect(f.ui.queryByText("There may be changes")).toBeNull();expect(f.loads()).toBe(2);
      // The later resync is still unacknowledged, merely silent. A subsequent
      // remote invalidation remains actionable and covers both at its real ACK.
      expect(f.session.gate.snapshot().routes[0].notice).toBe(true);
      await act(async()=>f.streams[0].push(frame('invalidate',['tasks'])));await f.ui.findByText('There may be changes');
      fireEvent.press(f.ui.getByRole("button",{name:"Update"}));await f.ui.findByText("Count 3");
    }else{
      expect(f.session.gate.snapshot().routes[0].pages).toEqual([1]);
      expect(f.http.mock.calls.at(-1)![0]).toBe(ORIGIN+"/hv/tasks/?status=active&category=7&page=1");
    }
    expect(f.ui.queryByRole("alert")).toBeNull();expect(f.streamFetch).toHaveBeenCalledTimes(1);
  } finally {dialog.mockRestore();f.close();}
});

it("does not open for anonymous identity and aborts on literal logout without clearing credentials itself",async()=>{
  const anonymous=fixture({authenticated:false});try{await anonymous.ui.findByText("Owner anonymous");expect(anonymous.streamFetch).not.toHaveBeenCalled();}finally{anonymous.close();}
  const f=fixture();try{
    await f.ui.findByText("Owner A");await waitFor(()=>expect(f.streamFetch).toHaveBeenCalledTimes(1));
    fireEvent.press(f.ui.getByText("Sign out"));await f.ui.findByText("Owner anonymous");
    expect(f.streamFetch.mock.calls[0][1].signal?.aborted).toBe(true);expect(f.streamFetch).toHaveBeenCalledTimes(1);
    expect(f.http.mock.calls.filter(([,init])=>init?.method?.toUpperCase()==="POST")).toHaveLength(1);
  }finally{f.close();}
});

it("retains the same Root/draft across background confirmation and discards A pending read before opening the resumed connection",async()=>{
  const f=fixture({mode:"notice"});try{
    await f.ui.findByText("Owner A");await waitFor(()=>expect(f.streamFetch).toHaveBeenCalledTimes(1));
    const root=f.ui.UNSAFE_getByType(f.session.gate.Root);fireEvent.changeText(f.ui.getByPlaceholderText("Draft"),"keep");
    act(()=>{f.streams[0].push(frame("invalidate",["tasks"]));f.session.pause();});
    expect(f.streamFetch.mock.calls[0][1].signal?.aborted).toBe(true);
    await act(async()=>{await f.session.foreground();});await waitFor(()=>expect(f.streamFetch).toHaveBeenCalledTimes(2));
    expect(f.ui.UNSAFE_getByType(f.session.gate.Root)).toBe(root);expect(f.ui.getByPlaceholderText("Draft").props.value).toBe("keep");
    expect(f.ui.queryByText("There may be changes")).toBeNull();expect(f.save).not.toHaveBeenCalled();expect(f.clear).not.toHaveBeenCalled();
  }finally{f.close();}
});

it("rejects a late A401 after B login and never reconnects B from A data or errors",async()=>{
  const f=fixture(),late=deferred<Response>();f.streamFetch.mockImplementationOnce(()=>late.promise);
  try {
    await f.ui.findByText("Owner A");await waitFor(()=>expect(f.streamFetch).toHaveBeenCalledTimes(1));
    fireEvent.press(f.ui.getByText("Sign in B"));await f.ui.findByText("Owner B");await waitFor(()=>expect(f.streamFetch).toHaveBeenCalledTimes(2));
    const stale=stream(A,401);await act(async()=>late.resolve(stale.response));expect(stale.cancel).toHaveBeenCalledTimes(1);
    expect(f.session.snapshot().session.identity?.binding).toBe(B);expect(f.session.snapshot().session.availability).toBe("foreground");
    expect(f.streamFetch).toHaveBeenCalledTimes(2);expect(f.clear).not.toHaveBeenCalled();
  }finally{f.close();}
});

it("discards an already-settling A read after B auth admission without applying its hint or auth-required to B",async()=>{
  const f=fixture({mode:"notice"});let held:ReturnType<ReturnType<typeof stream>["holdRead"]>|undefined;try{
    await f.ui.findByText("Owner A");await waitFor(()=>expect(f.streamFetch).toHaveBeenCalledTimes(1));
    held=f.streams[0].holdRead();act(()=>f.streams[0].push(frame("invalidate",["tasks"])+frame("auth-required")));
    await waitFor(()=>expect(held!.waiting()).toBe(true));
    fireEvent.press(f.ui.getByText("Sign in B"));
    await f.ui.findByText("Owner B");await waitFor(()=>expect(f.streamFetch).toHaveBeenCalledTimes(2));
    await act(async()=>held!.release());
    expect(f.streams[0].cancel).toHaveBeenCalledTimes(1);
    expect(f.ui.queryByText("There may be changes")).toBeNull();expect(f.ui.queryByText("We could not confirm your session")).toBeNull();
    expect(f.session.snapshot().session.identity?.binding).toBe(B);expect(f.clear).not.toHaveBeenCalled();
    expect(f.http.mock.calls.filter(([,init])=>init?.method?.toUpperCase()==="POST")).toHaveLength(1);
  }finally{held?.release();f.close();}
});

it("keeps HTTP and the exact draft available after a stream network failure without changing authentication",async()=>{
  const f=fixture({mode:"notice"});f.streamFetch.mockRejectedValueOnce(new Error("network"));
  try{
    await f.ui.findByText("Owner A");await waitFor(()=>expect(f.streamFetch).toHaveBeenCalledTimes(1));
    const input=f.ui.getByPlaceholderText("Draft");fireEvent.changeText(input,"not lost");
    fireEvent.press(f.ui.getByText("Save ordinary"));await f.ui.findByText("Saved once");
    expect(f.ui.getByPlaceholderText("Draft")).toBe(input);expect(input.props.value).toBe("not lost");
    expect(f.session.snapshot().session.availability).toBe("foreground");expect(f.session.snapshot().session.identity?.binding).toBe(A);
    expect(f.clear).not.toHaveBeenCalled();expect(f.save).not.toHaveBeenCalled();
  }finally{f.close();}
});

it.each([401,403,"auth-required"])("protects only the current generation on %s without credential clearing or an auth POST",async status=>{
  const f=fixture({streamStatus:typeof status==="number"?status:200});try{
    await waitFor(()=>expect(f.streamFetch).toHaveBeenCalledTimes(1));
    if(status==="auth-required")act(()=>f.streams[0].push(frame("auth-required")));
    await f.ui.findByText("We could not confirm your session");
    expect(f.session.snapshot().session.identity).toBeNull();expect(f.ui.queryByText("Owner A")).toBeNull();
    expect(f.clear).not.toHaveBeenCalled();expect(f.save).not.toHaveBeenCalled();expect(f.http.mock.calls.filter(([,init])=>init?.method?.toUpperCase()==="POST")).toHaveLength(0);
  }finally{f.close();}
});

it("keeps ordinary HTTP and drafts working with404 disabled until a new foreground activation",async()=>{
  const f=fixture({streamStatus:404,mode:"notice"});try{
    await f.ui.findByText("Owner A");await waitFor(()=>expect(f.streamFetch).toHaveBeenCalledTimes(1));
    fireEvent.changeText(f.ui.getByPlaceholderText("Draft"),"available offline");fireEvent.press(f.ui.getByText("Save ordinary"));await f.ui.findByText("Saved once");
    act(()=>f.theme.publish("dark"));expect(f.streamFetch).toHaveBeenCalledTimes(1);expect(f.ui.getByPlaceholderText("Draft").props.value).toBe("available offline");
    await act(async()=>{f.session.pause();await f.session.foreground();});await waitFor(()=>expect(f.streamFetch).toHaveBeenCalledTimes(2));
    expect(f.http.mock.calls.filter(([,init])=>init?.method?.toUpperCase()==="POST")).toHaveLength(1);
  }finally{f.close();}
});
