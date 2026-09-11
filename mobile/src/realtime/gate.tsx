import { useIsFocused, useRoute, useNavigation } from "@react-navigation/native";
import Hyperview, { Parser, renderChildren, shallowCloneToRoot, type HvComponentOnUpdate, type HvComponentProps, type HvBehavior } from "hyperview";
import React, { createContext, useContext, useLayoutEffect, useMemo, useSyncExternalStore } from "react";
import {ActivityIndicator,StyleSheet,View} from 'react-native';
import RealtimeNotice from '../components/RealtimeNotice';
import RealtimeConflictDialog from '../components/RealtimeConflictDialog';

import type { FetchImplementation } from "../network";
import { decorateOperationHref, hasReservedBody, readOperationUrl, nextCounter, OPERATION_PARAMETER } from "./operation";

import {findTarget, fragmentReplacement} from "./fragment";
import {navigationTarget, previousRoute, prepareReload, reloadUrl, screenCallbacks, UnsupportedDocument, type NavigationHandle} from "./navigation";

import {parseOwnedAuthPanel,type GatePorts,type GateObservation,type Outcome,type TerminalReason} from "./auth";
import {classifyAuth} from "./session-protocol";
import type {AuthResult} from "./session";
import {CHANGE_HEADERS,type ResourceChange} from './stream-protocol';
import {captureDraft,trackDraft,type DraftState} from './drafts';
import {affectsForm,formObjectKind} from './form-entities';
import {createRetention} from "./retention";
import {dependencies,neededVersion,parseResources,readNoticeLabels,resourceReloadUrl,type ResourceName,type ResourceVersions} from "./resources";

let nextInstance = 0;

const NAMESPACE = "https://hypertodo.app/components";
const REQUEST_HEADER = "X-HyperTodo-Request-ID";
const ROOT_PROVENANCE = Symbol("realtime-root-provenance");
const DOCUMENT_PROVENANCE = Symbol("realtime-document-provenance");
type DocumentProvenance = Readonly<{instance:number;epoch:number;operation:Operation;url:string}>;
type RootProvenance = Readonly<{instance: number; epoch: number}>;
type RootRequestInit = RequestInit & {[ROOT_PROVENANCE]?: RootProvenance;[DOCUMENT_PROVENANCE]?:DocumentProvenance};
type Update = Parameters<HvComponentOnUpdate>;
type RouteSnapshot = {
  key: string;
  focused: boolean;
  pages: number[];
  refreshHref: string;
  notice: boolean;
  noticeCode?: "auth-refused";
};
type Runtime = {fetch:FetchImplementation;before?:React.ComponentProps<typeof Hyperview>["onParseBefore"];after?:React.ComponentProps<typeof Hyperview>["onParseAfter"];parser: Parser; onError?: React.ComponentProps<typeof Hyperview>["onError"];loadingScreen?:React.ComponentProps<typeof Hyperview>["loadingScreen"]};
const RuntimeContext = createContext<Runtime | null>(null);
class NoDocument extends Error {}
class UncorrelatedResult extends Error {}

type Route = RouteSnapshot & {
  runtime: Runtime | null;
  navigation:NavigationHandle;
  options: HvComponentProps["options"];
  failedVersion?: number;
  ready?: boolean;
  element: Element;
  onUpdate: HvComponentOnUpdate;
  target: string;
  mode: string;
  observed: number;
  baseUrl: string;
  resources:readonly ResourceName[];
  observedResources:ResourceVersions;
  resourceFailure?:number;
  draft?:DraftState;
  documentRevision:number;
  confirming?:boolean;
  consent?:Readonly<{revision:number;documentRevision:number;kind:'refresh'|'leave'}>;
  heldDraft?:Operation;
  formVersions:ResourceVersions;
  formChanges:ResourceVersions;
  contextual:boolean;
  concealed:boolean;
  feedbackVersions:ResourceVersions;
  dismissedNotice?:string;
};
type Operation = { key: string; epoch: number; token: string; canonicalUrl: string; args: Readonly<Update>; method: "get" | "post"; kind: "ordinary" | "refresh"; phase: "pending" | "submitted"; version: number; id?: string; local?: boolean; syncId?: string; timer?: ReturnType<typeof setTimeout>; result?: Element;document?:Document;cleanup?:()=>void;navigationCheck?:()=>void;authHeld?:boolean;authPreparing?:boolean;authDelivery?:AuthResult;authDelivered?:boolean;authReceipt?:object;responseStatus?:number;resourceRefresh?:boolean;resourceVersion?:number;draftRevision?:number;releaseDraft?:(accepted:boolean)=>void;remoteFeedback?:boolean;draftCommit?:Readonly<{revision:number;after:string}> };

/** App-owned public Hyperview coordinator; transports never grant XML ACK authority. */
export function createRealtimeGate(ports:GatePorts={}) {
  const instance = nextCounter(nextInstance);
  nextInstance = instance;
  const activeRoots = new WeakSet<RootProvenance>();
  const documentRequests = new WeakSet<DocumentProvenance>();
  const retention=createRetention();
  const authSignals=new WeakMap<object,{operation:Operation;result:AuthResult}>();
  const effectReceipts=new WeakMap<Element,object>();
  const settingsClears=new WeakSet<Element>();
  const sourceAuthorities=new WeakMap<object,Element>();
  let readyEpoch:number|undefined;
  let operationSequence = 0;
  let sequence = 0;
  let lastTerminal: {outcome: Outcome; reason: TerminalReason; routeKey: string} | null = null;
  const localCommits = new WeakMap<Element, Operation>();
  let lastRejection: {reason: string; routeKey?: string} | null = null;
  let epoch = 0;
  let resumableEpoch: number | null = null;
  let version = 0;
  let resourceSequence=0;
  let resourceVersions:ResourceVersions={tasks:0,categories:0,ui:0};
  let changedResourceVersions:ResourceVersions={tasks:0,categories:0,ui:0};
  let noticeRevision=0;
  let interactionLease=Object.freeze({});
  const noticeListeners=new Set<()=>void>();
  const subscribeNotice=(listener:()=>void)=>{noticeListeners.add(listener);return()=>{noticeListeners.delete(listener);};};
  const noticeSnapshot=()=>noticeRevision;
  const notifyNotice=()=>{if(!ports.noticeLabels)return;noticeRevision+=1;for(const listener of noticeListeners)listener();};
  let blocked = false;
  let suspended = false;
  let rootRevision = 0;
  const rootListeners = new Set<() => void>();
  let active: Operation | undefined;
  const pending = new Map<string, { epoch: number; version: number; url: string; operation?: Operation;resources:ResourceVersions;contextual?:boolean }>();
  const operations = new Map<string, Operation>();
  const routes = new Map<string, Route>();
  const queue: Operation[] = [];
  const tracksDraft=(mode:string)=>['list','form','readonly'].includes(mode);
  const versionsFor=(route:Route)=>route.mode==='form'?route.formVersions:resourceVersions;
  const changesFor=(route:Route)=>route.mode==='form'?route.formChanges:changedResourceVersions;
  const automatic=(route:Route)=>route.mode==='readonly'||(route.mode==='list'&&(route.contextual?route.pages.length>0&&route.pages.every((page,index)=>page===index+1):route.pages.length===1&&route.pages[0]===1));
  function updateDraft(route:Route,functionalEdit=false){
    if(tracksDraft(route.mode)){
      const previous=route.draft,next=trackDraft(previous,captureDraft(route.element,route.options.componentRegistry));
      route.draft=functionalEdit&&previous?.current===null&&next.current===null?Object.freeze({...next,revision:next.revision+1}):next;
      if(route.consent&&route.consent.revision!==route.draft.revision)route.consent=undefined;
    }
    return route.draft;
  }
  const consentCurrent=(route:Route)=>route.consent&&route.consent.documentRevision===route.documentRevision&&route.consent.revision===route.draft?.revision;
  const remoteConflict=(route:Route)=>route.mode==='form'&&neededVersion(route.resources,changesFor(route),route.observedResources)>0;
  const conflictBusy=(route:Route)=>[...operations.values()].some(operation=>operation!==route.heldDraft)||route.confirming===true;

  /** Consent belongs to this document/revision, not a reusable native callback. */
  function conflictChoices(route:Route){
    const capturedEpoch=epoch,lease=interactionLease,element=route.element,documentRevision=route.documentRevision,revision=route.draft?.revision;
    const previous=previousRoute(route.navigation,route.key),destination=previous&&routes.get(previous.key);
    const destinationElement=destination?.element,destinationRevision=destination?.documentRevision;
    const canReturn=()=>{
      const current=destination&&routes.get(destination.key);
      const draft=current&&updateDraft(current);
      return !!previous&&previous.isCurrent()&&!!current&&current.element===destinationElement
        &&current.documentRevision===destinationRevision&&current.ready===true&&!!draft&&!draft.dirty;
    };
    const choose=(back:boolean)=>{
      const current=routes.get(route.key);
      if(capturedEpoch!==epoch||lease!==interactionLease||suspended||retention.isPaused()||!current?.focused||current.element!==element||current.documentRevision!==documentRevision
        ||updateDraft(current)?.revision!==revision||consentCurrent(current)||!remoteConflict(current)||conflictBusy(current)||current.noticeCode||current.failedVersion===version)return;
      if(back&&!canReturn())return;
      current.consent=Object.freeze({revision:revision!,documentRevision,kind:back?'leave':'refresh'});current.concealed=true;
      // This response already committed on the server, but has not delivered any
      // local effects. Retire it terminally: no swap, onEnd, navigation or ACK.
      if(current.heldDraft)finish(current.heldDraft,'cancelled','sync-replaced',false);
      if(back){
        const target=routes.get(previous!.key)!;
        target.consent=Object.freeze({revision:target.draft!.revision,documentRevision:target.documentRevision,kind:'refresh'});target.concealed=true;
        if(!previous!.goBack()){target.consent=undefined;current.consent=undefined;notifyNotice();return;}
        drain();
      }else refreshResources(current,true);
      notifyNotice();
    };
    return {canGoBack:canReturn(),onUpdate:()=>choose(false),onGoBack:()=>choose(true)};
  }
  function functionalField(route:Route,field:Element){
    if(field.namespaceURI!=='https://hyperview.org/hyperview'||!['text-field','picker-field','date-field','switch'].includes(field.localName)||field.getAttribute('name')==='csrfmiddlewaretoken')return false;
    if(!Array.from(route.element.getElementsByTagName('*')).includes(field))return false;
    let parent:Node|null=field.parentNode;while(parent&&parent!==route.element){if(parent.nodeType===1&&(parent as Element).localName==='form')return true;parent=parent.parentNode;}return false;
  }

  const subscribeRoot = (listener: () => void) => {
    rootListeners.add(listener);
    return () => { rootListeners.delete(listener); };
  };
  const rootSnapshot = () => rootRevision;
  const notifyRoot = () => {
    rootRevision += 1;
    for (const listener of rootListeners) listener();
  };

  /** Own the entire HXML tree; a boundary cannot hide stale sibling content. */
  function Root(props: React.ComponentProps<typeof Hyperview>) {
    const revision = useSyncExternalStore(subscribeRoot, rootSnapshot, rootSnapshot);
    // App locale changes can rerender Root while Hyperview's PureComponent
    // correctly retains its tree; update only the independent notice store.
    useLayoutEffect(()=>{notifyNotice();});
    const renderEpoch = epoch;
    const provenance = useMemo(() => Object.freeze({instance, epoch:renderEpoch}), [renderEpoch]);
    useLayoutEffect(() => {
      if (!suspended) activeRoots.add(provenance);
      return () => {activeRoots.delete(provenance);};
    }, [provenance, revision]);
    const fetch = useMemo<FetchImplementation>(() => async (input, init) => {
      // Native/custom callbacks can retain the old tree's public onUpdate even
      // after it unmounts. Never admit those requests under a new session.
      if (renderEpoch !== epoch) throw new Error("Stale realtime root");
      if (suspended) throw new Error("Realtime authentication is suspended");
      if (!activeRoots.has(provenance)) throw new Error("Stale realtime root");
      const ownedInit: RootRequestInit = {...init, [ROOT_PROVENANCE]:provenance};
      return props.fetch(input, ownedInit);
    }, [renderEpoch, props.fetch, provenance]);
    const runtime = useMemo<Runtime>(()=>({fetch,before:props.onParseBefore,after:props.onParseAfter,parser:new Parser(fetch, props.onParseBefore, props.onParseAfter), onError:props.onError,loadingScreen:props.loadingScreen}), [fetch,props.onParseBefore,props.onParseAfter,props.onError,props.loadingScreen]);
    // Suspend instead of immediately fetching under cookies that may still
    // belong to the old session. Authentication must confirm before resuming.
    return suspended ? null : <RuntimeContext.Provider value={runtime}><Hyperview key={renderEpoch} {...props} fetch={fetch} /></RuntimeContext.Provider>;
  }

  function observe(event:GateObservation){
    try{ports.onObservation?.(Object.freeze({...event}));}catch{ /* Observation cannot change an already decided lifecycle. */ }
  }

  function ready(route:Route){
    if(retention.isPaused()||suspended||!route.focused||!route.ready||readyEpoch===epoch)return;
    readyEpoch=epoch;
    observe({kind:"ready",epoch,routeKey:route.key});
    try{ports.onReady?.(Object.freeze({epoch,routeKey:route.key}));}catch{ /* Reporting cannot invent another readiness. */ }
  }

  function reject(reason: string, routeKey?: string) {
    lastRejection = {reason, ...(routeKey ? {routeKey} : {})};
  }

  function retire(operation: Operation) {
    operation.releaseDraft?.(false);operation.releaseDraft=undefined;
    const route=routes.get(operation.key);if(route?.heldDraft===operation)route.heldDraft=undefined;
    operation.cleanup?.();
    if (operation.timer) clearTimeout(operation.timer);
    operations.delete(operation.token);
    if (operation.id) pending.delete(operation.id);
    if (active === operation) active = undefined;
    retention.wake();
  }

  function indicators(operation: Operation, before: boolean) {
    const route = routes.get(operation.key);
    if (!route || operation.epoch !== epoch) return;
    const options = operation.args[3];
    for (const [names, visible] of [[options.showIndicatorIds,before],[options.hideIndicatorIds,!before]] as const) {
      for (const id of (names || "").split(/\s+/).filter(Boolean)) {
        const target = Array.from(currentDocument(route.element)?.getElementsByTagName("*") || []).find(node=>node.getAttribute("id")===id);
        if (!target) continue;
        const replacement = target.cloneNode(false) as Element;
        for (const child of Array.from(target.childNodes)) replacement.appendChild(child);
        replacement.setAttribute("hide",visible ? "false" : "true");
        route.onUpdate(null,"swap",target,{newElement:replacement});
        // Swap updates XML synchronously; observe its new tree without calling
        // this an ACK. Only Boundary's later layout may acknowledge a result.
        const current = currentDocument(replacement)?.getElementsByTagNameNS(NAMESPACE,"realtime")[0];
        if (current) route.element = current;
      }
    }
  }

  function finish(operation: Operation, outcome: Outcome, reason: TerminalReason, progress = true) {
    if (operations.get(operation.token) !== operation) return;
    lastTerminal = {outcome, reason, routeKey:operation.key};
    if (outcome !== "ack") indicators(operation,false);
    const route = routes.get(operation.key);
    if (route && outcome === "ack") {route.failedVersion = undefined;route.noticeCode=undefined;if(operation.args[1]==="reload")route.resourceFailure=undefined;}
    else if (route && !["once","sync-replaced","sdk-on-end","navigation-changed","navigation-no-op","missing-destination"].includes(reason)) {route.notice = true; route.failedVersion = version;}
    if(route&&operation.resourceRefresh&&outcome!=="ack"&&reason!=="owner-unavailable")route.resourceFailure=operation.resourceVersion;
    retire(operation);
    observe({kind:"terminal",epoch:operation.epoch,routeKey:operation.key,operation:operation.id??null,outcome,reason});
    notifyNotice();
    if (progress) drain();
  }

  function reportError(route: Route, error: Error) {
    try {route.runtime?.onError?.(error);} catch {
      // Caller reporting cannot skip our cleanup or create an unhandled rejection.
      if (lastTerminal?.routeKey === route.key && lastTerminal.outcome !== "ack") lastTerminal = {...lastTerminal,reason:"caller-error"};
    }
  }

  function callEnd(route: Route, operation: Operation) {
    try {operation.args[3].onEnd?.();} catch (error) {reportError(route,error as Error);}
  }

  function cancelOwner(key: string, refreshOnly = false) {
    for (const operation of operations.values()) {
      if (operation.key === key && (!refreshOnly || operation.kind === "refresh")) { operation.navigationCheck?.(); finish(operation,"cancelled","owner-unavailable",false); }
    }
  }

  function currentDocument(element: Element): Document | null {
    let root: Node = element;
    while (root.parentNode) root = root.parentNode;
    return root.nodeType === 9 ? root as Document : null;
  }

  function hasReservedForm(element: Element): boolean {
    let ancestor: Node | null = element;
    while (ancestor?.nodeType === 1) {
      const current = ancestor as Element;
      if (current.localName === "form" && current.namespaceURI === "https://hyperview.org/hyperview") {
        return Array.from(current.getElementsByTagName("*")).some(field => field.getAttribute("name") === OPERATION_PARAMETER);
      }
      ancestor = ancestor.parentNode;
    }
    return false;
  }

  function enqueue(key: string, args: Update, kind: Operation["kind"], ownerEpoch = epoch,resourceRefresh=false) {
    const route = routes.get(key);
    if(retention.isPaused()){reject("paused-owner",key);return;}
    if (route && currentDocument(route.element)?.getElementsByTagNameNS(NAMESPACE, "realtime").length !== 1) { reject("ambiguous-owner", key); return; }
    if (ownerEpoch !== epoch || suspended) { reject("stale-owner", key); return; }
    if (!route?.focused) { reject("inactive-owner", key); return; }
    const [href, action] = args;
    if (!Array.from(currentDocument(route.element)!.getElementsByTagName("*")).includes(args[2])) { reject("missing-origin", key); return; }
    if (!["append","replace","reload","navigate","back"].includes(action??"")) {
      // Native input callbacks can arrive after their panel was replaced. Only
      // a live node may reach SDK swap: its detached ancestor is not a Document.
      const replacement=args[3].newElement;
      const functionalEdit=action==='swap'&&replacement?.nodeType===1&&functionalField(route,args[2])&&args[2].getAttribute('value')!==replacement.getAttribute('value');
      route.onUpdate(...args);
      // SDK swap moves the live tree synchronously, before React layout. Carry
      // that authority forward for another current edit; this is never an ACK.
      const document=route.options.onUpdateCallbacks?.getDoc();
      const boundaries=document?.getElementsByTagNameNS(NAMESPACE,"realtime");
      if(ownerEpoch===epoch&&routes.get(key)===route&&boundaries?.length===1)route.element=boundaries[0];
      updateDraft(route,functionalEdit);drain();
      return;
    }
    const navigationAction=action==="navigate"||action==="back";
    if ((!href || !href.trim()) && action!=="reload" && !navigationAction) { reject("missing-href", key); return; }
    const local = !navigationAction && action!=="reload" && !!href?.startsWith("#");
    if (local) {
      const found = Array.from(currentDocument(route.element)!.getElementsByTagName("*")).some(element => element.getAttribute("id") === href!.slice(1));
      if (!found) { reject("missing-local-source", key); return; }

    }
    let canonicalUrl = href??"";
    if(action==="reload")try{canonicalUrl=reloadUrl(href,typeof route.options.screenUrl==="string"?route.options.screenUrl:route.baseUrl);}catch{reject("unsupported-href",key);return;}
    else if (!local && !navigationAction) try {
      const url = new URL(href!, route.baseUrl);
      const base = new URL(route.baseUrl);
      if (url.hash || !["http:", "https:"].includes(url.protocol) || url.origin !== base.origin) throw new Error("unsupported-href");
      canonicalUrl = url.toString();
      decorateOperationHref(href!, "g0-1-0-1");
    } catch (error) { reject(error instanceof Error && error.message === "reserved-parameter" ? "reserved-parameter" : "unsupported-href", key); return; }
    if (hasReservedForm(args[2])) { reject("reserved-parameter", key); return; }
    if (args[3]?.once && args[3].behaviorElement?.getAttribute("ran-once")) {
      lastTerminal = {outcome:"no-document",reason:"once",routeKey:key};
      observe({kind:"terminal",epoch,routeKey:key,operation:null,outcome:"no-document",reason:"once"});
      try {args[3].onEnd?.();} catch(error) {reportError(route,error as Error);}
      return;
    }
    const syncId = args[3]?.syncId || undefined;
    if (syncId) {
      // Submitted XML is no longer replaceable network work, but still owns
      // the serialization barrier until its matching real boundary layout.
      const existing = [...operations.values()].filter(candidate=>candidate.key===key && candidate.syncId===syncId && candidate.phase!=="submitted");
      if (existing.length && args[3]?.syncMethod !== "replace") {lastTerminal={outcome:"dropped",reason:"sync-drop",routeKey:key};observe({kind:"terminal",epoch,routeKey:key,operation:null,outcome:"dropped",reason:"sync-drop"});return;}
      for (const candidate of existing) finish(candidate,"cancelled","sync-replaced",false);
    }
    if (operations.size >= 64) { reject("operation-capacity", key); return; }
    try { operationSequence = nextCounter(operationSequence); }
    catch { reject("operation-counter", key); return; }
    const token = `g0-${instance}-${epoch}-${operationSequence}`;
    // Keep immutable dispatch authority separate from the caller's retained options.
    const options = Object.freeze({...args[3]});
    const admitted: Readonly<Update> = Object.freeze([args[0], args[1], args[2], options]);
    const method = action!=="reload" && options.verb === "post" ? "post" : "get";
    const operation: Operation = {key, epoch, token, canonicalUrl, args:admitted, method, kind, phase:"pending", version, local, syncId,resourceRefresh,resourceVersion:resourceRefresh?neededVersion(route.resources,versionsFor(route),route.observedResources):undefined};
    // A new explicit action supersedes the unapplied old result; do not block
    // logout/navigation behind an unanswered draft dialog or replay its POST.
    if(kind==='ordinary'&&active?.releaseDraft)finish(active,'cancelled','sync-replaced',false);
    operations.set(token, operation);
    queue.push(operation);
    drain();
  }

  function run(operation: Operation) {
    const route = routes.get(operation.key);
    if (!route || (operation.kind === "refresh" && !route.focused) || operation.epoch !== epoch) { finish(operation,"cancelled","owner-unavailable",false); return; }
    active = operation;
    const [href, action, element, options] = operation.args;
    if(action==="navigate"||action==="back"){runNavigation(operation,route);return;}
    if(action==="reload"){void runReload(operation,route);return;}
    // Bare Hyperview remains a C1-only harness; owned lifecycles require Root.
    if (!route.runtime) {
      route.onUpdate(decorateOperationHref(href!, operation.token), action, element, {...options,onEnd:()=>{if(active===operation&&!operation.id)finish(operation,"no-document","sdk-on-end",false);try{callEnd(route,operation);}finally{drain();}}});
      return;
    }
    const behavior = options.behaviorElement;
    if (options.once && behavior) {
      if (behavior.getAttribute("ran-once")) {finish(operation,"no-document","once",false);try{callEnd(route,operation);}finally{drain();}return;}
      behavior.setAttribute("ran-once","true");
    }
    const form = route.options.componentRegistry?.getFormData(element) ?? null;
    if(operation.method==='post')operation.draftRevision=updateDraft(route)?.revision;
    const retryAction = behavior?.getAttribute("network-retry-action") as Parameters<Parser["loadElement"]>[3];
    const retryEvent = behavior?.getAttribute("network-retry-event");
    indicators(operation,true);
    const execute = async () => {
      operation.timer = undefined;
      const current = routes.get(operation.key);
      if (operations.get(operation.token)!==operation || suspended || operation.epoch!==epoch) return;
      if(retention.isPaused()&&!await retention.wait(()=>operations.get(operation.token)===operation&&!suspended&&operation.epoch===epoch))return;
      if (!current || !findTarget(current.element,element,options)) {finish(operation,"cancelled","missing-target");return;}
      if (options.delay && behavior && !Array.from(currentDocument(current.element)!.getElementsByTagName("*")).includes(behavior)) {finish(operation,"cancelled","removed-delayed-origin",false);try{callEnd(route,operation);}finally{drain();}return;}
      try {
        let source: Element;
        if (operation.local) {
          const original = Array.from(currentDocument(current.element)!.getElementsByTagName("*")).find(node=>node.getAttribute("id")===href!.slice(1));
          if (!original) {finish(operation,"no-document","missing-local-source");return;}
          source = original.cloneNode(true) as Element;
        } else {
          const result = await route.runtime!.parser.loadElement(decorateOperationHref(operation.canonicalUrl,operation.token),form,operation.method,retryAction,retryEvent);
          if (typeof result === "symbol") {finish(operation,"no-document","parser-no-op");return;}
          source = result.doc.documentElement;
          const markers = [source,...Array.from(source.getElementsByTagNameNS(NAMESPACE,"realtime-page"))];
          if (!markers.some(marker=>marker.namespaceURI===NAMESPACE && marker.localName==="realtime-page" && marker.getAttribute("request-id")===operation.id)) throw new UncorrelatedResult("Uncorrelated realtime result");
        }
        // This is the owned delivery seam: public Parser completion is NOT an ACK.
        if(!await retention.wait(()=>operations.get(operation.token)===operation&&!suspended&&operation.epoch===epoch))return;
        indicators(operation,false);
        let owner = routes.get(operation.key);
        let target = owner && findTarget(owner.element,element,options);
        if (!owner || !target) {finish(operation,"cancelled","missing-target");return;}
        if(operation.method==='post'&&operation.draftRevision!==undefined&&(target.localName==='form'||target.getElementsByTagName('form').length)){
          while(updateDraft(owner)?.revision!==operation.draftRevision){
            owner.heldDraft=operation;notifyNotice();
            const accepted=await new Promise<boolean>(resolve=>{operation.releaseDraft=resolve;});
            operation.releaseDraft=undefined;
            if(!accepted||operations.get(operation.token)!==operation||operation.epoch!==epoch||suspended)return;
            if(!await retention.wait(()=>operations.get(operation.token)===operation&&operation.epoch===epoch&&!suspended))return;
            owner=routes.get(operation.key);target=owner&&findTarget(owner.element,element,options);
            if(!owner||!target){finish(operation,'cancelled','missing-target');return;}
          }
          owner.heldDraft=undefined;
        }
        const replacement = fragmentReplacement(target,source,action!);
        const beforeDraft=updateDraft(owner),wholeDraft=captureDraft(owner.element,owner.options.componentRegistry);
        const replacesCompleteForm=operation.method==='post'&&operation.responseStatus===200&&action==='replace'&&wholeDraft!==null&&wholeDraft!=='[]'&&captureDraft(target,owner.options.componentRegistry)===wholeDraft;
        const settingsUrl=operation.responseStatus===200&&operation.method==="post"?new URL(operation.canonicalUrl):null;
        if(settingsUrl&&operation.method==="post"&&operation.responseStatus===200&&action==="replace"&&options.targetId==="settings-form-panel"&&settingsUrl.origin===new URL(owner.baseUrl).origin&&settingsUrl.pathname==="/hv/settings/"&&!settingsUrl.search&&source.namespaceURI==="https://hyperview.org/hyperview"&&source.localName==="view"&&source.getAttribute("id")==="settings-form-panel"){
          for(const node of Array.from(source.childNodes))if(node.nodeType===1){
            const behavior=node as Element;
            if(behavior.namespaceURI==="https://hyperview.org/hyperview"&&behavior.localName==="behavior"&&behavior.getAttribute("action")==="store-biometric-token"&&behavior.getAttribute("trigger")==="load"&&behavior.hasAttribute("token")&&behavior.getAttribute("token")===""&&behavior.getAttribute("once")==="true"&&behavior.getAttribute("immediate")==="true")settingsClears.add(behavior);
          }
        }
        operation.result = replacement;
        operation.phase = "submitted";
        if (operation.local) localCommits.set(replacement,operation);
        owner.onUpdate(null,"swap",target,{newElement:replacement});
        // Public swap synchronously moves live nodes into a cloned tree before
        // React layout. Carry only this owned tree forward; this is not an ACK.
        const boundaries = currentDocument(replacement)?.getElementsByTagNameNS(NAMESPACE,"realtime");
        if (routes.get(operation.key)===owner && operations.get(operation.token)===operation && boundaries?.length===1){
          owner.element=boundaries[0];
          const after=captureDraft(owner.element,owner.options.componentRegistry);
          if(replacesCompleteForm&&beforeDraft&&after!==null)operation.draftCommit=Object.freeze({revision:beforeDraft.revision,after});
        }
        callEnd(owner,operation);
      } catch (error) {
        const signal=error&&typeof error==="object"?authSignals.get(error):undefined;
        if(signal&&signal.operation===operation){authSignals.delete(error as object);await deliverAuth(operation,signal.result);return;}
        if (operations.get(operation.token)!==operation) return;
        const outcome = error instanceof NoDocument ? "no-document" : error instanceof Error && error.name === "AbortError" ? "cancelled" : "error";
        finish(operation,outcome,error instanceof NoDocument ? "empty-response" : error instanceof UncorrelatedResult ? "uncorrelated-result" : "request-error",false);
        try {if (outcome === "error") reportError(route,error as Error);} finally {drain();}
      }
    };
    if (options.delay) operation.timer=setTimeout(()=>{void execute();},parseInt(options.delay,10));
    else void execute();
  }

  function runNavigation(operation:Operation,route:Route){
    try{
      const [href,action,element,options]=operation.args;
      const target=navigationTarget(route.navigation,href,action!,route.baseUrl);
      if(target.reason){finish(operation,"no-document",target.reason as TerminalReason);return;}
      const before=JSON.stringify(target.navigation.getState());
      const check=()=>{
        if(operations.get(operation.token)!==operation||operation.epoch!==epoch||suspended)return;
        const state=target.navigation.getState(),focused=state.routes[state.index];
        if(JSON.stringify(state)===before)return;
        if(target.name && focused?.name!==target.name)return;
        if(target.url && new URL(String((focused?.params as {url?:string})?.url),route.baseUrl).pathname!==new URL(target.url).pathname)return;
        finish(operation,"no-document","navigation-changed");
      };
      operation.navigationCheck=check;
      operation.cleanup=target.navigation.addListener("state",check);
      route.onUpdate(href,action,element,options);
      check();
    }catch(error){finish(operation,"error","request-error",false);reportError(route,error as Error);drain();}
  }

  async function runReload(operation:Operation,route:Route){
    operation.draftRevision=updateDraft(route)?.revision;
    operation.remoteFeedback=operation.resourceRefresh&&route.focused&&!route.concealed&&automatic(route)&&neededVersion(route.resources,route.feedbackVersions,route.observedResources)>0;
    try{
      if(!route.runtime)throw new Error("missing-screen-runtime");
      const callbacks=screenCallbacks(route.options);
      const options=operation.args[3];
      if(options.once&&options.behaviorElement)options.behaviorElement.setAttribute("ran-once","true");
      indicators(operation,true);
      const parser=new Parser(async(input,init)=>{
        const url=input;
        const authority=Object.freeze({instance,epoch:operation.epoch,operation,url});
        documentRequests.add(authority);
        try{return await route.runtime!.fetch(input,{...init,[DOCUMENT_PROVENANCE]:authority} as RootRequestInit);}
        finally{documentRequests.delete(authority);}
      },route.runtime.before,route.runtime.after);
      const result=await parser.loadDocument(operation.canonicalUrl);
      if(!await retention.wait(()=>operations.get(operation.token)===operation&&!suspended&&operation.epoch===epoch))return;
      const current=routes.get(operation.key);
      if(!current||updateDraft(current)?.revision!==operation.draftRevision){
        indicators(operation,false);if(current)current.resourceFailure=operation.resourceVersion;
        finish(operation,'cancelled','sync-replaced',false);drain();return;
      }
      const prepared=prepareReload(result.doc,operation.id);
      indicators(operation,false);
      operation.document=result.doc;operation.result=result.doc.documentElement;operation.phase="submitted";
      callbacks.setState({doc:result.doc,styles:prepared.styles,url:operation.canonicalUrl,error:null,elementError:null,staleHeaderType:result.staleHeaderType});
      if(routes.get(operation.key)===route&&operations.get(operation.token)===operation)route.element=prepared.boundary;
      callEnd(route,operation);
    }catch(error){
      if(operations.get(operation.token)!==operation)return;
      const outcome=error instanceof NoDocument?"no-document":error instanceof Error&&error.name==="AbortError"?"cancelled":"error";
      finish(operation,outcome,error instanceof UnsupportedDocument?"unsupported-document":error instanceof NoDocument?"empty-response":"request-error",false);
      if(outcome==="error")reportError(route,error as Error);drain();
    }
  }

  function drain() {
    // Mark retained stale read-only content even while another route owns HTTP.
    // Rendering keeps this tree mounted, but cannot expose it on the next focus.
    for(const route of routes.values())if(!route.focused&&automatic(route)&&!updateDraft(route)?.dirty&&neededVersion(route.resources,versionsFor(route),route.observedResources)>0)route.concealed=true;
    notifyNotice();
    if (blocked || active || suspended || retention.isPaused()) return;
    while (queue.length) {
      const next = queue.shift()!;
      if (!operations.has(next.token)) continue;
      run(next);
      if (active) return;
    }
    for (const route of routes.values()) {
      const legacyNotice=route.observed < version || route.failedVersion === version;
      const dirty=neededVersion(route.resources,versionsFor(route),route.observedResources);
      route.notice=legacyNotice||dirty>0;
      const editing=updateDraft(route)?.dirty;
      if(consentCurrent(route)&&route.consent?.kind==='refresh'&&route.ready&&route.focused&&route.resourceFailure!==dirty){
        refreshResources(route,true);break;
      }
      if(dirty&&!editing&&route.ready&&route.focused&&automatic(route)&&route.resourceFailure!==dirty){
        refreshResources(route);break;
      }
      if (legacyNotice && !editing && route.focused && route.mode === "list" && route.pages.length === 1 && route.failedVersion !== version) {
        enqueue(route.key, [route.refreshHref, "replace", route.element, {targetId:route.target,verb:"get"}], "refresh");
        break;
      }
    }
  }

  function refreshResources(route:Route,discardConfirmed=false){
    if(!route.ready||!route.focused||retention.isPaused()||suspended||!readNoticeLabels(ports.noticeLabels)||[...operations.values()].some(operation=>operation.key===route.key&&operation.resourceRefresh))return;
    if(updateDraft(route)?.dirty&&!discardConfirmed)return;
    try{const url=resourceReloadUrl(route.refreshHref,route.baseUrl,route.mode,route.pages,route.contextual);enqueue(route.key,[url,"reload",route.element,{}],"refresh",epoch,true);}
    catch{route.resourceFailure=neededVersion(route.resources,versionsFor(route),route.observedResources);route.notice=true;notifyNotice();}
  }

  async function requestResourceRefresh(route:Route){
    if(route.confirming||(active&&active!==route.heldDraft)||retention.isPaused()||suspended||!route.focused||routes.get(route.key)!==route)return;
    updateDraft(route);
    if(consentCurrent(route)&&route.consent?.kind==='refresh'){refreshResources(route,true);return;}
    if(!updateDraft(route)?.dirty&&!route.heldDraft){refreshResources(route);return;}
    if(!ports.confirmDiscard)return;
    const capturedEpoch=epoch,revision=route.draft!.revision,documentRevision=route.documentRevision,held=route.heldDraft;
    route.confirming=true;notifyNotice();
    let accepted=false;try{accepted=await ports.confirmDiscard()===true;}catch{/* Failed confirmation retains the draft. */}
    const current=routes.get(route.key);
    if(current)current.confirming=false;
    if(accepted&&current&&epoch===capturedEpoch&&!suspended&&!retention.isPaused()&&current.focused&&current.documentRevision===documentRevision&&updateDraft(current)?.revision===revision){
      if(held&&active===held&&current.heldDraft===held){held.draftRevision=revision;held.releaseDraft?.(true);}
      else if(!active)refreshResources(current,true);
    }
    notifyNotice();
  }

  function containsBoundary(document: Document | null | undefined, route: Route): boolean {
    // XML clone operations can retain an old ownerDocument pointer. Match the
    // current boundary node inside the actual getRoot() tree, not that pointer.
    return !!document && Array.from(document.getElementsByTagNameNS(NAMESPACE, "realtime")).includes(route.element);
  }

  /** Capture actual live source ownership before any native await. */
  function bindSource(element:Element,callbacks:{getRoot:()=>Document|undefined;updateRoot:(doc:Document)=>void}){
    const document=callbacks.getRoot();
    const owners=[...routes.values()].filter(route=>containsBoundary(document,route));
    if(document?.getElementsByTagNameNS(NAMESPACE,"realtime").length!==1||owners.length!==1){reject("ambiguous-owner");return null;}
    const key=owners[0].key,ownerEpoch=epoch;
    const isAlive=()=>{
      const current=callbacks.getRoot(),route=routes.get(key);
      return ownerEpoch===epoch&&!suspended&&!!route&&containsBoundary(current,route)&&current?.getElementsByTagNameNS(NAMESPACE,"realtime").length===1&&Array.from(current.getElementsByTagName("*")).includes(element);
    };
    const sourceIsCurrent=()=>isAlive()&&!retention.isPaused()&&routes.get(key)?.focused===true;
    if(!isAlive()){reject("missing-origin",key);return null;}
    const dispatch:HvComponentOnUpdate=(...args)=>{
      if(!sourceIsCurrent()){const route=routes.get(key);reject(ownerEpoch!==epoch||suspended?"stale-owner":retention.isPaused()?"paused-owner":!route||!containsBoundary(callbacks.getRoot(),route)?"missing-owner":!route.focused?"inactive-owner":"missing-origin",key);return;}
      enqueue(key,args,"ordinary",ownerEpoch);
    };
    const authority=Object.freeze({isAlive,sourceIsCurrent,onUpdate:dispatch,effectReceipt:()=>sourceIsCurrent()?effectReceipts.get(element)??null:null,
      markDraftEdit:(field:Element)=>{
        const route=routes.get(key);
        // Native avatar selection mutates a real hidden field directly. Signal
        // before that mutation; no payload copy and no auth/ACK authority.
        if(sourceIsCurrent()&&route&&functionalField(route,field))updateDraft(route,true);
      },
      bindBiometricSubmit:()=>{
        if(!sourceIsCurrent())return null;
        const route=routes.get(key)!,current=callbacks.getRoot()!;
        const field=Array.from(current.getElementsByTagName("*")).find(node=>node.getAttribute("id")===element.getAttribute("target"));
        let form:Node|null=element;while(form?.nodeType===1&&(form as Element).localName!=="form")form=form.parentNode;
        const submit=form?.nodeType===1?Array.from((form as Element).getElementsByTagName("behavior")).filter(node=>node.getAttribute("trigger")==="on-event"&&node.getAttribute("event-name")===element.getAttribute("event-name")):[];
        if(!field||!form||!Array.from((form as Element).getElementsByTagName("*")).includes(field)||submit.length!==1)return null;
        const behavior=submit[0],href=behavior.getAttribute("href"),targetId=behavior.getAttribute("target");
        if(!href||behavior.getAttribute("verb")!=="post"||behavior.getAttribute("action")!=="replace"||targetId!=="login-panel"||classifyAuth(new URL(href,route.baseUrl).toString(),"POST",new URL(route.baseUrl).origin)!=="biometric")return null;
        let consumed=false;
        return(token:string)=>{
          if(consumed||!sourceIsCurrent()||!/^[A-Za-z0-9_-]{43}$/.test(token))return false;
          const live=callbacks.getRoot()!;
          if(![field,behavior].every(node=>Array.from(live.getElementsByTagName("*")).includes(node)))return false;
          consumed=true;field.setAttribute("value",token);callbacks.updateRoot(shallowCloneToRoot(field));
          const owned=routes.get(key),boundaries=callbacks.getRoot()?.getElementsByTagNameNS(NAMESPACE,"realtime");
          if(owned&&boundaries?.length===1)owned.element=boundaries[0];
          if(!sourceIsCurrent())return false;
          dispatch(href,"replace",behavior.parentNode as Element,{verb:"post",targetId,behaviorElement:behavior});return true;
        };
      },
    });
    sourceAuthorities.set(authority,element);
    return authority;
  }

  /** Explicit opt-in adapter for app-owned callbacks, never SDK defaults. */
  function ownBehavior(behavior: HvBehavior): HvBehavior {
    return {...behavior,callback:(element,_onUpdate,getRoot,updateRoot)=>{
      const source=bindSource(element,{getRoot,updateRoot});
      if(!source?.sourceIsCurrent())return;
      behavior.callback(element,source.onUpdate,getRoot,updateRoot);
    }};
  }

  async function deliverAuth(operation:Operation,result:AuthResult){
    if(operations.get(operation.token)!==operation||operation.epoch!==epoch||suspended)return;
    const route=routes.get(operation.key);if(!route){finish(operation,"cancelled","owner-unavailable");return;}
    if(result.kind==="held"){
      operation.authPreparing=false;operation.authHeld=true;
      const queued=operation.authDelivery;operation.authDelivery=undefined;
      if(queued){operation.authHeld=false;await deliverAuth(operation,queued);}
      return;
    }
    operation.authPreparing=false;operation.authHeld=false;operation.authDelivery=undefined;
    if(result.kind==="transition"){finish(operation,"no-document","auth-transition");return;}
    if(!await retention.wait(()=>operations.get(operation.token)===operation&&!suspended&&operation.epoch===epoch))return;
    if(result.kind==="panel"){
      try{
        const source=parseOwnedAuthPanel(result,operation.id);
        const owner=routes.get(operation.key),target=owner&&findTarget(owner.element,operation.args[2],operation.args[3]);
        if(!owner||!target){finish(operation,"cancelled","missing-target");return;}
        for(const behavior of Array.from(source.getElementsByTagName("behavior")))if(behavior.getAttribute("action")==="store-biometric-token")effectReceipts.set(behavior,result.receipt);
        indicators(operation,false);operation.result=source;operation.authReceipt=result.receipt;operation.phase="submitted";localCommits.set(source,operation);
        owner.onUpdate(null,"swap",target,{newElement:source});
        const boundaries=currentDocument(source)?.getElementsByTagNameNS(NAMESPACE,"realtime");
        if(operations.get(operation.token)===operation&&boundaries?.length===1)owner.element=boundaries[0];
        callEnd(owner,operation);
      }catch(error){finish(operation,"error","request-error",false);reportError(route,error as Error);drain();}
      return;
    }
    if(result.kind==="refused")route.noticeCode="auth-refused";
    finish(operation,result.kind==="busy"?"dropped":"no-document",result.kind==="refused"?"auth-refused":result.kind==="busy"?"auth-busy":"auth-uncertain",false);
    callEnd(route,operation);drain();
  }

  function Boundary({ element, stylesheets, onUpdate, options }: HvComponentProps) {
    const { key } = useRoute();
    const navigation = useNavigation<NavigationHandle>();
    const focused = useIsFocused();
    const runtime = useContext(RuntimeContext);
    useSyncExternalStore(subscribeNotice,noticeSnapshot,noticeSnapshot);
    const boundaryEpoch=epoch;
    useLayoutEffect(() => {
      const previous = routes.get(key);
      if(previous?.focused&&!focused)interactionLease=Object.freeze({});
      let hasReady=previous?.ready??false;
      let observedResources=previous?.observedResources??{tasks:0,categories:0,ui:0};
      let documentCommitted=false;
      let contextual=previous?.contextual??false;
      const acknowledged:Operation[]=[];
      for (const node of [element,...Array.from(element.getElementsByTagName("*"))]) {
        const local = localCommits.get(node);
        if (local && local.key===key && local.epoch===epoch && local.result===node&&!retention.isPaused()) finish(local,"ack",local.authReceipt?"auth-panel-layout":"local-layout",false);
      }
      const pages = new Set<number>();
      let observed = routes.get(key)?.observed ?? version;
      let baseUrl = routes.get(key)?.baseUrl ?? "";
      for (const marker of Array.from(element.getElementsByTagNameNS(NAMESPACE, "realtime-page"))) {
        const page = Number(marker.getAttribute("page"));
        if (Number.isInteger(page) && page >= 1) pages.add(page);
        const requestId = marker.getAttribute("request-id") ?? "";
        const request = pending.get(requestId);
        if (request?.epoch !== epoch) continue;
        hasReady=true;
        if(retention.isPaused())continue;
        const operation = request.operation;
        if (operation?.document && operation.document!==currentDocument(element)) continue;
        if (operation && (operation.key !== key || operation.epoch !== epoch || operations.get(operation.token) !== operation)) continue;
        if (!routes.has(key)) observed = Math.min(observed, request.version);
        if (!operation || operation.args[1]==="reload"){baseUrl=request.url;observedResources=request.resources;documentCommitted=true;contextual=request.contextual===true;}
        pending.delete(requestId);
        if (operation) {
          if (operation.kind === "refresh" || operation.args[1]==="reload") observed = operation.version;
          finish(operation,"ack",operation.args[1]==="reload"?"reload-layout":"remote-layout",false);
          acknowledged.push(operation);
        }
      }
      const mode=element.getAttribute('mode')??'notice';
      const draftSnapshot=tracksDraft(mode)?captureDraft(element,options.componentRegistry):null;
      const savedDraft=acknowledged.some(operation=>operation.draftCommit&&previous?.draft?.revision===operation.draftCommit.revision&&draftSnapshot===operation.draftCommit.after);
      const consent=documentCommitted?undefined:previous?.consent;
      routes.set(key, {
        key, focused, element, onUpdate, observed, baseUrl, runtime, options, navigation, failedVersion:previous?.failedVersion,ready:hasReady,noticeCode:previous?.noticeCode,
        resources:dependencies(element),observedResources,resourceFailure:previous?.resourceFailure,contextual,
        concealed:!!consent||(neededVersion(dependencies(element),resourceVersions,observedResources)>0&&(previous?.concealed??false)),consent,
        feedbackVersions:previous?.feedbackVersions??{tasks:0,categories:0,ui:0},
        dismissedNotice:previous?.dismissedNotice,
        draft:tracksDraft(mode)?trackDraft(previous?.draft,draftSnapshot,documentCommitted||savedDraft):undefined,
        formVersions:previous?.mode===mode?previous.formVersions:resourceVersions,
        formChanges:previous?.mode===mode?previous.formChanges:changedResourceVersions,
        documentRevision:(previous?.documentRevision??0)+(documentCommitted?1:0),confirming:previous?.confirming,heldDraft:previous?.heldDraft,
        pages: [...pages].sort((a, b) => a - b),
        refreshHref: element.getAttribute("refresh-href") ?? "",
        target: element.getAttribute("target") ?? "",
        mode,
        notice: observed < version || previous?.failedVersion === version || neededVersion(dependencies(element),resourceVersions,observedResources)>0,
      });
      ready(routes.get(key)!);
      if(focused&&!retention.isPaused()&&!suspended&&acknowledged.some(operation=>operation.remoteFeedback)&&neededVersion(dependencies(element),versionsFor(routes.get(key)!),observedResources)===0){
        try{ports.onResourceUpdated?.();}catch{/* Feedback cannot change a genuine ACK. */}
      }
      if (!focused) cancelOwner(key, true);
      drain();
    }, [element, focused, key, onUpdate, runtime, options,navigation]);
    useLayoutEffect(() => () => {
      routes.delete(key);
      cancelOwner(key);
      drain();
    }, [key]);
    const dispatch: HvComponentOnUpdate = (...args) => enqueue(key, args, "ordinary", boundaryEpoch);
    const route=routes.get(key),labels=readNoticeLabels(ports.noticeLabels);
    const concealed=route&&(!!consentCurrent(route)||(automatic(route)&&!route.draft?.dirty&&(route.concealed||(!route.focused&&neededVersion(route.resources,versionsFor(route),route.observedResources)>0))));
    const remoteChange=route&&neededVersion(route.resources,changesFor(route),route.observedResources)>0;
    const warningKey=route?[neededVersion(route.resources,changesFor(route),route.observedResources),route.heldDraft?.token,route.noticeCode,route.failedVersion,route.observed<version?version:''].join(':'):'';
    const autoPending=route&&automatic(route)&&!route.draft?.dirty&&route.resourceFailure!==neededVersion(route.resources,versionsFor(route),route.observedResources);
    const visible=route&&(route.notice||route.heldDraft)&&focused&&labels&&(route.heldDraft||route.noticeCode||route.failedVersion===version||route.observed<version||(remoteChange&&!autoPending));
    const resyncOnly=route&&neededVersion(route.resources,versionsFor(route),route.observedResources)>0&&neededVersion(route.resources,changesFor(route),route.observedResources)===0;
    const message=route?.noticeCode==="auth-refused"?labels?.csrf:route?.heldDraft?(labels?.newerEdits??labels?.changed):route?.failedVersion===version?labels?.error:resyncOnly?labels?.resync:labels?.changed;
    const conflict=route&&labels?.conflict&&focused&&!retention.isPaused()&&!suspended&&!consentCurrent(route)&&!route.noticeCode&&route.failedVersion!==version&&remoteConflict(route);
    const resolvingNotice=route&&consentCurrent(route)&&!route.heldDraft&&!route.noticeCode&&route.failedVersion!==version;
    const choices=conflict?conflictChoices(route):null;
    const LoadingScreen=runtime?.loadingScreen;
    const loading=concealed&&focused&&(route.failedVersion===undefined||(active?.key===key&&active.epoch===boundaryEpoch&&active.args[1]==='reload'));
    return <>
      {choices&&labels?.conflict?<RealtimeConflictDialog message={labels.conflict.messages[formObjectKind(route!.element)]} goBack={labels.conflict.goBack} backUnavailable={labels.conflict.backUnavailable} update={labels.update} pending={conflictBusy(route!)} {...choices}/>:null}
      {!conflict&&!resolvingNotice&&visible&&message&&route.dismissedNotice!==warningKey?<RealtimeNotice message={message} actionLabel={labels.update} pending={retention.isPaused()||suspended||(!!active&&active!==route.heldDraft)||route.confirming===true} onAction={route.noticeCode==="auth-refused"?undefined:()=>{if(epoch===boundaryEpoch&&routes.get(key)===route)void requestResourceRefresh(route);}} dismissLabel={labels.dismiss} onDismiss={()=>{const current=routes.get(key);if(current&&epoch===boundaryEpoch){current.dismissedNotice=warningKey;notifyNotice();}}}/>:null}
      <View style={{flex:1}} testID="realtime-content">
        <View style={{flex:1,opacity:concealed?0:1}} pointerEvents={concealed||conflict?'none':'auto'} accessibilityElementsHidden={!!(concealed||conflict)} importantForAccessibility={concealed||conflict?'no-hide-descendants':'auto'}>{renderChildren(element, stylesheets, dispatch, options)}</View>
        {/* Fill the retained content area without giving the hidden tree a new identity. */}
        {loading?<View style={StyleSheet.absoluteFill} testID="realtime-loading-overlay">
          {LoadingScreen?<LoadingScreen element={element}/>:<View style={{flex:1,alignItems:'center',justifyContent:'center'}}><ActivityIndicator/></View>}
        </View>:null}
      </View>
    </>;
  }

  const components = [
    Object.assign(Boundary, { localName: "realtime", namespaceURI: NAMESPACE }),
    Object.assign(() => null, { localName: "realtime-page", namespaceURI: NAMESPACE }),
  ];

  function wrapFetch(transport: FetchImplementation): FetchImplementation {
    return async (input, init = {}) => {
      // A retained callback can outlive the mounted Root during login/logout.
      // Deny admission before transport, request IDs or pending state exist.
      if (suspended) throw new Error("Realtime authentication is suspended");
      const requestEpoch = epoch;
      const hosted = Object.prototype.hasOwnProperty.call(init, ROOT_PROVENANCE);
      const {[ROOT_PROVENANCE]:provenance,[DOCUMENT_PROVENANCE]:documentProvenance, ...transportInit} = init as RootRequestInit;
      if (hosted && (!provenance || typeof provenance !== "object" || !activeRoots.has(provenance) || provenance.instance !== instance || provenance.epoch !== epoch)) throw new Error("Invalid realtime root provenance");
      const inputUrl = typeof input === "string" ? input : input instanceof URL ? input.toString() : input.url;
      const parsed = readOperationUrl(inputUrl);
      if(documentProvenance && (!documentRequests.has(documentProvenance)||documentProvenance.instance!==instance||documentProvenance.epoch!==epoch||documentProvenance.url!==inputUrl))throw new Error("invalid-document-operation");
      const operation = documentProvenance?.operation ?? (parsed.token ? operations.get(parsed.token) : undefined);
      if(documentProvenance && (!operation||operations.get(operation.token)!==operation||operation.id))throw new Error("unknown-document-operation");
      if (parsed.token && (!operation || operation.epoch !== epoch || operation.id)) throw new Error("unknown-operation");
      if (operation && (operation !== active || !routes.has(operation.key) || (operation.kind === "refresh" && !routes.get(operation.key)?.focused) || (!documentProvenance && parsed.prefix !== operation.canonicalUrl) || (init.method ?? "get").toLowerCase() !== operation.method)) throw new Error("operation-owner-mismatch");
      if(retention.isPaused()&&!operation)throw new Error("Paused realtime root");
      if (hasReservedBody(init.body)) {
        if (operation) {reject("reserved-parameter", operation.key);retire(operation);drain();}
        throw new Error("reserved-parameter");
      }
      try { sequence = nextCounter(sequence); }
      catch { throw new Error("attempt-counter"); }
      const requestId = `gate-${instance}-${epoch}-${sequence}`;
      pending.set(requestId, {epoch, version, url:parsed.canonicalUrl, operation,resources:resourceVersions});
      if (operation) operation.id = requestId;
      const assertCurrent = () => {
        if (epoch !== requestEpoch) throw new Error("Stale realtime epoch");
        if (operation && operations.get(operation.token) !== operation) throw new Error("Cancelled realtime operation");
      };
      const headers = new Headers(init.headers);
      headers.set(REQUEST_HEADER, requestId);
      headers.delete(CHANGE_HEADERS.mutation);
      if(operation&&operation.method==='post'&&!operation.local&&!classifyAuth(parsed.canonicalUrl,operation.method,new URL(parsed.canonicalUrl).origin)){
        try{const mutationId=ports.admitMutation?.(operation);if(mutationId&&/^[a-f0-9]{40}$/.test(mutationId))headers.set(CHANGE_HEADERS.mutation,mutationId);}catch{/* Unknown origin never blocks HTTP. */}
      }
      try {
        const prepared={...transportInit,headers};
        if(operation&&ports.authenticate&&classifyAuth(parsed.canonicalUrl,operation.method,new URL(parsed.canonicalUrl).origin)){
          operation.authPreparing=true;
          const resume=(result:AuthResult)=>{
            if(result.kind==="held"||operation.authDelivered||(!operation.authPreparing&&!operation.authHeld)||operations.get(operation.token)!==operation||operation.epoch!==epoch||suspended)return false;
            operation.authDelivered=true;
            // Foreground may settle before Parser propagates our private held
            // signal. Buffer one result, never invent a Response or early ACK.
            if(operation.authPreparing)operation.authDelivery=result;
            else{operation.authHeld=false;void deliverAuth(operation,result);}
            return true;
          };
          const result=await ports.authenticate(parsed.canonicalUrl,prepared,resume);
          const signal=Object.freeze({});authSignals.set(signal,{operation,result});throw signal;
        }
        const response = await transport(parsed.token ? parsed.canonicalUrl : input, prepared);
        assertCurrent();
        const request=pending.get(requestId);if(request)request.contextual=response.headers.get(CHANGE_HEADERS.features)==='changes-v2';
        if(operation)operation.responseStatus=response.status;
        if (operation && (response.status === 204 || response.status === 205)) throw new NoDocument();
        // Parser reads the body later. A headers-only epoch check lets a
        // logout during response.text() expose the previous session's document.
        return new Proxy(response, {
          get(target, property) {
            if (property === "text") {
              return async () => {
                try {
                  if(!await retention.wait(()=>epoch===requestEpoch&&!suspended&&(!operation||operations.get(operation.token)===operation)))throw new Error("Stale retained response");
                  const text = await target.text();
                  if(!await retention.wait(()=>epoch===requestEpoch&&!suspended&&(!operation||operations.get(operation.token)===operation)))throw new Error("Stale retained response");
                  assertCurrent();
                  if (operation && !text.trim()) throw new NoDocument();
                  return text;
                } catch (error) {
                  pending.delete(requestId);
                  if (operation) { /* The owned parser catch retires this exact attempt. */ }
                  else if (!operation && !hosted && epoch === requestEpoch) blocked = true;
                  throw error;
                }
              };
            }
            const value = Reflect.get(target, property, target);
            return typeof value === "function" ? value.bind(target) : value;
          },
        });
      } catch (error) {
        pending.delete(requestId);
        if (operation) { /* The owned parser catch retires this exact attempt. */ }
        else if (!operation && !hosted && epoch === requestEpoch) blocked = true;
        throw error;
      }
    };
  }

  return {
    Root,
    components,
    wrapFetch,
    ownBehavior,
    bindSource,
    isSettingsClear:(element:Element,source:{sourceIsCurrent():boolean})=>sourceAuthorities.get(source)===element&&settingsClears.has(element)&&source.sourceIsCurrent(),
    setRetainedPaused:(ownedEpoch:number,paused:boolean)=>{
      if(ownedEpoch!==epoch||suspended)return false;
      retention.set(paused);
      if(paused)interactionLease=Object.freeze({});
      notifyNotice();
      if(!paused){for(const route of routes.values()){route.options.onUpdateCallbacks?.setState({});ready(route);}drain();}
      return true;
    },
    snapshot: () => ({
      pending: pending.size, queued: queue.filter(operation => operations.has(operation.token)).length, operations: operations.size, lastRejection, lastTerminal, blocked, suspended, epoch,retainedPaused:retention.isPaused(),
      routes: [...routes.values()].map(({ key, focused, pages, refreshHref, notice,noticeCode }) => ({ key, focused, pages, refreshHref, notice,noticeCode })),
    }),
    invalidateResources:(capturedEpoch:number,resources:readonly ResourceName[],cause:"invalidate"|"resync"|"local"="invalidate",change?:ResourceChange):boolean=>{
      const names=parseResources(resources);
      if(capturedEpoch!==epoch||suspended||!names||!["invalidate","resync","local"].includes(cause)||!readNoticeLabels(ports.noticeLabels))return false;
      if(resourceSequence>=Number.MAX_SAFE_INTEGER)return false;
      resourceSequence+=1;resourceVersions={...resourceVersions,...Object.fromEntries(names.map(name=>[name,resourceSequence]))};
      // Reconciliation cannot erase a still-unacknowledged real invalidation.
      if(cause==="invalidate")changedResourceVersions={...changedResourceVersions,...Object.fromEntries(names.map(name=>[name,resourceSequence]))};
      if(cause==='invalidate')for(const route of routes.values())if(route.focused&&!route.concealed&&!retention.isPaused()){
        route.feedbackVersions={...route.feedbackVersions,...Object.fromEntries(names.filter(name=>route.resources.includes(name)).map(name=>[name,resourceSequence]))};
      }
      for(const route of routes.values())if(route.mode==='form'&&(cause==='resync'||affectsForm(route.element,names,change))){
        route.formVersions={...route.formVersions,...Object.fromEntries(names.map(name=>[name,resourceSequence]))};
        if(cause==='invalidate')route.formChanges={...route.formChanges,...Object.fromEntries(names.map(name=>[name,resourceSequence]))};
      }
      drain();return true;
    },
    invalidate: () => {
      version += 1;
      for (const route of routes.values()) route.notice = true;
      drain();
    },
    resetEpoch: () => {
      // Revoke before allocation: exhaustion must not revive a consumed epoch.
      resumableEpoch = null;
      pending.clear();
      for (const operation of operations.values()) retire(operation);
      operations.clear();
      queue.length = 0;
      active = undefined;
      blocked = true;
      suspended = true;
      routes.clear();
      resourceSequence=0;resourceVersions={tasks:0,categories:0,ui:0};
      changedResourceVersions={tasks:0,categories:0,ui:0};
      retention.wake();readyEpoch=undefined;
      try {
        epoch = nextCounter(epoch);
        resumableEpoch = epoch;
      } finally { notifyRoot(); }
      return epoch;
    },
    /** Resume only after the caller confirms authentication for this token. */
    resumeEpoch: (token: number): boolean => {
      if (token !== epoch || token !== resumableEpoch || !suspended) return false;
      resumableEpoch = null;
      suspended = false;
      blocked = false;
      notifyRoot();
      return true;
    },
  };
}
