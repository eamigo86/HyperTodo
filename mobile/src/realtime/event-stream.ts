import { createStreamDecoder } from './stream-protocol';
import { SESSION_HEADERS as H, validBinding } from './session-protocol';
import type { ResourceName } from './resources';

export type StreamClock = {now():number; schedule(callback:()=>void,ms:number):()=>void; random():number};
export type StreamOwner = Readonly<{
  generation:number;
  binding:string;
  /** Must check authenticated identity, generation, foreground and actual Root readiness. */
  isCurrent():boolean;
  receive(resources:readonly ResourceName[],cause:'invalidate'|'resync'):boolean;
  onAuthRequired():void;
}>;
type Ports = {origin:string; fetch(url:string,init:RequestInit):Promise<Response>; clock?:StreamClock};
type Connection = {
  owner:StreamOwner; controller:AbortController; reader?:ReadableStreamDefaultReader<Uint8Array>;
  cancelWatch?:()=>void; cancelLease?:()=>void; activity:number;
};
const defaultClock:StreamClock = {
  now:()=>performance.now(), random:()=>Math.random(),
  schedule:(run,ms)=>{const timer=setTimeout(run,ms);return()=>clearTimeout(timer);},
};
const ALL_RESOURCES = Object.freeze(['tasks','categories','ui'] as const);

/** One generation-owned SSE connection. No App/SDK state or XML ACK authority. */
export function createEventStream(ports:Ports) {
  const origin=new URL(ports.origin);
  if (!['http:','https:'].includes(origin.protocol) || origin.username || origin.password || origin.pathname!=='/' || origin.search || origin.hash) throw new Error('unsupported-stream-origin');
  const endpoint=new URL('/realtime/events/',origin.origin).toString();
  const clock=ports.clock??defaultClock;
  let source:StreamOwner|null=null, owner:StreamOwner|null=null, connection:Connection|undefined;
  let cancelRetry:(()=>void)|undefined, failures=0, disposed=false;
  function eligible(value:StreamOwner|null):value is StreamOwner {
    try { return !disposed && !!value && owner===value && value.isCurrent()===true; }
    catch { return false; }
  }
  const owns=(value:Connection)=>connection===value && eligible(value.owner);
  function cancelBody(response:Response) {
    try { void response.body?.cancel().catch(()=>{}); } catch { /* No payload reads on refusal. */ }
  }
  function close(value:Connection) {
    if(connection===value)connection=undefined;
    value.cancelWatch?.(); value.cancelLease?.(); value.controller.abort();
    const reader=value.reader;
    if(reader) {
      value.reader=undefined;
      try { void reader.cancel().catch(()=>{}).finally(()=>{try{reader.releaseLock();}catch{/* Already released. */}}); }
      catch { try{reader.releaseLock();}catch{/* Reader already closed. */} }
    }
  }
  function retry(value:Connection) {
    const allowed=owns(value), captured=value.owner;
    close(value);
    if(!allowed)return;
    // Equal-centred jitter, clamped to the agreed1–30s bounds. Only a valid
    // resync resets failures; headers/heartbeats cannot produce a retry storm.
    const base=Math.min(30000,1000*2**Math.min(failures++,5));
    const sample=clock.random();
    const jitter=Number.isFinite(sample)?Math.min(1,Math.max(0,sample)):0.5;
    const delay=Math.max(1000,Math.min(30000,Math.round(base*(0.75+0.5*jitter))));
    cancelRetry=clock.schedule(()=>{cancelRetry=undefined;if(eligible(captured))open(captured);},delay);
  }
  function activity(value:Connection) {
    value.cancelWatch?.(); value.activity=clock.now();
    const watch=()=>{
      if(!owns(value)){close(value);return;}
      const remaining=45000-(clock.now()-value.activity);
      if(remaining>0)value.cancelWatch=clock.schedule(watch,remaining);
      else retry(value);
    };
    value.cancelWatch=clock.schedule(watch,45000);
  }
  function authRequired(value:Connection) {
    const allowed=owns(value), captured=value.owner;
    close(value);
    if(allowed)try{captured.onAuthRequired();}catch{/* Notification cannot grant new authority. */}
  }
  async function load(value:Connection) {
    try {
      const response=await ports.fetch(endpoint,{
        method:'GET',credentials:'include',redirect:'error',cache:'no-store',signal:value.controller.signal,
        headers:{Accept:'text/event-stream',Origin:origin.origin,'Cache-Control':'no-store',[H.contract]:'realtime-v1',[H.expected]:value.owner.binding},
      });
      if(!owns(value)){cancelBody(response);close(value);return;}
      if(response.redirected || !response.url || new URL(response.url).toString()!==endpoint) {
        cancelBody(response);retry(value);return;
      }
      if(response.status===401 || response.status===403) {
        cancelBody(response);authRequired(value);return;
      }
      if(response.status===404) { cancelBody(response);close(value);return; }
      if(response.status!==200 || response.headers.get(H.binding)!==value.owner.binding || response.headers.get('Content-Type')?.split(';')[0].trim().toLowerCase()!=='text/event-stream' || !response.body) {
        cancelBody(response);retry(value);return;
      }
      activity(value);
      value.reader=response.body.getReader();
      const decoder=createStreamDecoder(event=>{
        if(!owns(value))return;
        if(event.type==='auth-required'){authRequired(value);return;}
        if(event.type==='resync') {
          failures=0;
          value.owner.receive(ALL_RESOURCES,'resync');
        } else value.owner.receive(event.resources,'invalidate');
      });
      while(owns(value)) {
        const result=await value.reader.read();
        if(!owns(value)){close(value);return;}
        if(result.done){decoder.end();retry(value);return;}
        if(result.value.byteLength)activity(value);
        decoder.push(result.value);
      }
      close(value);
    } catch { if(connection===value)retry(value); }
  }
  function open(captured:StreamOwner) {
    if(!eligible(captured) || connection)return;
    const value:Connection={owner:captured,controller:new AbortController(),activity:clock.now()};
    connection=value;
    activity(value);
    value.cancelLease=clock.schedule(()=>{if(connection===value)retry(value);},60000);
    void load(value);
  }
  function stop() {
    cancelRetry?.(); cancelRetry=undefined;
    if(connection)close(connection);
  }
  return {
    setOwner(next:StreamOwner|null):void {
      if(disposed || next===source)return;
      if(next && (!Number.isSafeInteger(next.generation) || next.generation<0 || !validBinding(next.binding) || ![next.isCurrent,next.receive,next.onAuthRequired].every(fn=>typeof fn==='function'))) throw new Error('invalid-stream-owner');
      stop(); source=next; failures=0;
      owner=next?Object.freeze({...next}):null;
      if(eligible(owner))open(owner);
    },
    dispose():void { if(disposed)return;disposed=true;stop();source=null;owner=null; },
  };
}
