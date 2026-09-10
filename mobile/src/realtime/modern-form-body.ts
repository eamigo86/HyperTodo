function stringPairs(body:object):Array<[string,string]> {
  const value=body as {getParts?:()=>unknown;entries?:()=>Iterable<unknown>};
  try {
    if(typeof value.getParts==="function"){
      const parts=value.getParts();if(!Array.isArray(parts))throw new Error();
      return parts.map(part=>{
        if(!part||typeof part.fieldName!=="string"||typeof part.string!=="string"||"uri" in part)throw new Error();
        return [part.fieldName,part.string];
      });
    }
    if(typeof value.entries==="function")return Array.from(value.entries(),entry=>{
      if(!Array.isArray(entry)||entry.length!==2||typeof entry[0]!=="string"||typeof entry[1]!=="string")throw new Error();
      return [entry[0],entry[1]];
    });
  } catch {throw new Error("unsupported-form-body");}
  throw new Error("unsupported-form-body");
}

/** Snapshot public Parser form data before session admission, never below it. */
export function snapshotFormRequest(init:RequestInit={}):RequestInit {
  const headers=new Headers(init.headers);let body=init.body;
  if(body!==undefined&&body!==null&&typeof body!=="string"){
    if(typeof body!=="object")throw new Error("unsupported-form-body");
    body=new URLSearchParams(stringPairs(body)).toString();
    headers.set("Content-Type","application/x-www-form-urlencoded;charset=UTF-8");
  }
  return {...init,body,headers};
}
