import type {FormObjectKind} from './form-entities';

export type ResourceName="tasks"|"categories"|"ui";
export type ResourceVersions=Readonly<Record<ResourceName,number>>;
export type NoticeLabels={changed:string;resync:string;update:string;dismiss:string;csrf:string;error:string;newerEdits?:string;conflict?:Readonly<{messages:Readonly<Record<FormObjectKind,string>>;goBack:string;backUnavailable:string}>};
const combinations=new Set(["tasks","categories","ui","tasks categories","tasks ui","categories ui","tasks categories ui"]);
/** Copy the closed ordered resource protocol; malformed events have no effects. */
export function parseResources(value:unknown):readonly ResourceName[]|null {
 if(!Array.isArray(value)||!value.every(item=>["tasks","categories","ui"].includes(item))||!combinations.has(value.join(" ")))return null;
 return Object.freeze([...value]) as readonly ResourceName[];
}
/** Read explicitly declared dependencies, never infer them from a route name. */
export function dependencies(element:Element):readonly ResourceName[]{return parseResources((element.getAttribute("resources")??"").split(" "))??[];}
export function neededVersion(names:readonly ResourceName[],current:ResourceVersions,observed:ResourceVersions):number{return Math.max(0,...names.filter(name=>current[name]>observed[name]).map(name=>current[name]));}
/** Reload the canonical full document; negotiated lists retain their loaded prefix. */
export function resourceReloadUrl(href:string,base:string,mode:string,pages:readonly number[]=[1],contextual=false):string {
 const url=new URL(href,base),origin=new URL(base);
 if(!href||url.origin!==origin.origin||url.hash||!["http:","https:"].includes(url.protocol))throw new Error("invalid-resource-refresh");
 url.searchParams.delete("fragment");
 if(mode==="list"){
  if(contextual){
   if(!pages.length||pages.some((page,index)=>page!==index+1))throw new Error('invalid-resource-prefix');
   if(pages.length>20){url.searchParams.delete('through_page');url.searchParams.set('page','1');}
   else{url.searchParams.delete('page');url.searchParams.set('through_page',String(pages.length));}
  }else{url.searchParams.delete('through_page');url.searchParams.set("page","1");}
 }
 return url.toString();
}
/** Labels are app-owned translated plain text, never markup or implicit English. */
export function readNoticeLabels(provider:(()=>NoticeLabels)|undefined):NoticeLabels|null {
 try{const labels=provider?.();const valid=(value:unknown)=>typeof value==='string'&&!!value.trim()&&value.length<=512;
  if(!labels||!["changed","resync","update","dismiss","csrf","error"].every(key=>valid(labels[key as keyof NoticeLabels])))return null;
  const conflict=labels.conflict;
  if(conflict&&(!valid(conflict.goBack)||!valid(conflict.backUnavailable)||!conflict.messages||!(['task','category','settings','form'] as const).every(kind=>valid(conflict.messages[kind]))))return null;
  return {...labels,...(conflict?{conflict:{...conflict,messages:{...conflict.messages}}}:{})};
 }catch{return null;}
}
