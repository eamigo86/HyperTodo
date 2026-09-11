import 'react-native-gesture-handler/jestSetup';
import React from 'react';
import {act,fireEvent,render,waitFor,within} from '@testing-library/react-native';
import {Alert,AppState,Text} from 'react-native';
import {createSessionApp} from '../App';
import {AppSessionSurface,type AppSessionOptions} from '../src/realtime/app-session';
import RealtimeConflictDialog from '../src/components/RealtimeConflictDialog';
import {createThemeStore} from '../src/theme';
import {SESSION_HEADERS as H} from '../src/realtime/session-protocol';
import type {HvComponentProps} from 'hyperview';

jest.mock('expo-splash-screen',()=>({preventAutoHideAsync:jest.fn(),hideAsync:jest.fn()}));
jest.mock('lottie-react-native',()=>{
 const React=jest.requireActual('react'),{View}=jest.requireActual('react-native');
 return {__esModule:true,default:React.forwardRef((props:any,ref:any)=>{React.useImperativeHandle(ref,()=>({play:()=>props.onAnimationFinish?.(false)}));return <View {...props}/>;})};
});
jest.mock('react-native-safe-area-context',()=>jest.requireActual('react-native-safe-area-context/jest/mock').default);
jest.mock('react-native-webview',()=>({WebView:()=>null}));
jest.mock('expo-secure-store',()=>({getItem:()=>null,setItem:()=>{}}));
const originalState=AppState.currentState;
beforeEach(()=>{AppState.currentState='active';});afterEach(()=>{AppState.currentState=originalState;});
const ORIGIN='https://app.test',ENTRY=ORIGIN+'/hv/',PREVIOUS=ORIGIN+'/hv/about/',HV='https://hyperview.org/hyperview',APP='https://hypertodo.app/components',BINDING='hvs1.'+'A'.repeat(43);

function fixture({language='en',noHistory=false,previousDraft=false,previousTracked=true,settings=false,dirty=true,object='task',safePost=false}={}){
 const kind=settings?'settings':object,screenId=kind==='settings'?'settings-screen':kind==='category'?'category-form-screen':kind==='unknown'?'unknown-screen':'task-form-screen';
 const formUrl=ORIGIN+(kind==='settings'?'/hv/settings/':kind==='category'?'/hv/categories/x/edit/':'/hv/tasks/x/edit/'),panel=kind==='settings'?'settings-form-panel':kind==='category'?'category-form-panel':'task-form-panel',resource=kind==='settings'?'ui':kind==='category'?'categories':'tasks';
 let homeLoads=0,formLoads=0,seed=0,closed=false,control!:ReadableStreamDefaultController<Uint8Array>;
 const holds=new Set<string>(),pending=new Map<string,{resolve():void;reject(error:Error):void}>();
 const events:any[]=[],notice=jest.fn(),clear=jest.fn(async()=>{}),save=jest.fn(async()=>{}),streamCancel=jest.fn();
 const reply=(body:BodyInit|null,url:string,type='application/vnd.hyperview+xml')=>{
  const response=new Response(body,{headers:{[H.binding]:BINDING,'Content-Type':type,'Content-Language':language,'X-HyperTodo-Realtime-Features':'changes-v2','X-HyperTodo-Mutation-Seed':(++seed).toString(16).padStart(32,'0')}});
  Object.defineProperty(response,'url',{value:url});return response;
 };
 const marker=(id:string)=>`<app:realtime-page request-id="${id}" page="1"/>`;
 const formPanel=(id:string)=>`<view id="${panel}">${marker(id)}<form><text-field name="title" placeholder="Title" value="Saved ${formLoads}"/><text-field hide="true" name="csrfmiddlewaretoken" value="synthetic-csrf"/><view action="replace" verb="post" href="${formUrl}" target="${panel}"><text>Save form</text></view></form><view action="navigate" href="${ORIGIN}/hv/other/"><text>Open other</text></view></view>`;
 const entityKey='1'.repeat(64),entityEpoch='a'.repeat(16);
 const doc=(id:string,form:boolean)=>`<doc xmlns="${HV}" xmlns:app="${APP}"><screen id="${form?screenId:'previous-screen'}"><body><app:realtime resources="${form?resource:'ui'}" mode="${form||previousDraft?'form':'readonly'}" refresh-href="${form?formUrl:PREVIOUS}" target="${form?(kind==='mismatch'?'category-form-screen':screenId):'previous'}"${form?` entities="${JSON.stringify({epoch:entityEpoch,items:[{resource,key:entityKey}]}).replaceAll('"','&quot;')}"`:''}>${form?formPanel(id):`<view id="previous">${marker(id)}<text>Previous ${homeLoads}</text>${previousDraft?'<form><text-field name="previous-draft" placeholder="Previous draft" value="initial"/></form>':''}<view action="navigate" href="${formUrl}"><text>Open form</text></view></view>`}</app:realtime></body></screen></doc>`;
 const http=jest.fn(async(input:RequestInfo|URL,init?:RequestInit)=>{
  const url=String(input),id=new Headers(init?.headers).get('X-HyperTodo-Request-ID')!,post=init?.method?.toUpperCase()==='POST';
  if(url.endsWith('/session-state/'))return reply(JSON.stringify({version:1,authenticated:true,binding:BINDING}),url,'application/json');
  if(url===ENTRY)return reply(`<doc xmlns="${HV}"><navigator id="root" type="stack"><nav-route id="home" href="${noHistory?formUrl:PREVIOUS}"/></navigator></doc>`,url);
  let body:string;
  if(post)body=safePost?formPanel(id).replace('<view id=',`<view xmlns="${HV}" xmlns:app="${APP}" id=`):`<view xmlns="${HV}" xmlns:app="${APP}" id="${panel}">${marker(id)}<behavior trigger="load" action="store-biometric-token" token="" once="true" immediate="true"/><behavior trigger="load" action="show-snackbar" message="Old POST delivered" tone="success" once="true"/><behavior trigger="load" action="back" once="true"/><text>Held server response</text></view>`;
  else{if(url===formUrl)formLoads++;else homeLoads++;body=doc(id,url===formUrl);if(url===PREVIOUS&&!previousTracked)body=body.replace('mode="form"','mode="notice"');if(url===ORIGIN+'/hv/other/')body=body.replace('</app:realtime>','<view action="back"><text>Return to form</text></view></app:realtime>');}
  const response=reply(body,url),key=post?'post':url;
  if(holds.delete(key)){const text=response.text.bind(response);response.text=async()=>{await new Promise<void>((resolve,reject)=>pending.set(key,{resolve,reject}));pending.delete(key);return text();};}
  return response;
 });
 const streamFetch=jest.fn(async()=>{
  const {ReadableStream}=jest.requireActual('node:stream/web');
  return reply(new ReadableStream({start:(value:typeof control)=>{control=value;},cancel:streamCancel}),ORIGIN+'/realtime/events/','text/event-stream');
 });
 const options:AppSessionOptions={entrypointUrl:ENTRY,http,credentials:{read:async()=>null,storage:{enqueue:async(job:any)=>job({save,clear})}},
  native:{platform:'ios',hasHardware:async()=>false,isEnrolled:async()=>false,supportedTypes:async()=>[],readToken:async()=>null,unlock:async()=>({success:false}),pick:async()=>({canceled:true}),render:jest.fn(),save:jest.fn()},
  onTheme:()=>{},onNotice:notice,stopStream:jest.fn(),onGateObservation:event=>events.push(event),stream:{fetch:streamFetch}};
 const App=createSessionApp(options,createThemeStore({read:()=>language==='es'?'dark':'light',write:()=>{}})),ui=render(<App/>);
 fireEvent(ui.getByTestId('animated-splash'),'layout');const session=ui.UNSAFE_getByType(AppSessionSurface).props.session as ReturnType<typeof import('../src/realtime/app-session').createAppSession>;
 const remote=(names=[resource])=>control.enqueue(new TextEncoder().encode(`event: invalidate\ndata: ${JSON.stringify({version:2,resources:names,mutation_id:null,entities:null})}\n\n`));
 return{ui,session,http,events,notice,clear,save,streamFetch,formUrl,remote,
  resync:()=>control.enqueue(new TextEncoder().encode('event: resync\ndata: {"version":1}\n\n')),
  precise:(key=entityKey,mutationId:string|null=null)=>control.enqueue(new TextEncoder().encode(`event: invalidate\ndata: ${JSON.stringify({version:2,resources:[resource],mutation_id:mutationId,entities:{epoch:entityEpoch,items:[{resource,key}]}})}\n\n`)),
  edit:async()=>{if(!noHistory){await ui.findByText('Previous 1');if(previousDraft)fireEvent.changeText(ui.getByPlaceholderText('Previous draft'),'do not discard me');fireEvent.press(ui.getByText('Open form'));}await ui.findByPlaceholderText('Title');await waitFor(()=>expect(streamFetch).toHaveBeenCalledTimes(1));if(dirty)fireEvent.changeText(ui.getByPlaceholderText('Title'),'local draft');},
  hold:(key=formUrl)=>holds.add(key),waiting:(key=formUrl)=>pending.has(key),release:(key=formUrl)=>pending.get(key)?.resolve(),fail:(key=formUrl)=>pending.get(key)?.reject(new Error('Controlled reload failure')),
  counts:()=>({home:homeLoads,form:formLoads}),close:()=>{if(!closed){closed=true;ui.unmount();}}};
}

it.each([{language:'en',dirty:true},{language:'es',dirty:true},{language:'en',dirty:false},{language:'es',dirty:false}])('uses the same concise two-choice modal and fresh GET for open forms: %j',async({language,dirty})=>{
 const f=fixture({language,dirty}),alert=jest.spyOn(Alert,'alert').mockImplementation(()=>{});
 try{
  await f.edit();const root=f.ui.UNSAFE_getByType(f.session.gate.Root),epoch=f.session.gate.snapshot().epoch;
  act(()=>{f.remote();f.remote();});await f.ui.findByTestId('realtime-conflict-card');
  const dialog=f.ui.UNSAFE_getByType(RealtimeConflictDialog),card=within(f.ui.getByTestId('realtime-conflict-card'));
  expect(f.ui.UNSAFE_getAllByType(RealtimeConflictDialog)).toHaveLength(1);expect(card.getAllByRole('button')).toHaveLength(2);
  expect(dialog.findAllByType(Text)).toHaveLength(3); // One sentence and the two button labels.
  expect(dialog.props.message).toBe(language==='es'?'Los datos de esta tarea se modificaron de forma remota.':'This task was updated remotely.');expect(f.ui.queryByTestId('realtime-notice')).toBeNull();
  const update=language==='es'?'Actualizar':'Update',back=language==='es'?'Volver':'Go back';expect(card.getByRole('button',{name:back})).not.toBeDisabled();
  f.hold();const callback=dialog.props.onUpdate;fireEvent.press(card.getByRole('button',{name:update}));act(()=>callback());
  await waitFor(()=>expect(f.waiting()).toBe(true));expect(f.counts().form).toBe(2);expect(f.ui.queryByTestId('realtime-conflict-card')).toBeNull();
  expect(f.ui.getByPlaceholderText('Title',{includeHiddenElements:true}).props.value).toBe(dirty?'local draft':'Saved 1');expect(f.ui.queryByPlaceholderText('Title')).toBeNull();expect(f.ui.getByLabelText('Loading HyperTodo')).toBeTruthy();
  expect(f.events.filter(event=>event.reason==='reload-layout')).toHaveLength(0);expect(alert).not.toHaveBeenCalled();
  await act(async()=>f.release());await waitFor(()=>expect(f.ui.getByPlaceholderText('Title').props.value).toBe('Saved 2'));
  expect(f.events.at(-1)).toMatchObject({outcome:'ack',reason:'reload-layout'});expect(f.session.gate.snapshot().epoch).toBe(epoch);expect(f.ui.UNSAFE_getByType(f.session.gate.Root)).toBe(root);expect(f.notice).not.toHaveBeenCalled();
  expect(f.http.mock.calls.filter(([,init])=>init?.method?.toUpperCase()==='POST')).toHaveLength(0);
 }finally{f.close();alert.mockRestore();}
});

it.each([
 {object:'category',en:'This category was updated remotely.',es:'Los datos de esta categoría se modificaron de forma remota.'},
 {object:'settings',en:'These settings were updated remotely.',es:'Esta configuración se modificó de forma remota.'},
 {object:'unknown',en:'This form was updated remotely.',es:'Los datos de este formulario se modificaron de forma remota.'},
 {object:'mismatch',en:'This form was updated remotely.',es:'Los datos de este formulario se modificaron de forma remota.'},
])('names only the declared form kind, with a generic fallback: $object',async({object,en,es})=>{
 for(const language of ['en','es']){
  const f=fixture({object,language,dirty:false});
  try{await f.edit();act(()=>f.remote());await f.ui.findByTestId('realtime-conflict-card');expect(f.ui.UNSAFE_getByType(RealtimeConflictDialog).props.message).toBe(language==='en'?en:es);expect(f.ui.queryByTestId('realtime-notice')).toBeNull();}finally{f.close();}
 }
});

it.each([false,true])('shows only the branded loader while resolving the accepted conflict before its actual layout ACK (dirty=%s)',async dirty=>{
 const f=fixture({dirty});let restore:(()=>void)|undefined;
 try{
  await f.edit();const boundary=f.ui.UNSAFE_getAllByType(f.session.gate.components[0]).find(node=>node.props.element.getAttribute('refresh-href')===f.formUrl)!;
  const callbacks=boundary.props.options.onUpdateCallbacks as NonNullable<HvComponentProps['options']['onUpdateCallbacks']>,setState=callbacks.setState;
  let deliver:(()=>void)|undefined;
  // Delay only the SDK's public screen-state delivery. Its real parsed document
  // and later Boundary layout remain the sole acknowledgment authority.
  const pendingLayout=jest.spyOn(callbacks,'setState').mockImplementation(state=>{
   if(state.doc&&state.doc!==callbacks.getState().doc)deliver=()=>setState(state);else setState(state);
  });restore=()=>pendingLayout.mockRestore();
  act(()=>f.remote());await f.ui.findByTestId('realtime-conflict-card');f.hold();fireEvent.press(f.ui.getByRole('button',{name:'Update'}));
  await waitFor(()=>expect(f.waiting()).toBe(true));
  const resolving=()=>{
   expect(f.ui.queryByTestId('realtime-conflict-card')).toBeNull();expect(f.ui.queryByTestId('realtime-notice')).toBeNull();expect(f.ui.queryByText('There may be changes')).toBeNull();
   expect(f.ui.getByLabelText('Loading HyperTodo')).toBeTruthy();expect(f.ui.queryByPlaceholderText('Title')).toBeNull();expect(f.ui.getByPlaceholderText('Title',{includeHiddenElements:true}).props.value).toBe(dirty?'local draft':'Saved 1');
   expect(f.events.filter(event=>event.reason==='reload-layout')).toHaveLength(0);
  };
  resolving();await act(async()=>f.release());await waitFor(()=>expect(deliver).toEqual(expect.any(Function)));resolving();
  restore();await act(async()=>deliver!());await waitFor(()=>expect(f.ui.getByPlaceholderText('Title').props.value).toBe('Saved 2'));
  expect(f.ui.queryByTestId('realtime-notice')).toBeNull();expect(f.ui.queryByLabelText('Loading HyperTodo')).toBeNull();expect(f.events.filter(event=>event.reason==='reload-layout')).toHaveLength(1);expect(f.notice).not.toHaveBeenCalled();
 }finally{restore?.();f.close();}
});

it.each([false,true])('keeps resync, a different entity and this operation quiet on an open form (dirty=%s)',async dirty=>{
 const f=fixture({dirty,safePost:true});
 try{await f.edit();await act(async()=>{f.resync();f.precise('2'.repeat(64));});expect(f.ui.queryByTestId('realtime-conflict-card')).toBeNull();expect(f.ui.queryByTestId('realtime-notice')).toBeNull();expect(f.notice).not.toHaveBeenCalled();
  fireEvent.press(f.ui.getByText('Save form'));await waitFor(()=>expect(f.events.some(event=>event.reason==='remote-layout')).toBe(true));
  const post=f.http.mock.calls.find(([,init])=>init?.method?.toUpperCase()==='POST')!;const mutationId=new Headers(post[1]?.headers).get('X-HyperTodo-Mutation-ID');expect(mutationId).toMatch(/^[a-f0-9]{40}$/);
  await act(async()=>f.precise('1'.repeat(64),mutationId));expect(f.ui.queryByTestId('realtime-conflict-card')).toBeNull();expect(f.ui.queryByTestId('realtime-notice')).toBeNull();expect(f.notice).not.toHaveBeenCalled();
  act(()=>f.precise());await f.ui.findByTestId('realtime-conflict-card');expect(f.http.mock.calls.filter(([,init])=>init?.method?.toUpperCase()==='POST')).toHaveLength(1);
 }finally{f.close();}
});

it.each([false,true])('Go back refreshes only the exact clean predecessor even when its resource versions were already current (dirty=%s)',async dirty=>{
 const f=fixture({dirty});
 try{
  await f.edit();const previous=f.session.gate.snapshot().routes.find(route=>route.refreshHref===PREVIOUS)!.key;
  act(()=>f.remote());await f.ui.findByTestId('realtime-conflict-card');f.hold(PREVIOUS);
  const back=f.ui.UNSAFE_getByType(RealtimeConflictDialog).props.onGoBack;act(()=>{back();back();});
  await waitFor(()=>expect(f.waiting(PREVIOUS)).toBe(true));expect(f.counts()).toEqual({home:2,form:1});
  expect(f.ui.queryByText('Previous 1')).toBeNull();expect(f.ui.getByLabelText('Loading HyperTodo')).toBeTruthy();
  expect(f.ui.queryByTestId('realtime-notice')).toBeNull();expect(f.ui.queryByText('There may be changes')).toBeNull();
  expect(f.session.gate.snapshot().routes.find(route=>route.focused)?.key).toBe(previous);
  await act(async()=>f.release(PREVIOUS));await f.ui.findByText('Previous 2');expect(f.ui.queryByPlaceholderText('Title')).toBeNull();
  expect(f.events.at(-1)).toMatchObject({outcome:'ack',reason:'reload-layout',routeKey:previous});expect(f.notice).not.toHaveBeenCalled();expect(f.streamFetch).toHaveBeenCalledTimes(1);
 }finally{f.close();}
});

it.each([{noHistory:true},{previousDraft:true},{previousDraft:true,previousTracked:false}])('does not guess history or discard another form: %j',async options=>{
 const f=fixture(options);
 try{await f.edit();act(()=>f.remote());await f.ui.findByTestId('realtime-conflict-card');const modal=f.ui.UNSAFE_getByType(RealtimeConflictDialog);expect(modal.props.canGoBack).toBe(false);expect(f.ui.getByRole('button',{name:'Go back'})).toBeDisabled();expect(f.ui.getByRole('button',{name:'Update'})).not.toBeDisabled();act(()=>modal.props.onGoBack());expect(f.counts().form).toBe(1);if(options.previousDraft)expect(f.ui.getByPlaceholderText('Previous draft',{includeHiddenElements:true}).props.value).toBe('do not discard me');}finally{f.close();}
});

it('revokes a captured choice across blur and return to the same form identity',async()=>{
 const f=fixture();
 try{await f.edit();let source=f.ui.getByText('Open other');while(!source.props.onPress&&source.parent)source=source.parent;const navigate=source.props.onPress;expect(navigate).toEqual(expect.any(Function));
  act(()=>f.remote());await f.ui.findByTestId('realtime-conflict-card');const old=f.ui.UNSAFE_getByType(RealtimeConflictDialog).props.onUpdate;
  act(()=>navigate());await f.ui.findByText('Return to form');expect(f.ui.queryByTestId('realtime-conflict-card')).toBeNull();await act(async()=>old());expect(f.counts().form).toBe(1);
  fireEvent.press(f.ui.getByText('Return to form'));await f.ui.findByTestId('realtime-conflict-card');await act(async()=>old());expect(f.counts().form).toBe(1);
  fireEvent.press(f.ui.getByRole('button',{name:'Update'}));await waitFor(()=>expect(f.ui.getByPlaceholderText('Title').props.value).toBe('Saved 2'));
 }finally{f.close();}
});

it.each(['pause','invalidate','unmount'] as const)('revokes modal and captured choices on %s without discarding or requesting',async outcome=>{
 const f=fixture();
 try{await f.edit();act(()=>f.remote());await f.ui.findByTestId('realtime-conflict-card');const callbacks=f.ui.UNSAFE_getByType(RealtimeConflictDialog).props,count=f.http.mock.calls.length;
  act(()=>{if(outcome==='pause')f.session.pause();else if(outcome==='invalidate')f.session.supervisor.invalidate();else f.close();});
  if(outcome==='unmount')expect(f.ui.toJSON()).toBeNull();else expect(f.ui.queryByTestId('realtime-conflict-card')).toBeNull();
  await act(async()=>{callbacks.onUpdate();callbacks.onGoBack();});expect(f.http).toHaveBeenCalledTimes(count);expect(f.clear).not.toHaveBeenCalled();
 }finally{f.close();}
});

it('does not revive a captured choice after pause and confirmed same-session foreground',async()=>{
 const f=fixture();
 try{await f.edit();act(()=>f.remote());await f.ui.findByTestId('realtime-conflict-card');const old=f.ui.UNSAFE_getByType(RealtimeConflictDialog).props.onUpdate;
  act(()=>f.session.pause());await act(async()=>{await f.session.foreground();});await f.ui.findByTestId('realtime-conflict-card');
  await act(async()=>old());expect(f.counts().form).toBe(1);expect(f.ui.getByPlaceholderText('Title',{includeHiddenElements:true}).props.value).toBe('local draft');
  fireEvent.press(f.ui.getByRole('button',{name:'Update'}));await waitFor(()=>expect(f.ui.getByPlaceholderText('Title').props.value).toBe('Saved 2'));
 }finally{f.close();}
});

it('rejects consent for an older draft revision and never grants a second click authority',async()=>{
 const f=fixture();
 try{await f.edit();act(()=>f.remote());await f.ui.findByTestId('realtime-conflict-card');const old=f.ui.UNSAFE_getByType(RealtimeConflictDialog).props.onUpdate;
  fireEvent.changeText(f.ui.getByPlaceholderText('Title',{includeHiddenElements:true}),'newer draft');await act(async()=>old());expect(f.counts().form).toBe(1);expect(f.ui.getByPlaceholderText('Title',{includeHiddenElements:true}).props.value).toBe('newer draft');
  fireEvent.press(f.ui.getByRole('button',{name:'Update'}));await waitFor(()=>expect(f.ui.getByPlaceholderText('Title').props.value).toBe('Saved 2'));
 }finally{f.close();}
});

it('keeps failed Update stale and retries the same explicit discard revision without a second confirmation',async()=>{
 const f=fixture(),alert=jest.spyOn(Alert,'alert').mockImplementation(()=>{});
 try{await f.edit();act(()=>f.remote());await f.ui.findByTestId('realtime-conflict-card');f.hold();fireEvent.press(f.ui.getByRole('button',{name:'Update'}));await waitFor(()=>expect(f.waiting()).toBe(true));await act(async()=>f.fail());
  await f.ui.findByText('Could not update. Try again.');expect(f.ui.queryByTestId('realtime-conflict-card')).toBeNull();expect(f.ui.queryByPlaceholderText('Title')).toBeNull();expect(f.ui.getByPlaceholderText('Title',{includeHiddenElements:true}).props.value).toBe('local draft');
  expect(f.events.at(-1)).toMatchObject({outcome:'error',reason:'request-error'});fireEvent.press(f.ui.getByRole('button',{name:'Update'}));await waitFor(()=>expect(f.ui.getByPlaceholderText('Title').props.value).toBe('Saved 3'));expect(alert).not.toHaveBeenCalled();expect(f.notice).not.toHaveBeenCalled();
 }finally{f.close();alert.mockRestore();}
});

it('does not acknowledge changes received after the Update GET was admitted',async()=>{
 const f=fixture();
 try{await f.edit();act(()=>f.remote());await f.ui.findByTestId('realtime-conflict-card');f.hold();fireEvent.press(f.ui.getByRole('button',{name:'Update'}));await waitFor(()=>expect(f.waiting()).toBe(true));
  act(()=>{f.remote();f.remote();});expect(f.ui.queryByTestId('realtime-conflict-card')).toBeNull();await act(async()=>f.release());await waitFor(()=>expect(f.ui.getByPlaceholderText('Title',{includeHiddenElements:true}).props.value).toBe('Saved 2'));
  expect(f.session.gate.snapshot().routes.find(route=>route.focused)?.notice).toBe(true);await f.ui.findByTestId('realtime-conflict-card');expect(f.ui.queryByTestId('realtime-notice')).toBeNull();expect(f.notice).not.toHaveBeenCalled();
  fireEvent.press(f.ui.getByRole('button',{name:'Update'}));await waitFor(()=>expect(f.ui.getByPlaceholderText('Title').props.value).toBe('Saved 3'));expect(f.session.gate.snapshot().routes.find(route=>route.focused)?.notice).toBe(false);expect(f.notice).not.toHaveBeenCalled();
 }finally{f.close();}
});

it('requires new explicit consent if a live field changes while its discarded-revision GET is pending',async()=>{
 const f=fixture();
 try{await f.edit();act(()=>f.remote());await f.ui.findByTestId('realtime-conflict-card');f.hold();const stale=f.ui.UNSAFE_getByType(RealtimeConflictDialog).props.onUpdate;act(()=>stale());await waitFor(()=>expect(f.waiting()).toBe(true));
  fireEvent.changeText(f.ui.getByPlaceholderText('Title',{includeHiddenElements:true}),'later native edit');await act(async()=>f.release());await f.ui.findByTestId('realtime-conflict-card');
  expect(f.ui.getByPlaceholderText('Title',{includeHiddenElements:true}).props.value).toBe('later native edit');expect(f.events.filter(event=>event.reason==='reload-layout')).toHaveLength(0);await act(async()=>stale());expect(f.counts().form).toBe(2);
  fireEvent.press(f.ui.getByRole('button',{name:'Update'}));await waitFor(()=>expect(f.ui.getByPlaceholderText('Title').props.value).toBe('Saved 3'));expect(f.notice).not.toHaveBeenCalled();
 }finally{f.close();}
});

it.each(['update','back'] as const)('defers choices during a POST and abandons its retained response/effects before %s without replay',async choice=>{
 const f=fixture({settings:true});
 try{await f.edit();f.hold('post');fireEvent.press(f.ui.getByText('Save form'));await waitFor(()=>expect(f.waiting('post')).toBe(true));fireEvent.changeText(f.ui.getByPlaceholderText('Title'),'newer settings');
  act(()=>f.remote());await f.ui.findByTestId('realtime-conflict-card');const pending=f.ui.UNSAFE_getByType(RealtimeConflictDialog).props;expect(pending.pending).toBe(true);act(()=>{pending.onUpdate();pending.onGoBack();});expect(f.counts()).toEqual({home:1,form:1});
  await act(async()=>f.release('post'));await waitFor(()=>expect(f.ui.UNSAFE_getByType(RealtimeConflictDialog).props.pending).toBe(false));
  fireEvent.press(f.ui.getByRole('button',{name:choice==='update'?'Update':'Go back'}));
  if(choice==='update')await waitFor(()=>expect(f.ui.getByPlaceholderText('Title').props.value).toBe('Saved 2'));else await f.ui.findByText('Previous 2');
  expect(f.ui.queryByText('Held server response')).toBeNull();expect(f.clear).not.toHaveBeenCalled();expect(f.notice).not.toHaveBeenCalled();expect(f.events.filter(event=>event.reason==='remote-layout')).toHaveLength(0);
  expect(f.http.mock.calls.filter(([,init])=>init?.method?.toUpperCase()==='POST')).toHaveLength(1);expect(f.events.some(event=>event.outcome==='cancelled'&&event.reason==='sync-replaced')).toBe(true);
 }finally{f.close();}
});
