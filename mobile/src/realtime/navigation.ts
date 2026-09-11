import {CommonActions,type NavigationProp,type ParamListBase} from "@react-navigation/native";
import { createStylesheets, type HvComponentProps } from "hyperview";

const HV = "https://hyperview.org/hyperview";
const APP = "https://hypertodo.app/components";

/** The returned document cannot safely replace an owned ordinary screen. */
export class UnsupportedDocument extends Error {}
export type NavigationHandle = NavigationProp<ParamListBase>;

type PublicRoute={key?:string;state?:{index?:number;routes:readonly PublicRoute[]}};
function focusedBranch(route:PublicRoute|undefined):string[]{
 const keys:string[]=[],seen=new Set<PublicRoute>();
 while(route&&!seen.has(route)){
  seen.add(route);if(route.key)keys.push(route.key);
  route=route.state?.routes[route.state.index??0];
 }
 return keys;
}

/** Capture a real preceding stack entry, never guess by screen name or resource. */
export function previousRoute(navigation:NavigationHandle,currentKey:string){
 let owner:NavigationHandle|undefined=navigation;
 const seen=new Set<NavigationHandle>();
 while(owner&&!seen.has(owner)){
  seen.add(owner);const state=owner.getState(),source=state.routes[state.index];
  if(!focusedBranch(source).includes(currentKey))return null;
  if(state.type==='stack'&&state.index>0){
   const key=focusedBranch(state.routes[state.index-1]).at(-1);
   if(!key||!source?.key||!state.key)return null;
   const capturedOwner=owner,target=state.key,sourceKey=source.key;let consumed=false;
   const isCurrent=()=>{
    const now=capturedOwner.getState();
    return !consumed&&now.key===target&&now.type==='stack'&&now.index>0&&now.routes[now.index]?.key===sourceKey
     &&focusedBranch(now.routes[now.index]).includes(currentKey)&&focusedBranch(now.routes[now.index-1]).at(-1)===key;
   };
   return {key,isCurrent,goBack:()=>{
    if(!isCurrent())return false;consumed=true;
    capturedOwner.dispatch({...CommonActions.goBack(),source:sourceKey,target});return true;
   }};
  }
  owner=owner.getParent();
 }
 return null;
}

type Destination = {
  navigation: NavigationHandle;
  reason: "navigation-no-op" | "missing-destination" | null;
  url?: string;
  name?: string;
};

/** Resolve a screen URL without altering filters or adding correlation parameters. */
export function reloadUrl(href: string | null | undefined, current: string): string {
  const target = !href || href === "#" ? current : href;
  const url = new URL(target, current);
  const base = new URL(current);
  if (url.origin !== base.origin || url.hash || !["http:", "https:"].includes(url.protocol)) {
    throw new Error("unsupported-href");
  }
  return url.toString();
}

/** Require one actual screen and owned boundary before committing a reload. */
export function prepareReload(doc: Document, id: string | undefined) {
  const root = doc.documentElement;
  const children = Array.from(root.childNodes).filter(node => node.nodeType === 1) as Element[];
  const screens = children.filter(node => node.namespaceURI === HV && node.localName === "screen");
  const boundaries = doc.getElementsByTagNameNS(APP, "realtime");
  if (root.namespaceURI !== HV || root.localName !== "doc" || screens.length !== 1 ||
      children.some(node => node.localName === "navigator") || boundaries.length !== 1) {
    throw new UnsupportedDocument("Ordinary reload requires one screen and owned boundary");
  }
  if (!Array.from(boundaries[0].getElementsByTagNameNS(APP, "realtime-page"))
    .some(node => node.getAttribute("request-id") === id)) {
    throw new UnsupportedDocument("Reload result does not match its attempt");
  }
  return { boundary: boundaries[0], styles: createStylesheets(doc) };
}

/** Select only a public navigator that declares the requested destination. */
export function navigationTarget(
  navigation: NavigationHandle,
  href: string | null | undefined,
  action: string,
  current: string,
): Destination {
  if (action === "back") {
    return { navigation, reason: navigation.canGoBack() ? null : "navigation-no-op" };
  }
  if (!href || href === "#") return { navigation, reason: "missing-destination" };
  if (href.startsWith("#")) {
    const name = href.slice(1);
    let owner: NavigationHandle | undefined = navigation;
    while (owner && !owner.getState().routeNames.includes(name)) owner = owner.getParent();
    if (!owner) return { navigation, reason: "missing-destination", name };
    const state = owner.getState();
    return {
      navigation: owner,
      reason: state.routes[state.index]?.name === name ? "navigation-no-op" : null,
      name,
    };
  }
  const url = reloadUrl(href, current);
  let owner: NavigationHandle | undefined = navigation;
  while (owner && !owner.getState().routeNames.includes("card")) owner = owner.getParent();
  return { navigation: owner ?? navigation, reason: owner ? null : "missing-destination", url, name: "card" };
}

/** Require the actual caller-supplied public screen state callback. */
export function screenCallbacks(options: HvComponentProps["options"]) {
  const callbacks = options.onUpdateCallbacks;
  if (!callbacks?.setState || !callbacks.getState) throw new Error("missing-screen-callback");
  return callbacks;
}
