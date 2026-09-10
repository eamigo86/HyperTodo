import {createSessionEffects, type CredentialStore, type StorageQueue} from "../src/realtime/session-effects";

function deferred<T>(){let resolve!:(value:T)=>void;let reject!:(error:Error)=>void;const promise=new Promise<T>((yes,no)=>{resolve=yes;reject=no;});return{promise,resolve,reject};}
function fixture(){
 const store={save:jest.fn(async(_token:string)=>{}),clear:jest.fn(async()=>{})};let tail=Promise.resolve();
 const queue:StorageQueue={enqueue:(job)=>{const result=tail.then(()=>job(store));tail=result.then(()=>undefined,()=>undefined);return result;}};
 return{store,effects:createSessionEffects(queue)};
}

it("rechecks immutable effect ownership inside the native queue, before executing",async()=>{
 let job!: (store:CredentialStore)=>Promise<void>;const done=deferred<void>();
 const effects=createSessionEffects({enqueue:(value)=>{job=value;return done.promise;}});
 const store={save:jest.fn(async()=>{}),clear:jest.fn(async()=>{})};let current=true;
 const result=effects.apply({},()=>current,{kind:"store",token:"original"});current=false;
 await job(store);done.resolve();await expect(result).resolves.toBe("stale");
 expect(store.save).not.toHaveBeenCalled();expect(store.clear).not.toHaveBeenCalled();
});

it("snapshots effect content and runs a receipt exactly once",async()=>{
 let job!:(store:CredentialStore)=>Promise<void>;const done=deferred<void>();
 const effects=createSessionEffects({enqueue:(value)=>{job=value;return done.promise;}});
 const store={save:jest.fn(async()=>{}),clear:jest.fn(async()=>{})};const receipt={};const effect={kind:"store" as const,token:"original"};
 const result=effects.apply(receipt,()=>true,effect);effect.token="mutated";
 const duplicate=effects.apply(receipt,()=>true,{kind:"clear"});
 await job(store);done.resolve();await expect(result).resolves.toBe("stored");await expect(duplicate).resolves.toBe("stored");
 expect(store.save).toHaveBeenCalledTimes(1);expect(store.save).toHaveBeenCalledWith("original");expect(store.clear).not.toHaveBeenCalled();
});

it("serializes old running native work before a newer accepted effect",async()=>{
 const {store,effects}=fixture();const native=deferred<void>();store.save.mockImplementationOnce(()=>native.promise);
 const first=effects.apply({},()=>true,{kind:"store",token:"A"});await Promise.resolve();
 const second=effects.apply({},()=>true,{kind:"store",token:"B"});await Promise.resolve();expect(store.save).toHaveBeenCalledTimes(1);
 native.resolve();await first;await second;expect(store.save.mock.calls).toEqual([["A"],["B"]]);
});

it("does not let a late failed A write clear B after A loses authority",async()=>{
 const {store,effects}=fixture();const native=deferred<void>();let current=true;store.save.mockImplementationOnce(()=>native.promise);
 const first=effects.apply({},()=>current,{kind:"store",token:"A"});await Promise.resolve();current=false;
 const second=effects.apply({},()=>true,{kind:"store",token:"B"});native.reject(new Error("Old save failed"));
 await expect(first).resolves.toBe("stale");await expect(second).resolves.toBe("stored");expect(store.clear).not.toHaveBeenCalled();
});

it("awaits safe clear after a current save failure and reports clear failure truthfully",async()=>{
 const {store,effects}=fixture();store.save.mockRejectedValue(new Error("Save failed"));
 await expect(effects.apply({},()=>true,{kind:"store",token:"A"})).resolves.toBe("cleared-after-failure");expect(store.clear).toHaveBeenCalledTimes(1);
 store.clear.mockRejectedValueOnce(new Error("Clear failed"));await expect(effects.apply({},()=>true,{kind:"clear"})).resolves.toBe("failed");
});

it("bounds live receipts without eviction and refuses replay of retired receipts",async()=>{
 const jobs:Array<(store:CredentialStore)=>Promise<void>>=[];const completions:Array<ReturnType<typeof deferred<void>>>=[];
 const effects=createSessionEffects({enqueue:(job)=>{jobs.push(job);const completion=deferred<void>();completions.push(completion);return completion.promise;}});
 const first={};const tasks=[effects.apply(first,()=>true,{kind:"clear"})];for(let i=1;i<64;i++)tasks.push(effects.apply({},()=>true,{kind:"clear"}));
 await expect(effects.apply({},()=>true,{kind:"clear"})).resolves.toBe("capacity");expect(jobs).toHaveLength(64);
 const store={save:jest.fn(async()=>{}),clear:jest.fn(async()=>{})};for(let i=0;i<64;i++){await jobs[i](store);completions[i].resolve();}await Promise.all(tasks);
 const next=effects.apply({},()=>true,{kind:"clear"});await jobs[64](store);completions[64].resolve();await next;
 await expect(effects.apply(first,()=>true,{kind:"clear"})).resolves.toBe("retired");expect(jobs).toHaveLength(65);
});
