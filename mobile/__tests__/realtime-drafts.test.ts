import {DOMParser} from '@instawork/xmldom';
import {captureDraft,trackDraft} from '../src/realtime/drafts';

const parse=(value:string)=>new DOMParser().parseFromString(value,'application/xml').documentElement;
it('tracks actual serialized form values, not focus attributes or resource versions',()=>{
  const root=parse('<view><form><text-field name="title" value="before"/></form></view>');
  const registry={getFormData:(form:Element)=>{const body=new FormData();body.append('title',form.getElementsByTagName('text-field')[0].getAttribute('value')!);return body;}};
  const first=captureDraft(root,registry),baseline=trackDraft(undefined,first);
  root.getElementsByTagName('text-field')[0].setAttribute('focused','true');
  expect(trackDraft(baseline,captureDraft(root,registry))).toEqual(baseline);
  root.getElementsByTagName('text-field')[0].setAttribute('value','after');
  const changed=trackDraft(baseline,captureDraft(root,registry));
  expect(changed).toMatchObject({dirty:true,revision:1});
  root.getElementsByTagName('text-field')[0].setAttribute('value','before');
  expect(trackDraft(changed,captureDraft(root,registry))).toMatchObject({dirty:false,revision:2});
});

it('keeps the original baseline across edits and only changes it on an explicit committed reset',()=>{
  const baseline=trackDraft(undefined,'first'),one=trackDraft(baseline,'second'),two=trackDraft(one,'third');
  expect(two).toMatchObject({baseline:'first',current:'third',dirty:true,revision:2});
  const saved=trackDraft(two,'third',true);expect(saved).toMatchObject({baseline:'third',current:'third',dirty:false,revision:2});
  expect(trackDraft(saved,'late edit')).toMatchObject({dirty:true,revision:3});
});

it('treats unsupported or oversized form serialization as protected, never clean',()=>{
  const root=parse('<view><form/></view>');
  expect(captureDraft(root,undefined)).toBeNull();
  expect(captureDraft(root,{getFormData:()=>{throw new Error('private');}})).toBeNull();
  const body=new FormData();body.append('title','x'.repeat(262145));
  expect(captureDraft(root,{getFormData:()=>body})).toBeNull();
  expect(trackDraft(undefined,null)).toMatchObject({dirty:true});
  expect(captureDraft(parse('<view/>'),undefined)).toBe('[]');
});

it('does not treat appended request-only row forms or CSRF token rotation as unsaved edits',()=>{
 const parseRows=(count:number,token:string)=>parse('<view>'+Array.from({length:count},()=>`<form><text-field hide="true" name="csrfmiddlewaretoken" value="${token}"/></form>`).join('')+'<form><text-field name="query" value="active"/><text-field hide="true" name="csrfmiddlewaretoken" value="'+token+'"/></form></view>');
 const registry={getFormData:(form:Element)=>{const body=new FormData();for(const field of Array.from(form.getElementsByTagName('text-field')))body.append(field.getAttribute('name')!,field.getAttribute('value')!);return body;}};
 const first=captureDraft(parseRows(20,'before'),registry),next=captureDraft(parseRows(400,'rotated'),registry);
 expect(first).not.toBeNull();expect(next).not.toBeNull();expect(trackDraft(trackDraft(undefined,first),next)).toMatchObject({dirty:false,revision:0});
 const changed=parseRows(400,'another');Array.from(changed.getElementsByTagName('text-field')).find(field=>field.getAttribute('name')==='query')!.setAttribute('value','unsent');
 expect(trackDraft(trackDraft(undefined,first),captureDraft(changed,registry))).toMatchObject({dirty:true,revision:1});
});
