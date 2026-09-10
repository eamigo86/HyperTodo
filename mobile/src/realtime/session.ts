import {createSessionEffects,type EffectResult,type StorageQueue} from "./session-effects";
import {classifyAuth,parseAuthBody,parseObservation,validBinding,utf8Bytes,SESSION_HEADERS as H,type AuthBody,type AuthKind,type Observation} from "./session-protocol";

export type SessionClock={schedule(callback:()=>void,ms:number):()=>void;sleep(ms:number):Promise<void>};
export type Identity=Readonly<Observation & {generation:number}>;
type Availability="foreground"|"paused"|"auth-pending"|"uncertain";
type Reason="bootstrap-required"|"network-uncertain"|"identity-mismatch"|"invalid-response"|"storage-failed"|"revoked"|null;
export type AuthResult={kind:"transition";identity:Identity;storage:EffectResult|null}|{kind:"panel"|"refused";status:number;body:string;receipt:object}|{kind:"held"|"busy"|"uncertain"|"stale"};
export type SessionPorts={origin:string;transport(url:string,init:RequestInit):Promise<Response>;storage:StorageQueue;clock?:SessionClock;stopStream():void;onIdentity(identity:Identity|null):void;onTheme(theme:string|null):void;onLanguage?(language:string|null):void};
export type RecoveryHandle=Readonly<{
  isAlive():boolean;isCurrent():boolean;
  fetch(input:string,init?:RequestInit):Promise<Response>;
  authenticate(input:string,init?:RequestInit):Promise<AuthResult>;
  lease(alive:()=>boolean):Readonly<{isCurrent():boolean;clearCredential(receipt:object):Promise<EffectResult>}>;
  consumeEffect(receipt:object):Promise<EffectResult>;revoke():void;
}>;
export type RecoveryResult={kind:"recovery";handle:RecoveryHandle}|{kind:"busy"|"uncertain"|"stale"};
type RecoveryState={generation:number;binding:string;confirmed:boolean};
type Accepted={body:AuthBody;binding:string;status:number;receipt:object;needsPreconfirm:boolean;effect?:Promise<EffectResult>};
type AuthOperation={recovery?:boolean;generation:number;expected:string;kind:AuthKind;expired:boolean;sent:boolean;resumeConfirmed:boolean;accepted?:Accepted;processing?:Promise<AuthResult>};
const defaultClock:SessionClock={schedule:(fn,ms)=>{const timer=setTimeout(fn,ms);return()=>clearTimeout(timer);},sleep:ms=>new Promise(resolve=>setTimeout(resolve,ms))};

/** App-owned session authority. Transport/storage ports are not SDK or native proof. */
export function createSessionSupervisor(ports:SessionPorts) {
  const origin=new URL(ports.origin).origin;
  if(!/^https?:/.test(origin))throw new Error("unsupported-origin");
  const clock=ports.clock??defaultClock;
  let generation=0,identity:Identity|null=null,observedBinding:string|null=null;
  let availability:Availability="uncertain",reason:Reason="bootstrap-required",active=true,everConfirmed=false,rootReady=false,startupRevoked=false;
  let auth:AuthOperation|undefined;
  let recovery:RecoveryState|undefined,recoveryStarting=false;
  // Privacy revocation cannot settle an already submitted mutation/native job.
  let authExecuting=false;
  let confirming:Promise<AuthResult>|undefined;
  const inFlight=new Set<Promise<Response>>();
  const listeners=new Set<()=>void>();
  const receipts=new WeakMap<object,{generation:number;result:Promise<EffectResult>}>();
  const nativeEffects=new Set<Promise<EffectResult>>();
  const snapshot=()=>Object.freeze({identity,observedBinding,availability,reason,generation,rootReady});
  const notify=()=>{for(const listener of listeners)listener();};
  const stop=()=>{try{ports.stopStream();}catch{/* Stream failure cannot grant admission. */}};
  function protect(why:Reason){reason=why;availability=active?"uncertain":"paused";stop();notify();}
  function current(op:AuthOperation){return auth===op&&op.generation===generation;}
  function invalidate(){
    startupRevoked=true;recovery=undefined;generation+=1;identity=null;rootReady=false;auth=undefined;protect("revoked");
    try{ports.onIdentity(null);}catch{/* Keep the shield if the UI adapter fails. */}
  }
  function address(input:string){
    const url=new URL(input,origin);
    if(url.origin!==origin||url.username||url.password||url.hash||!url.pathname.startsWith("/hv/"))throw new Error("unsupported-request");
    return url.toString();
  }
  function options(init:RequestInit,expected?:string):RequestInit {
    // The App snapshots the public Parser's FormData before this supervisor.
    // Only immutable strings enter its queue; files require a separate contract.
    if(init.body!==undefined&&init.body!==null&&typeof init.body!=="string")throw new Error("unsupported-request-body");
    const headers=new Headers(init.headers);headers.set(H.contract,"realtime-v1");
    if(expected)headers.set(H.expected,expected);else headers.delete(H.expected);
    if(!headers.has("Origin"))headers.set("Origin",origin);
    if(!headers.has("Accept"))headers.set("Accept","application/vnd.hyperview+xml");
    headers.set("Cache-Control","no-store");
    return {...init,headers,method:(init.method??"GET").toUpperCase(),credentials:"include",redirect:"error",cache:"no-store"};
  }
  function validResponse(response:Response){
    if(response.redirected||!response.url||new URL(response.url).origin!==origin)throw new Error("invalid-response-origin");
  }
  function waitChange(){return new Promise<void>(resolve=>{const listener=()=>{listeners.delete(listener);resolve();};listeners.add(listener);});}
  async function waitPaused(owned:()=>boolean){while(owned()&&availability==="paused")await waitChange();}
  async function waitForeground(op:AuthOperation){while(current(op)&&!active)await waitChange();if(!current(op))throw new Error("stale-owner");}
  async function observe(neutral=false):Promise<Observation> {
    const controller=new AbortController();let expired=false;
    let timeoutReject!:(reason:Error)=>void;
    const timeout=new Promise<never>((_resolve,reject)=>{timeoutReject=reject;});
    const cancel=clock.schedule(()=>{expired=true;controller.abort();timeoutReject(new Error("confirmation-timeout"));},2000);
    const load=async()=>{
      const response=await ports.transport(origin+"/hv/session-state/",options({method:"GET",signal:controller.signal,headers:{Accept:"application/json",...(neutral?{"X-HyperTodo-Recovery":"login-v1"}:{})}}));
      if(expired)throw new Error("confirmation-timeout");validResponse(response);
      if(response.status!==200)throw new Error("invalid-observation-status");
      const body=await response.text();if(expired)throw new Error("confirmation-timeout");return parseObservation(body,response.headers);
    };
    try{return await Promise.race([load(),timeout]);}finally{cancel();}
  }
  async function confirmation(ownerGeneration:number,neutral=false):Promise<Observation|null> {
    for(let attempt=0;attempt<3;attempt++){
      if(ownerGeneration!==generation)return null;
      if(attempt)await clock.sleep(attempt*1000);
      if(ownerGeneration!==generation)return null;
      try {const result=await observe(neutral);if(ownerGeneration!==generation)return null;observedBinding=result.binding;return result;}
      catch {if(ownerGeneration!==generation)return null;}
    }
    return null;
  }
  function publish(observation:Observation){
    recovery=undefined;
    generation+=1;identity=Object.freeze({...observation,generation});everConfirmed=true;rootReady=false;observedBinding=observation.binding;
    availability=active?"foreground":"paused";reason=null;
    try{ports.onIdentity(identity);}catch{protect("invalid-response");}
    notify();return identity;
  }
  async function reconcile(resume:boolean):Promise<AuthResult>{
    const captured=generation,expected=identity?.binding;
    const result=await confirmation(captured);
    if(captured!==generation)return{kind:"stale"};
    if(!result){protect("network-uncertain");return{kind:"uncertain"};}
    if(!expected||result.binding!==expected){invalidate();reason="identity-mismatch";notify();return{kind:"uncertain"};}
    if(resume&&active&&!auth){availability="foreground";reason=null;notify();}
    return{kind:resume&&active&&!auth?"held":"uncertain"};
  }
  async function failAuth(op:AuthOperation,why:Reason):Promise<AuthResult>{
    if(!current(op))return{kind:"stale"};protect(why);
    // A deadline does not settle a POST. This is reached only after its real
    // transport/body chain settled; confirmation never replays the mutation.
    await reconcile(false);
    if(auth===op)auth=undefined;
    return{kind:"uncertain"};
  }
  async function expected(op:AuthOperation,binding:string):Promise<Observation|null>{
    const result=await confirmation(op.generation,op.recovery);
    if(!current(op))return null;
    if(!result){protect("network-uncertain");return null;}
    if(result.binding!==binding){invalidate();reason="identity-mismatch";notify();return null;}
    if(op.recovery&&recovery?.generation===op.generation&&active)recovery.confirmed=true;
    return result;
  }
  async function completeAuth(op:AuthOperation):Promise<AuthResult>{
    if(op.processing)return op.processing;
    const process=async():Promise<AuthResult>=>{
      if(!current(op))return{kind:"stale"};
      const accepted=op.accepted!;
      if(!active)return{kind:"held"};
      let effectResult:EffectResult|null=null;
      if(accepted.body.effect){
        if(!accepted.effect){
          // Capture this exact owner in the queued job, not whichever auth is
          // current when the native queue later starts executing it.
          const queue:StorageQueue={enqueue:job=>ports.storage.enqueue(async store=>{
            while(current(op)){
              await waitForeground(op);
              if(accepted.needsPreconfirm){
                if(!await expected(op,accepted.binding))throw new Error("unconfirmed-owner");
                if(!active)continue;
                accepted.needsPreconfirm=false;
              }
              if(active&&current(op)){await job(store);return;}
            }
            throw new Error("stale-owner");
          })};
          accepted.effect=createSessionEffects(queue).apply(accepted.receipt,()=>current(op),accepted.body.effect);
          receipts.set(accepted.receipt,{generation:op.generation,result:accepted.effect});
        }
        effectResult=await accepted.effect;
        if(!current(op))return{kind:"uncertain"};
        if(!["stored","cleared","cleared-after-failure"].includes(effectResult)){protect("storage-failed");auth=undefined;return{kind:"uncertain"};}
      } else if(accepted.needsPreconfirm){
        if(!await expected(op,accepted.binding))return{kind:"uncertain"};accepted.needsPreconfirm=false;
      }
      if(!active)return{kind:"held"};
      // A pause can happen after native work started. Returning a non-success
      // panel also needs fresh ownership, without repeating its clear effect.
      if(accepted.needsPreconfirm){
        if(!await expected(op,accepted.binding))return{kind:"uncertain"};
        if(!active)return{kind:"held"};
        accepted.needsPreconfirm=false;
      }
      if(accepted.body.kind==="success"){
        const confirmed=await expected(op,accepted.binding);
        if(!confirmed)return{kind:"uncertain"};
        if(confirmed.authenticated!==(op.kind!=="logout")){invalidate();reason="invalid-response";notify();return{kind:"uncertain"};}
        if(!active)return{kind:"held"};
        auth=undefined;const next=publish(confirmed);
        return{kind:"transition",identity:next,storage:effectResult};
      }
      auth=undefined;availability="foreground";reason=null;notify();
      return{kind:accepted.body.kind,status:accepted.status,body:accepted.body.body,receipt:accepted.receipt};
    };
    op.processing=process();
    try{return await op.processing;}finally{op.processing=undefined;}
  }
  async function bootstrap():Promise<"ready"|"uncertain"|"stale">{
    if(everConfirmed||startupRevoked){await reconcile(true);return availability==="foreground"?"ready":"uncertain";}
    const captured=generation;const result=await confirmation(captured);
    if(captured!==generation)return"stale";
    if(!result||!active){protect("network-uncertain");return"uncertain";}
    publish(result);return"ready";
  }
  async function request(input:string,init:RequestInit={}):Promise<Response>{
    const url=address(input),method=(init.method??"GET").toUpperCase();
    if(classifyAuth(url,method,origin))throw new Error("explicit-auth-required");
    if(!identity||availability!=="foreground"||!active||auth)throw new Error("session-unavailable");
    const owner=identity,captured=generation,prepared=options(init,owner.binding);
    const raw=Promise.resolve().then(()=>ports.transport(url,prepared));inFlight.add(raw);
    let response:Response;
    try{response=await raw;}finally{inFlight.delete(raw);}
    const owned=()=>captured===generation&&identity===owner;
    if(!owned())throw new Error("stale-owner");
    try{validResponse(response);if(response.headers.get(H.binding)!==owner.binding||response.status===401)throw new Error("identity-mismatch");}
    catch {protect("identity-mismatch");await reconcile(false);throw new Error("untrusted-response");}
    await waitPaused(owned);
    if(!owned()||availability!=="foreground"||auth)throw new Error("session-unavailable");
    ports.onTheme(response.headers.get("X-HyperTodo-Theme"));
    if(owned()&&availability==="foreground"&&!auth)ports.onLanguage?.(response.headers.get("Content-Language"));
    return new Proxy(response,{get(target,property){
      if(property==="text")return async()=>{
        await waitPaused(owned);
        if(!owned()||availability!=="foreground")throw new Error("stale-owner");
        const body=await target.text();await waitPaused(owned);
        if(!owned()||availability!=="foreground")throw new Error("stale-owner");return body;
      };
      const value=Reflect.get(target,property,target);return typeof value==="function"?value.bind(target):value;
    }});
  }
  async function runAuthenticate(input:string,init:RequestInit,neutral?:RecoveryState):Promise<AuthResult>{
    if(neutral?recovery!==neutral||neutral.generation!==generation||!neutral.confirmed:!identity)return{kind:"stale"};
    if(auth)return{kind:"busy"};
    const url=address(input),kind=classifyAuth(url,init.method??"GET",origin);
    const binding=neutral?.binding??identity?.binding;
    if(!kind||!binding||!validBinding(binding)||!active)throw new Error("auth-unavailable");
    const prepared=options(init,binding);
    if(neutral)(prepared.headers as Headers).set("X-HyperTodo-Recovery","login-v1");
    const op:AuthOperation={recovery:!!neutral,generation,expected:binding,kind,expired:false,sent:false,resumeConfirmed:true};auth=op;availability="auth-pending";reason=null;stop();notify();
    await Promise.allSettled([...inFlight,...nativeEffects]);
    while(current(op)&&(!active||!op.resumeConfirmed))await waitChange();
    if(!current(op))return{kind:"stale"};
    op.sent=true;
    const controller=new AbortController();
    const abort=()=>{op.expired=true;controller.abort();if(current(op))protect("network-uncertain");};
    const source=prepared.signal;source?.addEventListener("abort",abort,{once:true});if(source?.aborted)abort();
    const cancel=clock.schedule(abort,30000);
    try {
      if(op.expired)throw new Error("auth-cancelled");
      const response=await ports.transport(url,{...prepared,signal:controller.signal});
      if(!current(op))return{kind:"stale"};if(op.expired)throw new Error("auth-timeout");
      validResponse(response);const binding=response.headers.get(H.binding);
      if(!validBinding(binding))throw new Error("invalid-response");
      const outcome=response.headers.get(H.outcome);
      // Capture the response's successful B before any body or confirmation.
      const successful=response.status===200&&outcome===(kind==="password"?"password-ok":kind==="biometric"?"biometric-ok":"logout-ok");
      if(!successful&&binding!==op.expected)throw new Error("identity-mismatch");
      const body=await response.text();if(!current(op))return{kind:"stale"};if(op.expired)throw new Error("auth-timeout");
      op.accepted={body:parseAuthBody(kind,response.status,outcome,body),binding,status:response.status,receipt:Object.freeze({}),needsPreconfirm:!active};
    } catch {return await failAuth(op,"network-uncertain");}
    finally{cancel();source?.removeEventListener("abort",abort);}
    return completeAuth(op);
  }
  async function authenticate(input:string,init:RequestInit,neutral?:RecoveryState):Promise<AuthResult>{
    if(authExecuting||auth)return{kind:"busy"};
    authExecuting=true;
    try{return await runAuthenticate(input,init,neutral);}finally{authExecuting=false;notify();}
  }
  function pause(){active=false;if(recovery)recovery.confirmed=false;availability="paused";if(auth&&!auth.sent)auth.resumeConfirmed=false;if(auth?.accepted)auth.accepted.needsPreconfirm=true;stop();notify();}
  async function foreground():Promise<AuthResult>{
    active=true;notify();
    if(confirming)return confirming;
    const resume=async():Promise<AuthResult>=>{
      if(!everConfirmed&&!startupRevoked){const state=await bootstrap();return{kind:state==="ready"?"held":state};}
      if(auth?.accepted)return completeAuth(auth);
      if(auth){
        const op=auth;
        if(!op.sent){
          if(!await expected(op,op.expected))return{kind:"uncertain"};
          if(!active)return{kind:"held"};
          op.resumeConfirmed=true;availability="auth-pending";notify();
        }
        return{kind:"busy"};
      }
      if(recovery){
        const captured=recovery,result=await confirmation(generation,true);
        if(recovery!==captured||captured.generation!==generation)return{kind:"stale"};
        if(!result||result.binding!==captured.binding){invalidate();reason=result?"identity-mismatch":"network-uncertain";notify();return{kind:"uncertain"};}
        if(!active)return{kind:"held"};
        captured.confirmed=true;availability="foreground";reason=null;notify();return{kind:"held"};
      }
      return reconcile(true);
    };
    confirming=resume();try{return await confirming;}finally{confirming=undefined;}
  }

  /** Explicit neutral presentation authority; observing a cookie never publishes Identity. */
  async function beginRecovery(): Promise<RecoveryResult> {
    if (recoveryStarting || authExecuting || auth || inFlight.size || nativeEffects.size || !active) return {
      kind: "busy"
    };
    recoveryStarting = true;
    try {
      invalidate();
      const captured = generation,
        result = await confirmation(captured, true);
      if (captured !== generation) return {
        kind: "stale"
      };
      if (!result || !active) {
        protect("network-uncertain");
        return {
          kind: "uncertain"
        };
      }
      const owner: RecoveryState = {
        generation: captured,
        binding: result.binding,
        confirmed: true
      };
      recovery = owner;
      availability = "foreground";
      reason = null;
      const alive = () => recovery === owner && generation === captured && !identity;
      const current = () => alive() && owner.confirmed && active && availability === "foreground" && !auth;
      const revoke = () => {
        if (alive()) invalidate();
      };
      const handle: RecoveryHandle = Object.freeze({
        isAlive: alive,
        isCurrent: current,
        revoke,
        fetch: async (input: string, init: RequestInit = {}) => {
          const url = new URL(input, origin);
          if (!current() || url.origin !== origin || url.username || url.password || url.hash || url.pathname !== "/hv/recovery/" || !["", "?screen=login"].includes(url.search) || (init.method ?? "GET").toUpperCase() !== "GET" || init.body != null) throw new Error("recovery-unavailable");
          const headers = new Headers(init.headers);
          headers.set("X-HyperTodo-Recovery", "login-v1");
          const raw = Promise.resolve().then(() => ports.transport(url.toString(), options({
            ...init,
            method: "GET",
            headers
          }, owner.binding)));
          inFlight.add(raw);
          let response: Response;
          try {
            response = await raw;
          } finally {
            inFlight.delete(raw);
          }
          if (!alive()) throw new Error("stale-owner");
          try {
            validResponse(response);
            if (response.status !== 200 || response.headers.get(H.binding) !== owner.binding) throw new Error("invalid-recovery-response");
          } catch {
            revoke();
            throw new Error("untrusted-response");
          }
          await waitPaused(alive);
          if (!current()) throw new Error("recovery-unavailable");
          return new Proxy(response, {
            get(target, property) {
              if (property === "text") return async () => {
                await waitPaused(alive);
                if (!current()) throw new Error("stale-owner");
                const body = await target.text();
                await waitPaused(alive);
                if (!current()) throw new Error("stale-owner");
                if (utf8Bytes(body) > 262144) {
                  revoke();
                  throw new Error("recovery-body-too-large");
                }
                return body;
              };
              const value = Reflect.get(target, property, target);
              return typeof value === "function" ? value.bind(target) : value;
            }
          });
        },
        authenticate: async (input: string, init: RequestInit = {}): Promise<AuthResult> => {
          let kind: AuthKind | null = null;
          try {
            const url = new URL(input, origin);
            if (!url.search && !url.hash) kind = classifyAuth(url.toString(), init.method ?? "GET", origin);
          } catch {/* Closed below. */}
          if (!current() || !["password", "biometric"].includes(kind ?? "")) return {
            kind: "stale"
          };
          return authenticate(input, init, owner);
        },
        lease: (aliveSource: () => boolean) => Object.freeze({
          isCurrent: () => {
            try {
              return current() && aliveSource() === true;
            } catch {
              return false;
            }
          },
          clearCredential: async () => "stale" as const
        }),
        consumeEffect: (receipt: object): Promise<EffectResult> => {
          const value = receipts.get(receipt);
          return alive() && value?.generation === captured ? value.result : Promise.resolve("retired");
        }
      });
      notify();
      return {
        kind: "recovery",
        handle
      };
    } finally {
      recoveryStarting = false;
      notify();
    }
  }
  return {
    beginRecovery,snapshot,bootstrap,request,authenticate,pause,foreground,invalidate,
    retryConfirmation:foreground,
    // Explicit user intent may discard a settled held result, never cancel an
    // in-flight POST/native write or claim those effects were rolled back.
    abandonTransition:()=>{if(!auth||auth.processing||(auth.sent&&!auth.accepted))return false;auth=undefined;protect("network-uncertain");return true;},
    subscribe:(listener:()=>void)=>{listeners.add(listener);return()=>{listeners.delete(listener);};},
    markRootReady:(ownedGeneration:number)=>{if(ownedGeneration!==generation||availability!=="foreground"||!identity)return false;rootReady=true;notify();return true;},
    lease:(alive:()=>boolean)=>{
      const owner=identity,captured=generation;
      const owned=()=>{try{return !!owner&&identity===owner&&captured===generation&&alive()===true;}catch{return false;}};
      const isCurrent=()=>owned()&&active&&availability==="foreground"&&!auth;
      // An admitted clear may release an auth barrier for this same confirmed
      // owner, but uncertain reconciliation never authorizes a new write.
      const effectCurrent=()=>owned()&&active&&(availability==="foreground"||(
        availability==="auth-pending"&&auth?.generation===captured&&
        auth.expected===owner?.binding&&auth.resumeConfirmed
      ));
      const effects=createSessionEffects({enqueue:job=>ports.storage.enqueue(async store=>{
        await waitPaused(owned);
        // An admitted settings effect may finish while auth waits behind it.
        // It never starts under a different identity or a removed source.
        // The effect itself rechecks ownership before any native write.
        await job(store);
      })});
      return Object.freeze({isCurrent,clearCredential:(receipt:object):Promise<EffectResult>=>{
        if(!isCurrent())return Promise.resolve("stale");
        const existing=receipts.get(receipt);
        if(existing)return existing.generation===captured?existing.result:Promise.resolve("retired");
        if(nativeEffects.size>=64)return Promise.resolve("capacity");
        const result=effects.apply(receipt,effectCurrent,{kind:"clear"});
        receipts.set(receipt,{generation:captured,result});nativeEffects.add(result);
        void result.finally(()=>{nativeEffects.delete(result);});return result;
      }});
    },
    consumeEffect:(receipt:object):Promise<EffectResult>=>{const record=receipts.get(receipt);return record?.generation===generation?record.result:Promise.resolve("retired");},
  };
}
