import React from "react";
import {Pressable,Text,View} from "react-native";

export type ResourceName="tasks"|"categories"|"ui";
export type ResourceVersions=Readonly<Record<ResourceName,number>>;
export type NoticeLabels={changed:string;resync:string;update:string;csrf:string;error:string};
const combinations=new Set(["tasks","categories","ui","tasks categories","tasks ui","categories ui","tasks categories ui"]);
/** Copy the closed ordered resource protocol; malformed events have no effects. */
export function parseResources(value:unknown):readonly ResourceName[]|null {
 if(!Array.isArray(value)||!value.every(item=>["tasks","categories","ui"].includes(item))||!combinations.has(value.join(" ")))return null;
 return Object.freeze([...value]) as readonly ResourceName[];
}
/** Read explicitly declared dependencies, never infer them from a route name. */
export function dependencies(element:Element):readonly ResourceName[]{return parseResources((element.getAttribute("resources")??"").split(" "))??[];}
export function neededVersion(names:readonly ResourceName[],current:ResourceVersions,observed:ResourceVersions):number{return Math.max(0,...names.filter(name=>current[name]>observed[name]).map(name=>current[name]));}
/** Use canonical full documents; only list policy deliberately resets pagination. */
export function resourceReloadUrl(href:string,base:string,mode:string):string {
 const url=new URL(href,base),origin=new URL(base);
 if(!href||url.origin!==origin.origin||url.hash||!["http:","https:"].includes(url.protocol))throw new Error("invalid-resource-refresh");
 url.searchParams.delete("fragment");
 if(mode==="list")url.searchParams.set("page","1");
 return url.toString();
}
/** Labels are app-owned translated plain text, never markup or implicit English. */
export function readNoticeLabels(provider:(()=>NoticeLabels)|undefined):NoticeLabels|null {
 try{const labels=provider?.();if(!labels||!["changed","resync","update","csrf","error"].every(key=>{const value=labels[key as keyof NoticeLabels];return typeof value==="string"&&!!value.trim()&&value.length<=512;}))return null;return {...labels};}catch{return null;}
}
/** Persistent accessible control rendered outside the SDK list's item collection. */
export function ResourceNotice({message,label,disabled,onUpdate}:{message:string;label:string;disabled:boolean;onUpdate?:()=>void}){
 return <View style={{padding:12,borderWidth:1,borderColor:"#777",backgroundColor:"#f2f2f2"}}><Text accessibilityRole="alert" accessibilityLiveRegion="polite" style={{color:"#171717"}}>{message}</Text>{onUpdate?<Pressable accessibilityRole="button" accessibilityLabel={label} accessibilityState={{disabled}} disabled={disabled} onPress={onUpdate} style={{paddingVertical:10}}><Text style={{color:"#154899",fontWeight:"600"}}>{label}</Text></Pressable>:null}</View>;
}
