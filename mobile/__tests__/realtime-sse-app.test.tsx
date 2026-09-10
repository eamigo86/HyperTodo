import "react-native-gesture-handler/jestSetup";
declare const __dirname: string; // Supplied by this Jest module, not the native App.
import React from "react";
import {act, fireEvent, render, waitFor} from "@testing-library/react-native";
import {AppState} from "react-native";
import {createSessionApp} from "../App";
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
function stream(binding=A,status=200) {
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
  return {response:response(body,STREAM,binding,status,"text/event-stream"),cancel,push:(value:string)=>control.enqueue(new TextEncoder().encode(value)),
    holdRead:()=>{held=deferred<void>();return {waiting:()=>waiting,release:()=>{held?.resolve();held=undefined;}};}};
}
function fixture({authenticated=true,mode="list",page=1,streamStatus=200}={}) {
  let binding=A,loads=0,hold=false,release:(()=>void)|undefined;
  const events:any[]=[],streams:ReturnType<typeof stream>[]=[],save=jest.fn(async()=>{}),clear=jest.fn(async()=>{});
  const storage={enqueue:async(job:any)=>job({save,clear})};
  const streamFetch=jest.fn(async(_url:string,_init:RequestInit)=>{const next=stream(binding,streamStatus);streams.push(next);return next.response;});
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
    if(url===ENTRY)return response(`<doc xmlns="${HV}"><navigator id="root" type="stack"><nav-route id="home" href="/hv/tasks/?status=active&amp;category=7"/></navigator></doc>`,url,binding);
    loads++;const result=response(document(id).replace(`page="${page}"`, `page="${new URL(url).searchParams.get("page")==="1"?1:page}"`),url,binding);
    if(hold){const text=result.text.bind(result);result.text=async()=>{await new Promise<void>(yes=>{release=yes;});return text();};}
    return result;
  });
  const options:AppSessionOptions={
    entrypointUrl:ENTRY,http,credentials:{read:async()=>null,storage},
    native:{platform:"ios",hasHardware:async()=>false,isEnrolled:async()=>false,supportedTypes:async()=>[],readToken:async()=>null,unlock:async()=>({success:false}),pick:async()=>({canceled:true}),render:jest.fn(),save:jest.fn()},
    onTheme:()=>{},onNotice:()=>{},stopStream:jest.fn(),onGateObservation:event=>{events.push(event);},
    stream:{fetch:streamFetch},
  };
  const theme=createThemeStore({read:()=>"light",write:()=>{}});
  const App=createSessionApp(options,theme),ui=render(<App/>);fireEvent(ui.getByTestId("animated-splash"),"layout");
  const session=ui.UNSAFE_getByType(AppSessionSurface).props.session as ReturnType<typeof import("../src/realtime/app-session").createAppSession>;
  return {ui,session,theme,events,http,streamFetch,streams,save,clear,
    hold:()=>{hold=true;},waiting:()=>!!release,release:()=>{hold=false;release?.();release=undefined;},
    close:()=>{ui.unmount();},loads:()=>loads};
}

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

it.each(["notice","pages"])("keeps %s drafts with neutral resync; pending invalidate survives resync and matching ACK only covers admitted versions",async policy=>{
  const f=fixture({mode:policy==="notice"?"notice":"list",page:policy==="pages"?2:1});
  try {
    await f.ui.findByText("Owner A");await waitFor(()=>expect(f.streamFetch).toHaveBeenCalledTimes(1));
    fireEvent.changeText(f.ui.getByPlaceholderText("Draft"),"retained draft");
    act(()=>f.streams[0].push(frame("resync")));await f.ui.findByText("We need to check the current state");
    expect(f.loads()).toBe(1);expect(f.ui.getByPlaceholderText("Draft").props.value).toBe("retained draft");
    act(()=>f.streams[0].push(frame("invalidate",["tasks"])+frame("resync")));await f.ui.findByText("There may be changes");
    expect(f.ui.queryByText("We need to check the current state")).toBeNull();
    f.hold();fireEvent.press(f.ui.getByRole("button",{name:"Update"}));await waitFor(()=>expect(f.waiting()).toBe(true));
    if(policy==="notice")act(()=>f.streams[0].push(frame("resync")));
    await act(async()=>f.release());await f.ui.findByText("Count 2");
    if(policy==="notice"){
      await f.ui.findByText("We need to check the current state");expect(f.ui.queryByText("There may be changes")).toBeNull();expect(f.loads()).toBe(2);
      fireEvent.press(f.ui.getByRole("button",{name:"Update"}));await f.ui.findByText("Count 3");
    }else{
      expect(f.session.gate.snapshot().routes[0].pages).toEqual([1]);
      expect(f.http.mock.calls.at(-1)![0]).toBe(ORIGIN+"/hv/tasks/?status=active&category=7&page=1");
    }
    expect(f.ui.queryByRole("alert")).toBeNull();expect(f.streamFetch).toHaveBeenCalledTimes(1);
  } finally {f.close();}
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
