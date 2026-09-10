import {DOMParser} from '@instawork/xmldom';
import {affectsForm} from '../src/realtime/form-entities';
import type {ResourceChange} from '../src/realtime/stream-protocol';

const E='a'.repeat(16),X='1'.repeat(64),Y='2'.repeat(64),P='3'.repeat(64);
const change=(resource:'tasks'|'categories'|'ui',key:string,epoch=E):ResourceChange=>({mutationId:null,entities:{epoch,items:[{resource,key}]}});
function form(items=[{resource:'tasks',key:X},{resource:'ui',key:P}]){
 const root=new DOMParser().parseFromString('<view resources="tasks categories ui"><form><picker-field name="category" value="first"><picker-item value="first"/><picker-item value="second"/></picker-field></form></view>','application/xml').documentElement;
 root.setAttribute('entities',JSON.stringify({epoch:E,items}));
 const choices=Array.from(root.getElementsByTagName('picker-item'));
 for(const [index,node] of choices.entries()){node.setAttribute('realtime-entity-epoch',E);node.setAttribute('realtime-entity-key',index===0?X:Y);}
 return root;
}
it('distinguishes the edited task and profile dependency from a different task, never by account ID',()=>{
 const root=form();expect(affectsForm(root,['tasks'],change('tasks',X))).toBe(true);
 expect(affectsForm(root,['tasks'],change('tasks',Y))).toBe(false);
 expect(affectsForm(root,['ui'],change('ui',P))).toBe(true);
});
it('reads the currently committed picker value rather than its initial selection',()=>{
 const root=form();expect(affectsForm(root,['categories'],change('categories',X))).toBe(true);
 root.getElementsByTagName('picker-field')[0].setAttribute('value','second');
 expect(affectsForm(root,['categories'],change('categories',X))).toBe(false);
 expect(affectsForm(root,['categories'],change('categories',Y))).toBe(true);
});
it('uses conservative resources for unknown/legacy payloads, rotated epochs or malformed local metadata',()=>{
 const root=form();expect(affectsForm(root,['tasks'],undefined)).toBe(true);
 expect(affectsForm(root,['tasks'],{mutationId:null,entities:null})).toBe(true);
 expect(affectsForm(root,['tasks'],change('tasks',Y,'b'.repeat(16)))).toBe(true);
 root.setAttribute('entities','invalid');expect(affectsForm(root,['tasks'],change('tasks',Y))).toBe(true);
});
it('does not treat a new task form as every existing task and fails safe for unknown selected categories',()=>{
 const root=form([{resource:'ui',key:P}]);expect(affectsForm(root,['tasks'],change('tasks',X))).toBe(false);
 root.getElementsByTagName('picker-item')[0].removeAttribute('realtime-entity-key');
 expect(affectsForm(root,['categories'],change('categories',Y))).toBe(true);
 root.getElementsByTagName('picker-field')[0].setAttribute('value','');
 expect(affectsForm(root,['categories'],change('categories',Y))).toBe(false);
});
