import {dependencies,type ResourceName} from './resources';
import {parseEntitySet,type ResourceChange} from './stream-protocol';
import {utf8Bytes} from './session-protocol';

export type FormObjectKind='task'|'category'|'settings'|'form';
/** Display copy only: require the declared target to match the actual screen. */
export function formObjectKind(boundary:Element):FormObjectKind {
  const kinds:Readonly<Record<string,FormObjectKind>>={'task-form-screen':'task','category-form-screen':'category','settings-screen':'settings'};
  const target=boundary.getAttribute('target')??'';
  if(boundary.getAttribute('mode')!=='form'||!Object.prototype.hasOwnProperty.call(kinds,target))return 'form';
  let parent:Node|null=boundary.parentNode;
  while(parent){
    if(parent.nodeType===1&&(parent as Element).localName==='screen'){
      const screen=parent as Element;
      return screen.namespaceURI==='https://hyperview.org/hyperview'&&screen.getAttribute('id')===target?kinds[target]:'form';
    }
    parent=parent.parentNode;
  }
  return 'form';
}

/** Narrow draft conflicts, never authentication, using current declared dependencies. */
export function affectsForm(boundary:Element,resources:readonly ResourceName[],change:ResourceChange|undefined):boolean {
  if(!change?.entities)return true;
  try{
    const raw=boundary.getAttribute('entities');
    if(!raw||utf8Bytes(raw)>4096)return true;
    const local=parseEntitySet(JSON.parse(raw),dependencies(boundary));
    if(!local||local.epoch!==change.entities.epoch)return true;
    const keys=new Set(local.items.map(item=>item.resource+':'+item.key));
    if(resources.includes('categories')){
      for(const field of Array.from(boundary.getElementsByTagName('picker-field'))){
        if(field.getAttribute('name')!=='category')continue;
        // Hyperview's public picker commits its selection to the field value;
        // picker-item has no selected attribute and transient UI is not saved.
        const value=field.getAttribute('value');if(!value)continue;
        const selected=Array.from(field.getElementsByTagName('picker-item')).filter(item=>item.getAttribute('value')===value);
        if(selected.length!==1)return true;
        const key=selected[0].getAttribute('realtime-entity-key'),epoch=selected[0].getAttribute('realtime-entity-epoch');
        if(!key||!/^[a-f0-9]{64}$/.test(key)||epoch!==local.epoch)return true;
        keys.add('categories:'+key);
      }
    }
    return change.entities.items.some(item=>resources.includes(item.resource)&&keys.has(item.resource+':'+item.key));
  }catch{return true;}
}
