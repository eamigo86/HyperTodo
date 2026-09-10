/** Correlation only: identifiers cannot authorize a request or acknowledge a document. */
export function createMutationLedger(limits:Readonly<{counterLimit?:number;operationLimit?:number}>={}) {
  const counterLimit=limits.counterLimit??0xffffffff,operationLimit=limits.operationLimit??256;
  if(!Number.isInteger(counterLimit)||counterLimit<1||counterLimit>0xffffffff||!Number.isInteger(operationLimit)||operationLimit<1||operationLimit>256)throw new Error('invalid-mutation-limits');
  // One monotonic counter survives seed rotation and generation replacement.
  // Repeated/out-of-order seeds cannot reuse an identifier; no seed history grows.
  let counter=0;
  let seed:string|null=null,admitted=new WeakMap<object,string|null>();
  const recent=new Set<string>();
  return {
    acceptSeed(value:unknown):boolean {
      if(typeof value!=='string'||!/^[a-f0-9]{32}$/.test(value)){seed=null;return false;}
      seed=value;return true;
    },
    admit(operation:object):string|null {
      if(admitted.has(operation))return admitted.get(operation)!;
      const id=seed!==null&&counter<counterLimit?seed+(++counter).toString(16).padStart(8,'0'):null;
      admitted.set(operation,id);
      if(id!==null){
        recent.add(id);
        if(recent.size>operationLimit)recent.delete(recent.values().next().value!);
      }
      return id;
    },
    isOwn(value:unknown):boolean {return typeof value==='string'&&recent.has(value);},
    reset():void {seed=null;admitted=new WeakMap();recent.clear();},
  };
}
