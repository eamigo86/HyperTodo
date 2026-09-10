import { createEventStream, type StreamClock, type StreamOwner } from '../src/realtime/event-stream';
import { SESSION_HEADERS as H } from '../src/realtime/session-protocol';

const ORIGIN='https://app.test', URL=ORIGIN+'/realtime/events/', A='hvs1.'+'A'.repeat(43), B='hvs1.'+'B'.repeat(43);
const tick=async()=>{for(let i=0;i<20;i++)await Promise.resolve();};
const wire=(type:string,data:unknown)=>`event: ${type}\ndata: ${JSON.stringify(data)}\n\n`;
function clockFixture() {
  let now=0;
  const timers=new Set<{at:number;run:()=>void}>();
  const clock:StreamClock={now:()=>now,random:()=>0.5,schedule:(run,ms)=>{const item={at:now+ms,run};timers.add(item);return()=>{timers.delete(item);};}};
  return {clock,pending:()=>timers.size,advance:async(ms:number)=>{
    const end=now+ms;
    while(true){const next=[...timers].sort((a,b)=>a.at-b.at)[0];if(!next||next.at>end)break;now=next.at;timers.delete(next);next.run();await tick();}
    now=end;await tick();
  }};
}
function stream(status=200,binding=A,url=URL) {
  const {ReadableStream}=jest.requireActual('node:stream/web');
  let controller!:ReadableStreamDefaultController<Uint8Array>;
  const cancel=jest.fn();
  const body=new ReadableStream({start(value:ReadableStreamDefaultController<Uint8Array>){controller=value;},cancel});
  const response=new Response(body,{status,headers:{'Content-Type':'text/event-stream; charset=utf-8',[H.binding]:binding}});
  Object.defineProperty(response,'url',{value:url,configurable:true});
  return {response,cancel,push:(text:string)=>controller.enqueue(new TextEncoder().encode(text)),end:()=>controller.close()};
}
function owner(binding=A,generation=1) {
  return {binding,generation,isCurrent:jest.fn(()=>true),receive:jest.fn(()=>true),onAuthRequired:jest.fn()} satisfies StreamOwner;
}
function fixture() {
  const timing=clockFixture(), first=stream(), fetch=jest.fn(async(_url:string,_init:RequestInit)=>first.response);
  const client=createEventStream({origin:ORIGIN,fetch,clock:timing.clock});
  return {client,fetch,first,...timing};
}

it('opens only for a current captured owner and sends only fixed cookie/binding SSE metadata',async()=>{
  const f=fixture(), current=owner();current.isCurrent.mockReturnValue(false);
  f.client.setOwner(current);await tick();expect(f.fetch).not.toHaveBeenCalled();
  f.client.setOwner(null);current.isCurrent.mockReturnValue(true);f.client.setOwner(current);await tick();
  f.client.setOwner(current);expect(f.fetch).toHaveBeenCalledTimes(1);
  const [url,init]=f.fetch.mock.calls[0];expect(url).toBe(URL);
  expect(init).toMatchObject({method:'GET',credentials:'include',redirect:'error',cache:'no-store'});
  const headers=new Headers(init.headers);expect(headers.get(H.contract)).toBe('realtime-v1');expect(headers.get(H.expected)).toBe(A);expect(headers.get('Accept')).toBe('text/event-stream');expect(headers.get('Origin')).toBe(ORIGIN);
  expect(headers.has('Authorization')).toBe(false);expect(headers.has('Last-Event-ID')).toBe(false);
  f.client.dispose();await tick();expect(init.signal?.aborted).toBe(true);expect(f.first.cancel).toHaveBeenCalledTimes(1);expect(f.pending()).toBe(0);
});

it('delivers resource hints and truthful resync through the captured receiver, never heartbeat hints',async()=>{
  const f=fixture(), current=owner();f.client.setOwner(current);await tick();
  f.first.push(': heartbeat\n\n'+wire('invalidate',{version:1,resources:['categories']})+wire('resync',{version:1}));await tick();
  expect(current.receive.mock.calls).toEqual([[['categories'],'invalidate'],[['tasks','categories','ui'],'resync']]);
  expect(current.onAuthRequired).not.toHaveBeenCalled();f.client.dispose();
});

it('copies an admitted owner and rejects old stream data/auth errors after owner replacement',async()=>{
  const f=fixture(), a=owner(), b=owner(B,2), second=stream(200,B);
  let release!:(value:Response)=>void;
  f.fetch.mockImplementationOnce(()=>new Promise(resolve=>{release=resolve;})).mockResolvedValueOnce(second.response);
  f.client.setOwner(a);const originalReceive=a.receive;a.receive=jest.fn();a.binding=B;
  f.client.setOwner(b);await tick();release(f.first.response);await tick();
  expect(f.first.cancel).toHaveBeenCalledTimes(1);expect(originalReceive).not.toHaveBeenCalled();expect(a.onAuthRequired).not.toHaveBeenCalled();
  second.push(wire('resync',{version:1}));await tick();expect(b.receive).toHaveBeenCalledTimes(1);
  expect(new Headers(f.fetch.mock.calls[0][1].headers).get(H.expected)).toBe(A);
  f.client.dispose();expect(f.pending()).toBe(0);
});

it.each([401,403])('closes current status%s once without retry or affecting a later owner',async status=>{
  const f=fixture(), current=owner();f.fetch.mockResolvedValueOnce(stream(status).response);
  f.client.setOwner(current);await tick();expect(current.onAuthRequired).toHaveBeenCalledTimes(1);
  await f.advance(120000);expect(f.fetch).toHaveBeenCalledTimes(1);expect(f.pending()).toBe(0);f.client.dispose();
});

it('handles auth-required once, contains callback failure, and delivers no later same-chunk hint',async()=>{
  const f=fixture(), current=owner();current.onAuthRequired.mockImplementation(()=>{throw new Error('private');});
  f.client.setOwner(current);await tick();f.first.push(wire('auth-required',{version:1})+wire('invalidate',{version:1,resources:['tasks']}));await tick();
  expect(current.onAuthRequired).toHaveBeenCalledTimes(1);expect(current.receive).not.toHaveBeenCalled();expect(f.pending()).toBe(0);f.client.dispose();
});

it.each(['binding','content','redirect','foreign','wrong-path'])('rejects %s response before delivering its body without granting auth authority',async kind=>{
  const f=fixture(), current=owner(), bad=stream();
  if(kind==='binding')bad.response.headers.set(H.binding,B);
  if(kind==='content')bad.response.headers.set('Content-Type','application/json');
  if(kind==='redirect')Object.defineProperty(bad.response,'redirected',{value:true});
  if(kind==='foreign')Object.defineProperty(bad.response,'url',{value:'https://foreign.test/realtime/events/'});
  if(kind==='wrong-path')Object.defineProperty(bad.response,'url',{value:ORIGIN+'/other/'});
  f.fetch.mockResolvedValueOnce(bad.response);f.client.setOwner(current);await tick();
  expect(bad.cancel).toHaveBeenCalledTimes(1);expect(current.receive).not.toHaveBeenCalled();expect(current.onAuthRequired).not.toHaveBeenCalled();f.client.dispose();expect(f.pending()).toBe(0);
});

it('treats404 as disabled until a new activation, without retrying it indefinitely',async()=>{
  const f=fixture(), current=owner();f.fetch.mockResolvedValueOnce(stream(404).response);
  f.client.setOwner(current);await tick();await f.advance(120000);f.client.setOwner(current);expect(f.fetch).toHaveBeenCalledTimes(1);
  f.client.setOwner(null);f.client.setOwner(current);await tick();expect(f.fetch).toHaveBeenCalledTimes(2);f.client.dispose();
});

it('backs off network failures with bounded jitter and cancels scheduled reconnect on pause/dispose',async()=>{
  const f=fixture(), current=owner();f.fetch.mockRejectedValue(new Error('private network error'));
  f.client.setOwner(current);await tick();expect(current.onAuthRequired).not.toHaveBeenCalled();
  await f.advance(999);expect(f.fetch).toHaveBeenCalledTimes(1);await f.advance(1);expect(f.fetch).toHaveBeenCalledTimes(2);
  await f.advance(1999);expect(f.fetch).toHaveBeenCalledTimes(2);await f.advance(1);expect(f.fetch).toHaveBeenCalledTimes(3);
  f.client.setOwner(null);await f.advance(120000);expect(f.fetch).toHaveBeenCalledTimes(3);expect(f.pending()).toBe(0);
  f.client.dispose();f.client.setOwner(current);expect(f.fetch).toHaveBeenCalledTimes(3);
});

it('bounds retry jitter at both extremes and resets backoff only after a valid resync',async()=>{
  for(const sample of [0,1]) {
    const f=fixture(), current=owner(), times:number[]=[];
    f.clock.random=()=>sample;
    f.fetch.mockImplementation(async()=>{times.push(f.clock.now());throw new Error('network');});
    f.client.setOwner(current);await tick();await f.advance(180000);
    expect(times.length).toBeGreaterThan(6);
    expect(times.slice(1).every((time,index)=>time-times[index]>=1000 && time-times[index]<=30000)).toBe(true);
    expect(current.onAuthRequired).not.toHaveBeenCalled();f.client.dispose();expect(f.pending()).toBe(0);
  }
  const f=fixture(), current=owner();
  f.fetch.mockRejectedValueOnce(new Error('first')).mockRejectedValueOnce(new Error('second'));
  f.client.setOwner(current);await tick();await f.advance(3000);expect(f.fetch).toHaveBeenCalledTimes(3);
  f.first.push(wire('resync',{version:1}));await tick();f.first.end();await tick();
  await f.advance(999);expect(f.fetch).toHaveBeenCalledTimes(3);
  await f.advance(1);expect(f.fetch).toHaveBeenCalledTimes(4);f.client.dispose();
});

it('watchdog covers stalled headers even if fetch ignores abort, and late401 cannot revoke the newer connection',async()=>{
  const f=fixture(), current=owner();let late!:(response:Response)=>void;
  const next=stream();f.fetch.mockImplementationOnce(()=>new Promise(resolve=>{late=resolve;})).mockResolvedValueOnce(next.response);
  f.client.setOwner(current);await f.advance(45000);expect(f.fetch.mock.calls[0][1].signal?.aborted).toBe(true);
  await f.advance(1000);expect(f.fetch).toHaveBeenCalledTimes(2);late(stream(401).response);await tick();
  expect(current.onAuthRequired).not.toHaveBeenCalled();next.push(wire('resync',{version:1}));await tick();expect(current.receive).toHaveBeenCalledTimes(1);f.client.dispose();
});

it('heartbeats keep watchdog alive but cannot extend the60second connection lease',async()=>{
  const f=fixture(), current=owner();f.client.setOwner(current);await tick();
  for(let i=0;i<3;i++){await f.advance(15000);f.first.push(': heartbeat\n\n');await tick();}
  expect(f.fetch.mock.calls[0][1].signal?.aborted).toBe(false);
  await f.advance(15000);expect(f.fetch.mock.calls[0][1].signal?.aborted).toBe(true);expect(current.receive).not.toHaveBeenCalled();f.client.dispose();expect(f.pending()).toBe(0);
});

it('rechecks owner after read before dispatch and closes malformed streams without logging out',async()=>{
  const f=fixture(), current=owner();f.client.setOwner(current);await tick();
  f.first.push(wire('invalidate',{version:1,resources:['tasks']}));current.isCurrent.mockReturnValue(false);await tick();
  expect(current.receive).not.toHaveBeenCalled();expect(f.pending()).toBe(0);expect(f.first.cancel).toHaveBeenCalledTimes(1);f.client.dispose();
  const other=fixture(), next=owner();other.client.setOwner(next);await tick();other.first.push('retry: 1\n\n');await tick();
  expect(next.onAuthRequired).not.toHaveBeenCalled();expect(other.first.cancel).toHaveBeenCalledTimes(1);other.client.dispose();
});

it('negotiates rich changes and admits seed only after current-owner response validation',async()=>{
  const f=fixture(), onMutationSeed=jest.fn(),current={...owner(),onMutationSeed};
  const seed='d'.repeat(32),change={mutationId:seed+'00000001',entities:null};
  f.first.response.headers.set('X-HyperTodo-Realtime-Features','changes-v2');
  f.first.response.headers.set('X-HyperTodo-Mutation-Seed',seed);
  f.client.setOwner(current);await tick();
  expect(new Headers(f.fetch.mock.calls[0][1].headers).get('X-HyperTodo-Realtime-Features')).toBe('changes-v2');
  expect(onMutationSeed).toHaveBeenCalledWith(seed);
  f.first.push(wire('invalidate',{version:2,resources:['tasks'],mutation_id:change.mutationId,entities:null}));await tick();
  expect(current.receive).toHaveBeenCalledWith(['tasks'],'invalidate',change);
  f.client.dispose();
});

it.each(['missing-feature','wrong-feature','bad-seed','wrong-binding','late-owner'])('never accepts a seed from %s response',async kind=>{
  const f=fixture(),onMutationSeed=jest.fn(),current={...owner(),onMutationSeed};
  f.first.response.headers.set('X-HyperTodo-Mutation-Seed',kind==='bad-seed'?'unsafe':'d'.repeat(32));
  if(kind!=='missing-feature')f.first.response.headers.set('X-HyperTodo-Realtime-Features',kind==='wrong-feature'?'future':'changes-v2');
  if(kind==='wrong-binding')f.first.response.headers.set(H.binding,B);
  f.client.setOwner(current);
  if(kind==='late-owner')f.client.setOwner(null);
  await tick();expect(onMutationSeed).not.toHaveBeenCalled();f.client.dispose();
});

it('falls back to v1 when an old server does not confirm the feature',async()=>{
  const f=fixture(),current=owner();f.client.setOwner(current);await tick();
  f.first.push(wire('invalidate',{version:1,resources:['tasks']}));await tick();
  expect(current.receive).toHaveBeenCalledWith(['tasks'],'invalidate');
  f.first.push(wire('invalidate',{version:2,resources:['tasks'],mutation_id:null,entities:null}));await tick();
  expect(current.receive).toHaveBeenCalledTimes(1);expect(f.first.cancel).toHaveBeenCalledTimes(1);
  expect(current.onAuthRequired).not.toHaveBeenCalled();f.client.dispose();
});
