import type {CredentialEffect} from "./session-protocol";

export type CredentialStore = {save(token:string):Promise<void>;clear():Promise<void>};
/** Adapter must share the existing native queue; never recursively enqueue. */
export type StorageQueue = {enqueue(job:(store:CredentialStore)=>Promise<void>):Promise<void>};
export type EffectResult = "stored"|"cleared"|"cleared-after-failure"|"stale"|"failed"|"capacity"|"retired";

/** Bounded, exactly-once accepted effects; receipts contain no credential data. */
export function createSessionEffects(queue:StorageQueue) {
  const live=new Map<object,Promise<EffectResult>>();
  const seen=new WeakSet<object>();
  return {apply(receipt:object,isCurrent:()=>boolean,input:CredentialEffect):Promise<EffectResult> {
    const existing=live.get(receipt);if(existing)return existing;
    if(seen.has(receipt))return Promise.resolve("retired");
    if(live.size>=64)return Promise.resolve("capacity");
    const effect=Object.freeze({...input});
    const current=()=>{try{return isCurrent()===true;}catch{return false;}};
    let complete!:(result:EffectResult)=>void;
    const promise=new Promise<EffectResult>(resolve=>{complete=resolve;});
    live.set(receipt,promise);seen.add(receipt);
    let result:EffectResult="failed";
    const job=async(store:CredentialStore)=>{
      if(!current()){result="stale";return;}
      try {
        if(effect.kind==="clear")await store.clear();else await store.save(effect.token);
        result=current()?(effect.kind==="clear"?"cleared":"stored"):"stale";
      } catch {
        if(!current()){result="stale";return;}
        if(effect.kind==="clear"){result="failed";return;}
        try {await store.clear();result=current()?"cleared-after-failure":"stale";}
        catch {result=current()?"failed":"stale";}
      }
    };
    try {
      void Promise.resolve(queue.enqueue(job)).catch(()=>{result=current()?"failed":"stale";}).finally(()=>{live.delete(receipt);complete(result);});
    } catch {live.delete(receipt);complete(current()?"failed":"stale");}
    return promise;
  }};
}
