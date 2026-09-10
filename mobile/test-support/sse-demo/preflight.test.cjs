'use strict';
const test=require('node:test'), assert=require('node:assert/strict'), fs=require('node:fs');
const {fixture,dependencies:modules}=require('./portable-fixture.cjs');
const manifest=e=>({launchAsset:{url:e.metroOrigin+'/index.bundle?platform=ios&dev=true'},extra:{
  expoGo:{username:e.username,mainModuleName:'index',debuggerHost:new URL(e.metroOrigin).host,developer:{projectRoot:e.projectRoot}},
  expoClient:{sdkVersion:'57.0.0',slug:e.slug,hostUri:new URL(e.metroOrigin).host,extra:{apiUrl:e.apiOrigin+'/hv/'}}
}});
const js='DefaultApp createSessionApp createEventStream /realtime/events/ expo/fetch expo/src/async-require/hmr.ts';
test('candidate matches independently reviewed portable inventory; actual source drift/missing source fail',t=>{
  const f=fixture();t.after(f.close);const e=f.expected;
  const {verifyCandidate}=require('./preflight.cjs');
  assert.deepEqual(verifyCandidate(e),{sources:Object.keys(f.files).length,native:'NOT_RUN'});
  assert.throws(()=>verifyCandidate(e,p=>p.endsWith('/App.tsx')?Buffer.from('changed'):fs.readFileSync(p)));
  assert.throws(()=>verifyCandidate(e,p=>p===e.sourceManifest?Buffer.from('{}'):fs.readFileSync(p)));
});
test('served manifest must match normal App API, independent source/account/SDK/asset',t=>{
  const f=fixture();t.after(f.close);const e=f.expected;
  const {validateManifest}=require('./preflight.cjs');assert.equal(validateManifest(manifest(e),e),true);
  for(const mutate of [m=>m.extra.expoClient.extra.apiUrl='http://127.0.0.1:8000/hv/',
    m=>m.extra.expoClient.extra.password='no',m=>m.extra.expoClient.sdkVersion='56.0.0',
    m=>m.extra.expoGo.username='other',m=>m.extra.expoGo.developer.projectRoot='/original',
    m=>m.launchAsset.url=m.launchAsset.url.replace('platform=ios','platform=android'),
    m=>m.launchAsset.url='http://foreign/index.bundle?platform=ios&dev=true',
    m=>m.extra.expoGo.mainModuleName='App']) {const m=manifest(e);mutate(m);assert.throws(()=>validateManifest(m,e));}
});
test('preflight checks real response status/body in memory only and never requests API or builds',async t=>{
  const f=fixture();t.after(f.close);const e=f.expected;
  const {checkDevelopment}=require('./preflight.cjs'),{demoFiles}=require('./launcher.cjs'),calls=[];
  const http=async(url,init)=>{calls.push(url);assert.equal(init.redirect,'error');assert.ok(init.signal);
    return calls.length===1?new Response(JSON.stringify(manifest(e))):new Response(js,{headers:{'content-type':'application/javascript'}});};
  assert.deepEqual(await checkDevelopment(e,{http,readEntry:()=>demoFiles(e,modules)['index.js']}),
    {manifest:true,developmentJavaScript:true,entry:true,sources:Object.keys(f.files).length,native:'NOT_RUN'});
  assert.deepEqual(calls,[e.metroOrigin,manifest(e).launchAsset.url]);
});
test('invalid entry/source/expectation fail before HTTP; HTTP errors and Gate0 bundle fail closed',async t=>{
  const f=fixture();t.after(f.close);const e=f.expected;
  const {checkDevelopment}=require('./preflight.cjs'),{demoFiles}=require('./launcher.cjs');let calls=0;
  await assert.rejects(checkDevelopment(e,{http:async()=>{calls++;},readEntry:()=> 'wrong entry'}));assert.equal(calls,0);
  for(const [status,body,type] of [[500,js,'application/javascript'],[200,'realtime-native-app-v1','application/javascript'],[200,js,'text/html']]) {
    let count=0;await assert.rejects(checkDevelopment(e,{readEntry:()=>demoFiles(e,modules)['index.js'],http:async()=>++count===1?
      new Response(JSON.stringify(manifest(e))):new Response(body,{status,headers:{'content-type':type}})}));
  }
});
