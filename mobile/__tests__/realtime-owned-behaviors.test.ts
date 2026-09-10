jest.mock("react-native-webview",()=>({WebView:()=>null}));
import {DOMParser} from "@instawork/xmldom";
import {createSessionSupervisor} from "../src/realtime/session";
import {SESSION_HEADERS as H} from "../src/realtime/session-protocol";
import {createOwnedBehaviors,type OwnedNativePorts} from "../src/behaviors/owned";
const A="hvs1."+"A".repeat(43),B="hvs1."+"B".repeat(43),NS="https://hyperview.org/hyperview";
function deferred<T>(){let resolve!:(value:T)=>void;let reject!:(error:Error)=>void;const promise=new Promise<T>((yes,no)=>{resolve=yes;reject=no;});return{promise,resolve,reject};}
const tick=async()=>{for(let i=0;i<16;i++)await Promise.resolve();};
async function fixture(){
 let binding=A;const save=jest.fn(async(_token:string)=>{}),clear=jest.fn(async()=>{});
 const transport=jest.fn(async()=>({status:200,url:"https://app.test/hv/session-state/",headers:new Headers({[H.binding]:binding}),text:async()=>JSON.stringify({version:1,authenticated:true,binding})}) as Response);
 const supervisor=createSessionSupervisor({origin:"https://app.test",transport,storage:{enqueue:job=>job({save,clear})},onIdentity:()=>{},onTheme:()=>{},stopStream:()=>{},clock:{schedule:()=>()=>{},sleep:async()=>{}}});await supervisor.bootstrap();
 let doc=new DOMParser().parseFromString(`<doc xmlns="${NS}"><screen><body><view id="available" hide="true"><switch value="off"/></view><view id="token" hide="true"><image variant="face" hide="true"/><image variant="fingerprint" hide="true"/></view><form><text-field id="field" value=""/><image id="preview" hide="true"/><view id="current"/><behavior id="source" target="field" available-target="available" token-target="token" preview-target="preview" current-target="current"/></form></body></screen></doc>`,"application/xml") as Document;
 const element=doc.getElementById("source")!;let alive=true,focused=true;const getRoot=()=>doc,updateRoot=jest.fn((next:Document)=>{doc=next;});
 const submit=jest.fn((_token:string)=>true);let receipt:object|null=null;let settings=false;
 const source={isAlive:()=>alive,sourceIsCurrent:()=>alive&&focused,onUpdate:jest.fn(),effectReceipt:()=>receipt,bindBiometricSubmit:jest.fn(()=>submit)};
 const native={hasHardware:jest.fn(async()=>true),isEnrolled:jest.fn(async()=>true),supportedTypes:jest.fn(async()=>[2]),readToken:jest.fn(async()=>"credential" as string|null),unlock:jest.fn(async()=>({success:true})),pick:jest.fn(async()=>({canceled:false,uri:"file://synthetic"})),render:jest.fn(async(_uri:string)=>({saveAsync:async()=>({base64:"YWJj"})})),save:jest.fn(async()=>({base64:"YWJj"})),platform:"ios" as const};
 const notice=jest.fn(),notifyResources=jest.fn();const bindSource=jest.fn(()=>source);
 const behaviors=createOwnedBehaviors({supervisor,native:native as OwnedNativePorts,bindSource,isSettingsClear:()=>settings,notice,notifyResources});
 const run=(action:string)=>Promise.resolve(behaviors.find(value=>value.action===action)!.callback(element,jest.fn(),getRoot,updateRoot));
 return{supervisor,native,save,clear,notice,notifyResources,submit,source,bindSource,updateRoot,element,run,doc:()=>doc,setReceipt:(value:object|null)=>{receipt=value;},settings:()=>{settings=true;},remove:()=>{alive=false;},blur:()=>{focused=false;},setBinding:(value:string)=>{binding=value;},transport};
}

it("registers only the five existing app actions and captures a root generation",async()=>{
 const f=await fixture();f.supervisor.invalidate();f.setBinding(B);await f.supervisor.foreground();await f.run("biometric-unlock");await f.run("pick-avatar");
 expect(f.bindSource).not.toHaveBeenCalled();expect(f.native.unlock).not.toHaveBeenCalled();expect(f.native.pick).not.toHaveBeenCalled();expect(f.notice).not.toHaveBeenCalled();
});

it("binds biometric submit before native prompt and never dispatches a global event",async()=>{
 const f=await fixture(),prompt=deferred<{success:boolean}>();f.native.unlock.mockImplementationOnce(()=>prompt.promise);const task=f.run("biometric-unlock");
 expect(f.source.bindBiometricSubmit).toHaveBeenCalledTimes(1);expect(f.submit).not.toHaveBeenCalled();prompt.resolve({success:true});await task;
 expect(f.submit).toHaveBeenCalledTimes(1);expect(f.submit).toHaveBeenCalledWith("credential");expect(f.native.readToken).toHaveBeenCalledTimes(1);expect(f.save).not.toHaveBeenCalled();
});

it.each(["prompt","token"])("drops an old owner's biometric continuation after %s await",async(stage)=>{
 const f=await fixture();const delayed=deferred<unknown>();if(stage==="prompt")f.native.unlock.mockImplementationOnce(()=>delayed.promise as Promise<{success:boolean}>);else f.native.readToken.mockImplementationOnce(()=>delayed.promise as Promise<string>);
 const task=f.run("biometric-unlock");await tick();expect(stage==="prompt"?f.native.unlock:f.native.readToken).toHaveBeenCalledTimes(1);f.supervisor.invalidate();delayed.resolve(stage==="prompt"?{success:true}:"old secret");await task;
 expect(f.submit).not.toHaveBeenCalled();expect(f.notice).not.toHaveBeenCalled();expect(f.clear).not.toHaveBeenCalled();if(stage==="prompt")expect(f.native.readToken).not.toHaveBeenCalled();
});

it("retains same-owner prompt completion until real foreground confirmation",async()=>{
 const f=await fixture(),prompt=deferred<{success:boolean}>();f.native.unlock.mockImplementationOnce(()=>prompt.promise);const task=f.run("biometric-unlock");f.supervisor.pause();prompt.resolve({success:true});await tick();
 expect(f.native.readToken).not.toHaveBeenCalled();expect(f.submit).not.toHaveBeenCalled();await f.supervisor.foreground();await task;expect(f.transport).toHaveBeenCalledTimes(2);expect(f.submit).toHaveBeenCalledTimes(1);
});

it.each(["user_cancel","system_cancel","app_cancel","user_fallback"])("keeps intentional %s quiet",async(error)=>{
 const f=await fixture();f.native.unlock.mockResolvedValueOnce({success:false,error} as {success:boolean});await f.run("biometric-unlock");expect(f.notice).not.toHaveBeenCalled();expect(f.native.readToken).not.toHaveBeenCalled();
});

it("clears a missing credential only with the current lease and reports safe current failures",async()=>{
 const f=await fixture();f.native.readToken.mockResolvedValueOnce(null);await f.run("biometric-unlock");expect(f.clear).toHaveBeenCalledTimes(1);expect(f.submit).not.toHaveBeenCalled();
 f.native.unlock.mockRejectedValueOnce(new Error("native secret"));await f.run("biometric-unlock");expect(f.notice).toHaveBeenCalledWith({message:"Biometric unlock isn't available right now. Sign in with your password.",tone:"error"});
});

it("collects probe results before one public DOM update without opting in",async()=>{
 const f=await fixture(),types=deferred<number[]>();f.native.supportedTypes.mockImplementationOnce(()=>types.promise);const task=f.run("probe-biometrics");await tick();
 expect(f.doc().getElementById("available")!.getAttribute("hide")).toBe("true");types.resolve([2]);await task;
 expect(f.updateRoot).toHaveBeenCalledTimes(1);expect(f.doc().getElementById("available")!.getAttribute("hide")).toBe("false");expect(f.doc().getElementsByTagName("switch")[0].getAttribute("value")).toBe("off");
 expect(Array.from(f.doc().getElementsByTagName("image")).filter(e=>e.getAttribute("variant")).map(e=>e.getAttribute("hide"))).toEqual(["false","true"]);
});

it.each(["hasHardware","isEnrolled","readToken","supportedTypes"] as const)("stops a stale probe after %s await before further work",async(stage)=>{
 const f=await fixture(),delayed=deferred<unknown>();(f.native[stage] as jest.Mock).mockImplementationOnce(()=>delayed.promise);const task=f.run("probe-biometrics");await tick();expect(f.native[stage]).toHaveBeenCalledTimes(1);f.remove();delayed.resolve(stage==="readToken"?"token":stage==="supportedTypes"?[2]:true);await task;
 expect(f.updateRoot).not.toHaveBeenCalled();expect(f.notice).not.toHaveBeenCalled();expect(f.doc().getElementById("available")!.getAttribute("hide")).toBe("true");
 const order=["hasHardware","isEnrolled","readToken","supportedTypes"] as const;for(const next of order.slice(order.indexOf(stage)+1))expect(f.native[next]).not.toHaveBeenCalled();
});

it("prepares an avatar draft but never persists or posts it",async()=>{
 const f=await fixture();await f.run("pick-avatar");expect(f.doc().getElementById("field")!.getAttribute("value")).toBe("YWJj");expect(f.doc().getElementById("preview")!.getAttribute("source")).toBe("data:image/jpeg;base64,YWJj");expect(f.doc().getElementById("current")!.getAttribute("hide")).toBe("true");expect(f.notice).toHaveBeenCalledWith({message:"Photo ready. Tap Save settings to keep it.",tone:"success"});expect(f.updateRoot).toHaveBeenCalledTimes(1);expect(f.transport).toHaveBeenCalledTimes(1);expect(f.save).not.toHaveBeenCalled();
});

it.each(["pick","render","save"] as const)("discards picker work when source loses focus during %s",async(stage)=>{
 const f=await fixture(),delayed=deferred<unknown>();(f.native[stage] as jest.Mock).mockImplementationOnce(()=>delayed.promise);const task=f.run("pick-avatar");await tick();expect(f.native[stage]).toHaveBeenCalledTimes(1);f.blur();delayed.resolve(stage==="pick"?{canceled:false,uri:"file://old"}:stage==="render"?{}:{base64:"old"});await task;expect(f.updateRoot).not.toHaveBeenCalled();expect(f.notice).not.toHaveBeenCalled();
 const order=["pick","render","save"] as const;for(const next of order.slice(order.indexOf(stage)+1))expect(f.native[next]).not.toHaveBeenCalled();
});

it("quietly cancels picker and rejects old error callbacks and snackbar callbacks",async()=>{
 const f=await fixture();f.native.pick.mockResolvedValueOnce({canceled:true} as {canceled:boolean;uri:string});await f.run("pick-avatar");expect(f.native.render).not.toHaveBeenCalled();
 const wait=deferred<never>();void wait.promise.catch(()=>{});f.native.pick.mockImplementationOnce(()=>wait.promise);const task=f.run("pick-avatar");f.supervisor.invalidate();wait.reject(new Error("old native secret"));await task;f.element.setAttribute("message","old message");await f.run("show-snackbar");expect(f.notice).not.toHaveBeenCalled();
});

it("accepts credential-clear only from explicit settings ownership, never arbitrary token HXML",async()=>{
 const f=await fixture();await f.run("store-biometric-token");expect(f.clear).not.toHaveBeenCalled();f.settings();f.element.setAttribute("token","arbitrary");await f.run("store-biometric-token");expect(f.save).not.toHaveBeenCalled();expect(f.clear).not.toHaveBeenCalled();f.element.setAttribute("token","");await f.run("store-biometric-token");expect(f.clear).toHaveBeenCalledTimes(1);
});

it("consumes an already-awaited receipt without repeating its native effect",async()=>{
 const f=await fixture(),receipt={};await f.supervisor.lease(()=>true).clearCredential(receipt);f.setReceipt(receipt);await f.run("store-biometric-token");await f.run("store-biometric-token");expect(f.clear).toHaveBeenCalledTimes(1);expect(f.save).not.toHaveBeenCalled();
});


it("rechecks immediately after confirmation await before using the native credential",async()=>{
 const f=await fixture(),token=deferred<string>();f.native.readToken.mockImplementationOnce(()=>token.promise);const task=f.run("biometric-unlock");await tick();expect(f.native.readToken).toHaveBeenCalledTimes(1);
 token.resolve("old credential");void Promise.resolve().then(()=>f.supervisor.invalidate());await task;
 expect(f.submit).not.toHaveBeenCalled();expect(f.notice).not.toHaveBeenCalled();
});


it.each(["tasks","categories","ui","tasks categories","tasks ui","categories ui","tasks categories ui"])("delivers only canonical app-owned resource notification %s",async(value)=>{
 const f=await fixture();f.element.setAttribute("resources",value);await f.run("notify-resources");expect(f.notifyResources).toHaveBeenCalledTimes(1);expect(f.notifyResources).toHaveBeenCalledWith(f.source,value.split(" "));
});

it.each(["","tasks tasks","categories tasks","tasks private","tasks  ui"])("denies malformed resource notification %s",async(value)=>{
 const f=await fixture();f.element.setAttribute("resources",value);await f.run("notify-resources");expect(f.notifyResources).not.toHaveBeenCalled();
});

it("does not read unsupported namespaced resources or deliver old native-origin notifications",async()=>{
 const f=await fixture();f.element.setAttributeNS("https://hypertodo.app/components","app:resources","tasks");await f.run("notify-resources");expect(f.notifyResources).not.toHaveBeenCalled();f.element.setAttribute("resources","tasks");f.supervisor.invalidate();await f.run("notify-resources");expect(f.notifyResources).not.toHaveBeenCalled();
});

it("consumes the same explicit settings-clear node once across repeated callbacks",async()=>{
 const f=await fixture();f.settings();f.element.setAttribute("token","");await Promise.all([f.run("store-biometric-token"),f.run("store-biometric-token")]);await f.run("store-biometric-token");expect(f.clear).toHaveBeenCalledTimes(1);
});

it("preserves platform icon fallback when supported native types cannot be queried",async()=>{
 const f=await fixture();f.native.supportedTypes.mockRejectedValueOnce(new Error("unsupported native method"));await f.run("probe-biometrics");expect(f.updateRoot).toHaveBeenCalledTimes(1);expect(f.doc().getElementById("available")!.getAttribute("hide")).toBe("false");expect(f.notice).not.toHaveBeenCalled();expect(Array.from(f.doc().getElementsByTagName("image")).find(e=>e.getAttribute("variant")==="face")!.getAttribute("hide")).toBe("false");
});

it("reports current settings device-clear failure without claiming the server save failed",async()=>{
 const f=await fixture();f.settings();f.element.setAttribute("token","");f.clear.mockRejectedValueOnce(new Error("private native failure"));await f.run("store-biometric-token");expect(f.notice).toHaveBeenCalledWith({message:"Couldn't update device sign-in. Try again in a moment.",tone:"error"});
});

it("reports current missing-token cleanup failure and suppresses it after revocation",async()=>{
 const f=await fixture();f.native.readToken.mockResolvedValue(null);f.clear.mockRejectedValueOnce(new Error("private native failure"));await f.run("biometric-unlock");expect(f.notice).toHaveBeenCalledWith({message:"Biometric unlock isn't available right now. Sign in with your password.",tone:"error"});
 f.notice.mockClear();const pending=deferred<void>();f.clear.mockImplementationOnce(()=>pending.promise);const task=f.run("biometric-unlock");await tick();f.supervisor.invalidate();pending.reject(new Error("old failure"));await task;expect(f.notice).not.toHaveBeenCalled();expect(f.submit).not.toHaveBeenCalled();
});
