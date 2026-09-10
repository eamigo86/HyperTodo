'use strict';
const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),vm=require('node:vm');
const {fixture,hash}=require('./portable-fixture.cjs');
test('relocated source and explicit reviewed snapshot prepare only the real App and clean owned files',()=>{
  const f=fixture();try {
    const {prepareDemo,demoFiles,cleanupDemo}=require('./launcher.cjs');
    const {verifyCandidate}=require('./preflight.cjs');
    assert.equal(verifyCandidate(f.expected).sources,Object.keys(f.files).length);
    assert.equal(prepareDemo(f.expected).prepared,true);
    const seen=[];vm.runInNewContext(demoFiles(f.expected)['index.js'],{require(name){seen.push(name);return name==='expo'?{registerRootComponent(){}}:{default:{}};}});
    assert.deepEqual(seen,['expo',path.join(f.expected.sourceRoot,'App.tsx')]);
    const metro=fs.readFileSync(path.join(f.expected.projectRoot,'metro.config.cjs'),'utf8');
    assert.ok(metro.includes(f.expected.sourceRoot));assert.ok(!metro.includes('/private/tmp/djhv-sse-20260908/hypertodo'));
    assert.equal(cleanupDemo(f.expected),true);assert.ok(fs.existsSync(f.expected.sourceManifest));
  } finally{f.close();}
});
test('portable snapshot refuses wrong digest, traversal, partial inventory, changed and newly added source',()=>{
  const f=fixture();try {
    const {verifyCandidate}=require('./preflight.cjs');
    assert.equal(verifyCandidate(f.expected).sources,Object.keys(f.files).length);
    assert.throws(()=>verifyCandidate({...f.expected,sourceManifestSha256:'0'.repeat(64)}));
    const original=fs.readFileSync(f.expected.sourceManifest);
    for(const change of [files=>delete files['App.tsx'],files=>files['../escape.ts']='0'.repeat(64)]) {
      const files={...f.files};change(files);const bytes=JSON.stringify({version:1,files});fs.writeFileSync(f.expected.sourceManifest,bytes);
      assert.throws(()=>verifyCandidate({...f.expected,sourceManifestSha256:hash(bytes)}));
    }
    fs.writeFileSync(f.expected.sourceManifest,original);
    for(const suffix of ['ts','tsx','cts','mts','jsx','js','cjs','mjs','json']) {
      const added=path.join(f.expected.sourceRoot,'src',`unexpected.${suffix}`);fs.writeFileSync(added,'changed');
      assert.throws(()=>verifyCandidate(f.expected),`unreviewed ${suffix} source`);fs.unlinkSync(added);
    }
    fs.appendFileSync(path.join(f.expected.sourceRoot,'App.tsx'),'\n// changed');assert.throws(()=>verifyCandidate(f.expected));
  }finally{f.close();}
});
test('portable source, dependency and output symlinks or protected paths never authorize writing or cleanup',()=>{
  const f=fixture();try {
    const {prepareDemo,cleanupDemo}=require('./launcher.cjs');
    assert.equal(prepareDemo(f.expected).prepared,true);
    const own=path.join(f.expected.projectRoot,'index.js');fs.unlinkSync(own);fs.symlinkSync(path.join(f.expected.sourceRoot,'App.tsx'),own);
    assert.throws(()=>cleanupDemo(f.expected));assert.ok(fs.existsSync(path.join(f.expected.sourceRoot,'App.tsx')));
    const alias=path.join(f.root,'alias');fs.symlinkSync(f.expected.sourceRoot,alias);
    assert.throws(()=>prepareDemo({...f.expected,sourceRoot:alias,projectRoot:path.join(alias,`sse-demo-${f.expected.run}`,'metro')}));
    assert.throws(()=>prepareDemo({...f.expected,projectRoot:path.join(f.expected.sourceRoot,`sse-demo-${f.expected.run}`,'metro')}));
    const depAlias=path.join(f.root,'modules');fs.symlinkSync(f.expected.dependencies,depAlias);
    assert.throws(()=>prepareDemo({...f.expected,dependencies:depAlias}));
  }finally{f.close();}
});
test('dependency roots default to the relocated repository, not a particular maintainer checkout',()=>{
  const f=fixture();try {
    const {demoFiles}=require('./launcher.cjs');
    const e={...f.expected};delete e.dependencies;
    const files=demoFiles(e);
    assert.ok(files['babel.config.cjs'].includes(path.join(e.sourceRoot,'node_modules')));
    assert.ok(!Object.values(files).some(value=>value.includes('/Users/eamigo')));
  }finally{f.close();}
});
test('native harness accepts a new canonical run-scoped output after relocating its helper',()=>{
  const f=fixture();try {
    const {launcherFiles}=require('../native-app/launcher.cjs');
    const e={...f.expected,slug:'hypertodo-native-app',credentialKey:`hvt-native-${f.expected.run}.credential`,themeKey:`hvt-native-${f.expected.run}.theme`,
      projectRoot:path.join(f.root,`native-app-${f.expected.run}`,'metro')};
    const files=launcherFiles(e,e.dependencies,e.sourceRoot);
    assert.ok(files['index.js'].includes(e.sourceRoot));
    assert.ok(files['metro.config.cjs'].includes(e.sourceRoot));
    const relocated=require(path.join(e.sourceRoot,'test-support/native-app/launcher.cjs'));
    const defaults={...e};delete defaults.sourceRoot;
    const copied=relocated.launcherFiles(defaults,e.dependencies);
    assert.ok(copied['index.js'].includes(e.sourceRoot));
    assert.ok(copied['metro.config.cjs'].includes(e.sourceRoot));
  }finally{f.close();}
});
test('native harness development preflight validates the same explicitly relocated entry',async()=>{
  const f=fixture();try {
    const {launcherFiles}=require('../native-app/launcher.cjs'),{checkDevelopment}=require('../native-app/check-development.cjs');
    const e={...f.expected,slug:'hypertodo-native-app',credentialKey:`hvt-native-${f.expected.run}.credential`,themeKey:`hvt-native-${f.expected.run}.theme`};
    const nativeApp=Object.fromEntries(['run','apiOrigin','metroOrigin','credentialKey','themeKey'].map(key=>[key,e[key]]));
    const manifest={launchAsset:{url:e.metroOrigin+'/index.bundle?platform=ios&dev=true'},extra:{expoGo:{username:e.username,mainModuleName:'index',debuggerHost:new URL(e.metroOrigin).host,developer:{projectRoot:e.projectRoot}},expoClient:{sdkVersion:'57.0.0',slug:e.slug,hostUri:new URL(e.metroOrigin).host,extra:{nativeApp}}}};
    let calls=0;
    const result=await checkDevelopment(e,{readEntry:()=>launcherFiles(e,e.dependencies,e.sourceRoot)['index.js'],http:async()=>++calls===1?new Response(JSON.stringify(manifest)):new Response('realtime-native-app-v1 createSessionApp createSessionCredentialPort createThemeStore createOwnedNativePorts expo/src/async-require/hmr.ts',{headers:{'content-type':'application/javascript'}})});
    assert.equal(result.entry,true);assert.equal(calls,2);
  }finally{f.close();}
});
test('native launcher protects the explicitly supplied dependency root as well as the default',()=>{
  const f=fixture();try {
    const {launcherFiles}=require('../native-app/launcher.cjs');
    const e={...f.expected,slug:'hypertodo-native-app',credentialKey:`hvt-native-${f.expected.run}.credential`,themeKey:`hvt-native-${f.expected.run}.theme`};
    delete e.dependencies;
    const dependencies=path.join(f.root,'readonly-modules');fs.mkdirSync(dependencies);
    e.projectRoot=path.join(dependencies,`native-app-${e.run}`,'metro');
    assert.throws(()=>launcherFiles(e,dependencies));
    assert.equal(fs.readdirSync(dependencies).length,0);
  }finally{f.close();}
});
