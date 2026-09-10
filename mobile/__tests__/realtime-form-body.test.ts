jest.mock("react-native-webview",()=>({WebView:()=>null}));

import {DOMParser} from "@instawork/xmldom";
import {Parser} from "hyperview";
// Test the actual pinned registry. Production uses only the public Parser/fetch seam.
import {Registry} from "hyperview/src/services/components";
import {snapshotFormRequest} from "../src/realtime/modern-form-body";
const xml='<form xmlns="https://hyperview.org/hyperview"><text-field name="csrfmiddlewaretoken" value="csrf+é"/><text-field name="tag" value="a b"/><text-field name="tag" value="&amp;=?"/><text-field name="empty" value=""/></form>';

it("snapshots the actual Hyperview Registry POST FormData before the supervisor",async()=>{
 const doc=new DOMParser().parseFromString(xml,"application/xml") as Document;
 const form=new Registry().getFormData(doc.documentElement)!;
 const transport=jest.fn(async(_url:string,_init:RequestInit)=>new Response('<view xmlns="https://hyperview.org/hyperview"/>'));
 let submitted:RequestInit|undefined;
 const parser=new Parser(async(url,init)=>{submitted=snapshotFormRequest(init);return transport(url,submitted);},undefined,undefined);
 await parser.load("https://app.test/hv/login/",form,"post");
 expect(submitted!.body).toBe("csrfmiddlewaretoken=csrf%2B%C3%A9&tag=a+b&tag=%26%3D%3F&empty=");
 expect(new Headers(submitted!.headers).get("Content-Type")).toBe("application/x-www-form-urlencoded;charset=UTF-8");
 expect(new Headers(submitted!.headers).get("X-Hyperview-Version")).toBeTruthy();
 form.append("late","discarded");expect(submitted!.body).not.toContain("late");expect(transport).toHaveBeenCalledTimes(1);
});

it("preserves strings, empty bodies, signals, metadata and GET URL serialization",async()=>{
 const signal=new AbortController().signal;const init={method:"POST",body:"a=%20&a=+",signal,headers:{"X-CSRFToken":"kept"}};const result=snapshotFormRequest(init);
 init.body="mutated";init.headers["X-CSRFToken"]="changed";
 expect(result.body).toBe("a=%20&a=+");expect(result.signal).toBe(signal);expect(new Headers(result.headers).get("X-CSRFToken")).toBe("kept");
 expect(snapshotFormRequest({body:null}).body).toBeNull();expect(snapshotFormRequest({}).body).toBeUndefined();
 const form=new FormData();form.append("tag","a b");const raw=jest.fn(async(_url:string,_init:RequestInit)=>new Response('<view xmlns="https://hyperview.org/hyperview"/>'));
 await new Parser((url,options)=>raw(url,snapshotFormRequest(options)),undefined,undefined).load("https://app.test/hv/tasks/?filter=x",form,"get");
 expect(raw.mock.calls[0][0]).toContain("filter=x");expect(raw.mock.calls[0][0]).toContain("tag=a%20b");expect(raw.mock.calls[0][1].body).toBeUndefined();
});

it("supports standard string FormData entries without dropping duplicate values",()=>{
 const body={entries:function*(){yield ["a","1"];yield ["a","é+"];}} as unknown as FormData;
 expect(snapshotFormRequest({body}).body).toBe("a=1&a=%C3%A9%2B");
});

it.each([
 {getParts:()=>[{fieldName:"file",uri:"file://private",headers:{}}]},
 {entries:function*(){yield ["file",{name:"photo"}];}},
 {getParts:()=>[{fieldName:"n",string:2}]},
 {getParts:()=>[{fieldName:2,string:"n"}]},
 {getParts:()=>null},
 {},
])("rejects unsupported/malformed body rather than dropping fields",body=>{
 expect(()=>snapshotFormRequest({body:body as unknown as FormData})).toThrow("unsupported-form-body");
});
