/** A delivery/admission pause, never a cancellation or identity revocation. */
export function createRetention() {
  let paused=false;
  const listeners=new Set<()=>void>();
  const wake=()=>{for(const listener of [...listeners])listener();};
  return {
    isPaused:()=>paused,
    set(value:boolean){paused=value;wake();},
    wake,
    async wait(owned:()=>boolean):Promise<boolean>{
      while(paused&&owned())await new Promise<void>(resolve=>{const done=()=>{listeners.delete(done);resolve();};listeners.add(done);});
      return owned();
    },
  };
}
