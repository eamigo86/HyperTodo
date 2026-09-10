import {snapshotFormRequest} from './modern-form-body';
import {utf8Bytes} from './session-protocol';

export type DraftState=Readonly<{baseline:string|null;current:string|null;revision:number;dirty:boolean}>;
type Registry={getFormData(element:Element):FormData|null};

/** Use the same public registry serialization as a real submit, only in memory. */
export function captureDraft(boundary:Element,registry:Registry|undefined):string|null {
  try{
    const forms:Element[]=Array.from(boundary.getElementsByTagName('form'));
    if(boundary.localName==='form')forms.unshift(boundary);
    if(!forms.length)return '[]';
    if(!registry)return null;
    const values:string[]=[];
    for(const form of forms){
      const body=snapshotFormRequest({body:registry.getFormData(form)}).body;
      if(body!=null&&typeof body!=='string')return null;
      const fields=new URLSearchParams(body??'');
      // Masked CSRF tokens and request-only row forms are not user drafts.
      // This affects comparison only: real POST serialization stays untouched.
      fields.delete('csrfmiddlewaretoken');
      if(fields.size)values.push(fields.toString());
      if(values.length>32)return null;
    }
    const value=JSON.stringify(values);
    return utf8Bytes(value)<=262144?value:null;
  }catch{return null;}
}

/** A resource hint never changes the baseline; only a proven commit/discard may. */
export function trackDraft(previous:DraftState|undefined,current:string|null,reset=false):DraftState {
  const baseline=!previous||reset?current:previous.baseline;
  const revision=(previous?.revision??0)+(previous&&previous.current!==current?1:0);
  return Object.freeze({baseline,current,revision,dirty:current===null||baseline===null||current!==baseline});
}
