import {shallowCloneToRoot,Namespaces} from "hyperview";
import type {SaveOptions} from "expo-image-manipulator";
import type {HvBehavior,HvComponentOnUpdate,HvGetRoot,HvUpdateRoot} from "hyperview";
import type {createSessionSupervisor,RecoveryHandle} from "../realtime/session";
import type {SnackbarNotice} from "../feedback/snackbar";
export type SourceAuthority={isAlive():boolean;sourceIsCurrent():boolean;onUpdate:HvComponentOnUpdate;effectReceipt():object|null;bindBiometricSubmit():((token:string)=>boolean)|null;markDraftEdit?(field:Element):void};
export type RenderedImage={saveAsync(options:SaveOptions):Promise<{base64?:string}>};
export type OwnedNativePorts={platform:"ios"|"android";hasHardware():Promise<boolean>;isEnrolled():Promise<boolean>;supportedTypes():Promise<number[]>;readToken():Promise<string|null>;unlock(prompt:string):Promise<{success:boolean;error?:string}>;pick():Promise<{canceled:boolean;uri?:string}>;render(uri:string):Promise<RenderedImage>;save(image:RenderedImage):Promise<{base64?:string}>};
export type ResourceName="tasks"|"categories"|"ui";
export type OwnedBehaviorPorts={recovery?:RecoveryHandle;supervisor:ReturnType<typeof createSessionSupervisor>;native:OwnedNativePorts;bindSource(element:Element,callbacks:{getRoot:HvGetRoot;updateRoot:HvUpdateRoot}):SourceAuthority|null;isSettingsClear(element:Element,source:SourceAuthority):boolean;notice(value:SnackbarNotice):void;notifyResources(source:SourceAuthority,resources:readonly ResourceName[]):void};

const DISMISSED=new Set(["app_cancel","system_cancel","user_cancel","user_fallback"]);
const UNLOCK_FAILED="Biometric unlock isn't available right now. Sign in with your password.";
function byId(root:Document|undefined,id:string|null):Element|null {
  if(!root||!id)return null;
  return Array.from(root.getElementsByTagName("*")).find(value=>value.getAttribute("id")===id)??null;
}

/** Build existing app behaviors for one confirmed root, never a singleton event bus. */
export function createOwnedBehaviors(ports:OwnedBehaviorPorts):HvBehavior[]{
  const {supervisor,native}=ports,captured=supervisor.snapshot();
  const settingsReceipts=new WeakMap<Element,object>();
  const sameRoot=()=>{if(ports.recovery)return ports.recovery.isAlive();const now=supervisor.snapshot();return !!captured.identity&&now.identity===captured.identity&&now.generation===captured.generation;};
  const leaseFor=(alive:()=>boolean)=>ports.recovery?ports.recovery.lease(alive):supervisor.lease(alive);
  const callback=(action:string,run:(element:Element,source:SourceAuthority,getRoot:HvGetRoot,updateRoot:HvUpdateRoot,lease:ReturnType<typeof supervisor.lease>,current:(()=>Promise<boolean>) & {now():boolean})=>Promise<void>,failure?:string):HvBehavior=>({action,callback:async(element,_onUpdate,getRoot,updateRoot)=>{
    let source:SourceAuthority|null=null;
    let lease:ReturnType<typeof supervisor.lease>|null=null;
    const allowed=()=>sameRoot()&&!!source&&source.sourceIsCurrent()&&!!lease&&lease.isCurrent();
    try {
      if(!sameRoot()||!leaseFor(()=>true).isCurrent())return;
      source=ports.bindSource(element,{getRoot,updateRoot});if(!source)return;
      const capturedSource=source;lease=leaseFor(()=>sameRoot()&&capturedSource.sourceIsCurrent());
      if(!allowed())return;
      const current=Object.assign(async()=>{
        // OS prompt inactivity is a pause, not logout. Retain only this exact
        // root/source; foreground becomes available after actual confirmation.
        while(sameRoot()&&capturedSource.isAlive()&&supervisor.snapshot().availability==="paused"){
          await new Promise<void>(resolve=>{const off=supervisor.subscribe(()=>{off();resolve();});});
        }
        return allowed();
      },{now:allowed});
      await run(element,source,getRoot,updateRoot,lease,current);
    } catch {
      if(failure&&allowed())ports.notice({message:failure,tone:"error"});
    }
  }});
  const behaviors=[
    callback("biometric-unlock",async(element,source,_getRoot,_updateRoot,lease,current)=>{
      const submit=source.bindBiometricSubmit();if(!submit)return;
      const result=await native.unlock(element.getAttribute("prompt")??"Sign in to HyperTodo");if((!await current()||!current.now()))return;
      if(!result.success){if(!DISMISSED.has(result.error??""))ports.notice({message:UNLOCK_FAILED,tone:"error"});return;}
      const token=await native.readToken();if((!await current()||!current.now()))return;
      if(!token){
        const result=await lease.clearCredential(Object.freeze({}));
        if(await current()&&current.now()&&["failed","capacity"].includes(result))ports.notice({message:UNLOCK_FAILED,tone:"error"});
        return;
      }
      // The captured gate capability owns field update/form serialization/POST.
      // This boolean is admission, never authentication success or layout ACK.
      submit(token);
    },UNLOCK_FAILED),
    callback("probe-biometrics",async(element,_source,getRoot,updateRoot,_lease,current)=>{
      const available=element.getAttribute("available-target"),target=element.getAttribute("token-target");
      const hardware=await native.hasHardware();if((!await current()||!current.now())||!hardware)return;
      const enrolled=await native.isEnrolled();if((!await current()||!current.now())||!enrolled)return;
      const token=await native.readToken();if((!await current()||!current.now()))return;
      let types:number[]=[];
      if(token){try{types=await native.supportedTypes();}catch{types=[];}if((!await current()||!current.now()))return;}
      const root=getRoot();let mutated=byId(root,available);mutated?.setAttribute("hide","false");
      if(token){
        const button=byId(root,target);button?.setAttribute("hide","false");mutated=button??mutated;
        const wanted=types.length===1&&types[0]===2?"face":types.length?"fingerprint":native.platform==="ios"?"face":"fingerprint";
        for(const icon of Array.from(button?.getElementsByTagNameNS(Namespaces.HYPERVIEW,"image")??[])){
          const shown=icon.getAttribute("variant")===wanted;icon.setAttribute("hide",shown?"false":"true");if(shown)mutated=icon;
        }
      }
      if(mutated)updateRoot(shallowCloneToRoot(mutated));
    }),
    callback("pick-avatar",async(element,source,getRoot,updateRoot,_lease,current)=>{
      const target=element.getAttribute("target"),previewId=element.getAttribute("preview-target"),currentId=element.getAttribute("current-target");
      const picked=await native.pick();if((!await current()||!current.now())||picked.canceled||!picked.uri)return;
      const rendered=await native.render(picked.uri);if((!await current()||!current.now()))return;
      const {base64}=await native.save(rendered);if((!await current()||!current.now())||!base64)return;
      const root=getRoot(),field=byId(root,target);if(!field)return;
      if(field.getAttribute('value')!==base64)source.markDraftEdit?.(field);
      field.setAttribute("value",base64);const preview=byId(root,previewId);preview?.setAttribute("source",`data:image/jpeg;base64,${base64}`);preview?.setAttribute("hide","false");byId(root,currentId)?.setAttribute("hide","true");
      updateRoot(shallowCloneToRoot(field));
      if(await current()&&current.now())ports.notice({message:"Photo ready. Tap Save settings to keep it.",tone:"success"});
    },"Couldn't open your photos. Try again in a moment."),
    callback("store-biometric-token",async(element,source,_getRoot,_updateRoot,lease,current)=>{
      const receipt=source.effectReceipt();
      if(receipt){await (ports.recovery??supervisor).consumeEffect(receipt);await current();return;}
      // Only the app's explicitly bound settings-clear node can create a new
      // empty-token effect. Missing panel receipt is never permission to clear.
      if(ports.recovery||element.getAttribute("token")!==""||!ports.isSettingsClear(element,source))return;
      let ownedReceipt=settingsReceipts.get(element);
      if(!ownedReceipt){ownedReceipt=Object.freeze({});settingsReceipts.set(element,ownedReceipt);}
      const result=await lease.clearCredential(ownedReceipt);
      if(await current()&&current.now()&&["failed","capacity"].includes(result))ports.notice({message:"Couldn't update device sign-in. Try again in a moment.",tone:"error"});
    }),
    callback("notify-resources",async(element,source)=>{
      const value=element.getAttribute("resources")??"";
      if(!["tasks","categories","ui","tasks categories","tasks ui","categories ui","tasks categories ui"].includes(value))return;
      ports.notifyResources(source,Object.freeze(value.split(" ")) as readonly ResourceName[]);
    }),
    callback("show-snackbar",async(element)=>{
      const message=(element.getAttribute("message")??"").trim();if(message)ports.notice({message,tone:element.getAttribute("tone")==="success"?"success":"error"});
    }),
  ];
  return ports.recovery?behaviors.filter(value=>["biometric-unlock","probe-biometrics","store-biometric-token"].includes(value.action)):behaviors;
}
