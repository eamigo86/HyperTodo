import {previousRoute} from '../src/realtime/navigation';
import type {NavigationHandle} from '../src/realtime/navigation';
jest.mock('react-native-webview',()=>({WebView:()=>null}));

function navigator(routes:any[],index=routes.length-1,parent?:any){
 let state:any={key:'stack-1',type:'stack',routes,index};
 return {getState:()=>state,getParent:()=>parent,dispatch:jest.fn(),set:(next:any)=>{state=next;}};
}
it('captures exact stack/source/destination keys and dispatches back only once while they remain current',()=>{
 const n=navigator([{key:'list',name:'card'},{key:'form',name:'card'}]);
 const target=previousRoute(n as unknown as NavigationHandle,'form')!;
 expect(target.key).toBe('list');expect(target.isCurrent()).toBe(true);
 expect(target.goBack()).toBe(true);expect(target.goBack()).toBe(false);
 expect(n.dispatch).toHaveBeenCalledTimes(1);expect(n.dispatch).toHaveBeenCalledWith({type:'GO_BACK',source:'form',target:'stack-1'});
});
it('rejects a changed previous identity even when its URL/name is unchanged',()=>{
 const n=navigator([{key:'list-a',name:'card'},{key:'form',name:'card'}]);const target=previousRoute(n as unknown as NavigationHandle,'form')!;
 n.set({...n.getState(),routes:[{key:'list-b',name:'card'},{key:'form',name:'card'}]});
 expect(target.isCurrent()).toBe(false);expect(target.goBack()).toBe(false);expect(n.dispatch).not.toHaveBeenCalled();
});
it('resolves the focused leaf of a previous nested route without choosing a route by URL',()=>{
 const n=navigator([{key:'tabs',name:'root',state:{index:1,routes:[{key:'other'},{key:'selected-list'}]}},{key:'form',name:'card'}]);
 expect(previousRoute(n as unknown as NavigationHandle,'form')?.key).toBe('selected-list');
});
it('can find the owning parent stack but rejects missing history or a nonfocused source',()=>{
 const parent=navigator([{key:'list'},{key:'nested',state:{index:0,routes:[{key:'form'}]}}]);
 const child=navigator([{key:'form'}],0,parent);
 expect(previousRoute(child as unknown as NavigationHandle,'form')?.key).toBe('list');
 expect(previousRoute(navigator([{key:'form'}]) as unknown as NavigationHandle,'form')).toBeNull();
 expect(previousRoute(parent as unknown as NavigationHandle,'list')).toBeNull();
});
