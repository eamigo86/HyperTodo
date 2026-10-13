jest.mock("react-native-webview",()=>({WebView:()=>null}));
import {DOMParser} from "@instawork/xmldom";
import {createSessionSupervisor} from "../src/realtime/session";
import {SESSION_HEADERS as H} from "../src/realtime/session-protocol";
import {createOwnedBehaviors,type OwnedNativePorts} from "../src/behaviors/owned";
import {hyperviewLogger} from "../src/feedback/logging";
const A="hvs1."+"A".repeat(43),B="hvs1."+"B".repeat(43),NS="https://hyperview.org/hyperview";
function deferred<T>(){let resolve!:(value:T)=>void;let reject!:(error:Error)=>void;const promise=new Promise<T>((yes,no)=>{resolve=yes;reject=no;});return{promise,resolve,reject};}
const tick=async()=>{for(let i=0;i<16;i++)await Promise.resolve();};
// The diagnostics go to the console in the app; keep them out of the test output.
let warn:jest.SpyInstance;
beforeEach(()=>{warn=jest.spyOn(hyperviewLogger,"warn").mockImplementation(()=>{});});
afterEach(()=>warn.mockRestore());
async function fixture(){
 let binding=A;const save=jest.fn(async(_token:string)=>{}),clear=jest.fn(async()=>{});
 const transport=jest.fn(async()=>({status:200,url:"https://app.test/hv/session-state/",headers:new Headers({[H.binding]:binding}),text:async()=>JSON.stringify({version:1,authenticated:true,binding})}) as Response);
 const supervisor=createSessionSupervisor({origin:"https://app.test",transport,storage:{enqueue:job=>job({save,clear})},onIdentity:()=>{},onTheme:()=>{},stopStream:()=>{},clock:{schedule:()=>()=>{},sleep:async()=>{}}});await supervisor.bootstrap();
 let doc=new DOMParser().parseFromString(`<doc xmlns="${NS}"><screen><body><view id="available" hide="true"><switch value="off"/></view><view id="token" hide="true"><image variant="face" hide="true"/><image variant="fingerprint" hide="true"/></view><form><text-field id="field" value=""/><image id="preview" hide="true"/><view id="current"/><behavior id="source" target="field" available-target="available" token-target="token" preview-target="preview" current-target="current"/></form></body></screen></doc>`,"application/xml") as Document;
 const element=doc.getElementById("source")!;let alive=true,focused=true;const getRoot=()=>doc,updateRoot=jest.fn((next:Document)=>{doc=next;});
 const submit=jest.fn((_token:string)=>true);let receipt:object|null=null;let settings=false;
 const source={isAlive:()=>alive,sourceIsCurrent:()=>alive&&focused,onUpdate:jest.fn(),effectReceipt:()=>receipt,bindBiometricSubmit:jest.fn(()=>submit),markDraftEdit:jest.fn()};
 const native={hasHardware:jest.fn(async()=>true),isEnrolled:jest.fn(async()=>true),supportedTypes:jest.fn(async()=>[2]),readToken:jest.fn(async()=>"credential" as string|null),unlock:jest.fn(async()=>({success:true})),pick:jest.fn(async()=>({canceled:false,uri:"file://synthetic"})),render:jest.fn(async(_uri:string)=>({saveAsync:async()=>({base64:"YWJj"})})),save:jest.fn(async()=>({base64:"YWJj"})),platform:"ios" as const};
 const notice=jest.fn(),notifyResources=jest.fn();const bindSource=jest.fn(()=>source);
 const behaviors=createOwnedBehaviors({supervisor,native:native as OwnedNativePorts,bindSource,isSettingsClear:()=>settings,notice,notifyResources});
 const run=(action:string)=>Promise.resolve(behaviors.find(value=>value.action===action)!.callback(element,jest.fn(),getRoot,updateRoot));
 return{supervisor,native,save,clear,notice,notifyResources,submit,source,bindSource,updateRoot,element,run,doc:()=>doc,setReceipt:(value:object|null)=>{receipt=value;},settings:()=>{settings=true;},remove:()=>{alive=false;},blur:()=>{focused=false;},setBinding:(value:string)=>{binding=value;},transport};
}

it("registers only the six existing app actions and captures a root generation",async()=>{
 const f=await fixture();f.supervisor.invalidate();f.setBinding(B);await f.supervisor.foreground();await f.run("biometric-unlock");await f.run("pick-avatar");
 expect(f.bindSource).not.toHaveBeenCalled();expect(f.native.unlock).not.toHaveBeenCalled();expect(f.native.pick).not.toHaveBeenCalled();expect(f.notice).not.toHaveBeenCalled();
});

it("binds biometric submit before native prompt and never dispatches a global event",async()=>{
 const f=await fixture(),prompt=deferred<{success:boolean}>();f.native.unlock.mockImplementationOnce(()=>prompt.promise);const task=f.run("biometric-unlock");
 expect(f.source.bindBiometricSubmit).toHaveBeenCalledTimes(1);expect(f.submit).not.toHaveBeenCalled();prompt.resolve({success:true});await task;
 expect(f.submit).toHaveBeenCalledTimes(1);expect(f.submit).toHaveBeenCalledWith("credential");expect(f.native.readToken).toHaveBeenCalledTimes(1);expect(f.save).not.toHaveBeenCalled();
});

it("prompts with the HXML text and falls back to the default when the attribute is missing or empty",async()=>{
 // xmldom answers "" for a missing attribute, so only a falsy check reaches the default.
 const f=await fixture();f.element.setAttribute("prompt","Unlock your tasks");await f.run("biometric-unlock");
 expect(f.native.unlock).toHaveBeenLastCalledWith("Unlock your tasks");
 f.element.removeAttribute("prompt");await f.run("biometric-unlock");expect(f.native.unlock).toHaveBeenLastCalledWith("Sign in to HyperTodo");
 f.element.setAttribute("prompt","");await f.run("biometric-unlock");expect(f.native.unlock).toHaveBeenLastCalledWith("Sign in to HyperTodo");
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
 expect(f.updateRoot).toHaveBeenCalledTimes(1);expect(f.doc().getElementById("available")!.getAttribute("hide")).toBe("false");expect(f.doc().getElementById("token")!.getAttribute("hide")).toBe("false");expect(f.doc().getElementsByTagName("switch")[0].getAttribute("value")).toBe("off");
 expect(Array.from(f.doc().getElementsByTagName("image")).filter(e=>e.getAttribute("variant")).map(e=>e.getAttribute("hide"))).toEqual(["false","true"]);
});

it.each([["has no biometric hardware","hasHardware"],["has no strong biometric enrolled","isEnrolled"]] as const)("offers nothing when the device %s",async(_label,port)=>{
 const f=await fixture();f.native[port].mockResolvedValueOnce(false);await f.run("probe-biometrics");
 expect(f.updateRoot).not.toHaveBeenCalled();expect(f.doc().getElementById("available")!.getAttribute("hide")).toBe("true");expect(f.native.readToken).not.toHaveBeenCalled();expect(f.notice).not.toHaveBeenCalled();
});

it.each(["hasHardware","isEnrolled","readToken","supportedTypes"] as const)("stops a stale probe after %s await before further work",async(stage)=>{
 const f=await fixture(),delayed=deferred<unknown>();(f.native[stage] as jest.Mock).mockImplementationOnce(()=>delayed.promise);const task=f.run("probe-biometrics");await tick();expect(f.native[stage]).toHaveBeenCalledTimes(1);f.remove();delayed.resolve(stage==="readToken"?"token":stage==="supportedTypes"?[2]:true);await task;
 expect(f.updateRoot).not.toHaveBeenCalled();expect(f.notice).not.toHaveBeenCalled();expect(f.doc().getElementById("available")!.getAttribute("hide")).toBe("true");
 const order=["hasHardware","isEnrolled","readToken","supportedTypes"] as const;for(const next of order.slice(order.indexOf(stage)+1))expect(f.native[next]).not.toHaveBeenCalled();
});

it("logs only the code of a refused unlock and nothing for an intentional dismissal",async()=>{
 const f=await fixture();f.native.unlock.mockResolvedValueOnce({success:false,error:"user_cancel"} as {success:boolean});await f.run("biometric-unlock");
 expect(warn).not.toHaveBeenCalled();
 f.native.unlock.mockResolvedValueOnce({success:false,error:"lockout"} as {success:boolean});await f.run("biometric-unlock");
 expect(warn.mock.calls).toEqual([["biometric unlock refused","lockout"]]);
});

it("logs only the code of a crashed unlock or failed pick, never its message",async()=>{
 const f=await fixture();
 f.native.unlock.mockRejectedValueOnce(Object.assign(new Error("native secret"),{code:"ERR_BIOMETRIC"}));await f.run("biometric-unlock");
 f.native.pick.mockRejectedValueOnce(Object.assign(new Error("file://private/photo.jpg"),{code:"E_PICKER"}));await f.run("pick-avatar");
 f.native.pick.mockRejectedValueOnce(new Error("no code here"));await f.run("pick-avatar");
 expect(warn.mock.calls).toEqual([["biometric-unlock failed","ERR_BIOMETRIC"],["pick-avatar failed","E_PICKER"],["pick-avatar failed","unknown"]]);
});

it.each(["hasHardware","isEnrolled","readToken"] as const)("keeps the probe silent when %s rejects",async(stage)=>{
 const f=await fixture();f.native[stage].mockRejectedValueOnce(new Error("native secret"));
 await expect(f.run("probe-biometrics")).resolves.toBeUndefined();
 expect(f.notice).not.toHaveBeenCalled();expect(f.updateRoot).not.toHaveBeenCalled();expect(f.doc().getElementById("available")!.getAttribute("hide")).toBe("true");
});

it("prepares an avatar draft but never persists or posts it",async()=>{
 const f=await fixture();await f.run("pick-avatar");expect(f.doc().getElementById("field")!.getAttribute("value")).toBe("YWJj");expect(f.doc().getElementById("preview")!.getAttribute("source")).toBe("data:image/jpeg;base64,YWJj");expect(f.doc().getElementById("preview")!.getAttribute("hide")).toBe("false");expect(f.doc().getElementById("current")!.getAttribute("hide")).toBe("true");expect(f.notice).toHaveBeenCalledWith({message:"Photo ready. Tap Save settings to keep it.",tone:"success"});expect(f.updateRoot).toHaveBeenCalledTimes(1);expect(f.transport).toHaveBeenCalledTimes(1);expect(f.save).not.toHaveBeenCalled();
});

it('marks the live avatar field before a real value edit, not for identical picker output',async()=>{
 const f=await fixture(),seen:string[]=[];
 f.source.markDraftEdit.mockImplementation((field:Element)=>{seen.push(field.getAttribute('value')!);});
 await f.run('pick-avatar');expect(seen).toEqual(['']);expect(f.source.markDraftEdit).toHaveBeenCalledTimes(1);
 await f.run('pick-avatar');expect(f.source.markDraftEdit).toHaveBeenCalledTimes(1);
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

// The behaviors below carry contracts that used to be asserted on the retired singleton versions: the copy a failed
// prompt shows, the glyph a device reports, and the photo-picker failure paths.
const UNLOCK_FAILED={message:"Biometric unlock isn't available right now. Sign in with your password.",tone:"error"};
type Fixture=Awaited<ReturnType<typeof fixture>>;
const glyphs=(f:Fixture)=>Object.fromEntries(Array.from(f.doc().getElementsByTagName("image")).filter(e=>e.getAttribute("variant")).map(e=>[e.getAttribute("variant"),e.getAttribute("hide")]));

it.each(["lockout","not_enrolled","authentication_failed","missing_usage_description"])("explains an unexpected %s refusal once, without leaking its code",async(error)=>{
 const f=await fixture();f.native.unlock.mockResolvedValueOnce({success:false,error} as {success:boolean});await f.run("biometric-unlock");
 expect(f.notice).toHaveBeenCalledTimes(1);expect(f.notice).toHaveBeenCalledWith(UNLOCK_FAILED);expect(f.native.readToken).not.toHaveBeenCalled();expect(f.submit).not.toHaveBeenCalled();
});

it("passes the prompt copy authored in the HXML",async()=>{
 const f=await fixture();f.element.setAttribute("prompt","Unlock HyperTodo");await f.run("biometric-unlock");expect(f.native.unlock).toHaveBeenCalledWith("Unlock HyperTodo");
});

// Android reports hardware presence rather than enrolment and may list several modalities, so only a lone face
// modality earns the face glyph; an empty report (iOS Optic ID, an OEM with no feature string) falls back to the platform.
it.each([
 [[2],"ios","face"],[[1],"ios","fingerprint"],[[1,2],"android","fingerprint"],[[3],"android","fingerprint"],
 [[],"ios","face"],[[],"android","fingerprint"],
] as const)("shows only the glyph the device reports (%j on %s)",async(types,platform,shown)=>{
 const f=await fixture();(f.native as {platform:string}).platform=platform;f.native.supportedTypes.mockResolvedValueOnce([...types]);await f.run("probe-biometrics");
 expect(glyphs(f)).toEqual({face:shown==="face"?"false":"true",fingerprint:shown==="fingerprint"?"false":"true"});
});

it("offers only the opt-in row, and touches no glyph, when the device holds no token",async()=>{
 const f=await fixture();f.native.readToken.mockResolvedValueOnce(null);await f.run("probe-biometrics");
 expect(f.native.supportedTypes).not.toHaveBeenCalled();expect(f.doc().getElementById("available")!.getAttribute("hide")).toBe("false");expect(f.doc().getElementById("token")!.getAttribute("hide")).toBe("true");
 expect(glyphs(f)).toEqual({face:"true",fingerprint:"true"});expect(f.doc().getElementsByTagName("switch")[0].getAttribute("value")).toBe("off");
});

it("says so, without leaking the raw error, when the photo picker fails",async()=>{
 const f=await fixture();f.native.pick.mockRejectedValueOnce(new Error("no photos"));await f.run("pick-avatar");
 expect(f.updateRoot).not.toHaveBeenCalled();expect(f.notice).toHaveBeenCalledTimes(1);expect(f.notice).toHaveBeenCalledWith({message:"Couldn't open your photos. Try again in a moment.",tone:"error"});
});

it("posts nothing when the encoder returns no data or the target field is not on the screen",async()=>{
 const f=await fixture();f.native.save.mockResolvedValueOnce({} as {base64:string});await f.run("pick-avatar");expect(f.updateRoot).not.toHaveBeenCalled();
 f.element.setAttribute("target","missing");await f.run("pick-avatar");expect(f.updateRoot).not.toHaveBeenCalled();expect(f.notice).not.toHaveBeenCalled();
});

it("still arms the avatar field when the panel ships no preview targets",async()=>{
 const f=await fixture();f.element.removeAttribute("preview-target");f.element.removeAttribute("current-target");await f.run("pick-avatar");
 expect(f.updateRoot).toHaveBeenCalledTimes(1);expect(f.doc().getElementById("field")!.getAttribute("value")).toBe("YWJj");
});

it("publishes a trimmed snackbar, success only when the HXML says so, and nothing for a blank message",async()=>{
 const f=await fixture();f.element.setAttribute("message","  Task created.  ");f.element.setAttribute("tone","success");await f.run("show-snackbar");expect(f.notice).toHaveBeenLastCalledWith({message:"Task created.",tone:"success"});
 f.element.removeAttribute("tone");await f.run("show-snackbar");expect(f.notice).toHaveBeenLastCalledWith({message:"Task created.",tone:"error"});
 f.notice.mockClear();f.element.setAttribute("message","   ");await f.run("show-snackbar");expect(f.notice).not.toHaveBeenCalled();
});
