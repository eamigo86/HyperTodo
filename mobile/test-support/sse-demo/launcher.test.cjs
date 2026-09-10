'use strict';
const test = require('node:test'), assert = require('node:assert/strict');
const fs = require('node:fs'), path = require('node:path'), vm = require('node:vm');
const {fixture,dependencies:modules}=require('./portable-fixture.cjs');
test('entry registers only the unchanged DefaultApp and public Expo; API only config, no credentials/toolbar', t => {
  const f=fixture();t.after(f.close);
  const {demoFiles, validateEntry} = require('./launcher.cjs');
  const e=f.expected, files=demoFiles(e,modules), seen=[], actualApp={};
  assert.equal(Object.keys(files).length,5);
  vm.runInNewContext(files['index.js'], {require(name) {
    seen.push(name);
    return name==='expo' ? {registerRootComponent:component=>assert.equal(component,actualApp)} : {default:actualApp};
  }});
  assert.deepEqual(seen,['expo',path.join(e.sourceRoot,'App.tsx')]);
  assert.equal(validateEntry(files['index.js'],e),true);
  assert.throws(()=>validateEntry('require("../native-app/index")'));
  const sandbox={module:{exports:{}}}; vm.runInNewContext(files['app.config.cjs'],sandbox);
  assert.deepEqual(JSON.parse(JSON.stringify(sandbox.module.exports.expo.extra)),{apiUrl:e.apiOrigin+'/hv/'});
  assert.match(files['metro.config.cjs'],/withSharedExpo/);
  for (const text of Object.values(files)) assert.doesNotMatch(text,/nativeApp|credentialKey|Receive tasks hint|verified-test-account|AAAAAAAA-BBBB/);
});
test('invalid source/origin/guest/bundle fields are denied before content generation', t => {
  const f=fixture();t.after(f.close);
  const {demoFiles}=require('./launcher.cjs'), e=f.expected;
  for (const delta of [{projectRoot:'/Users/original'}, {platform:'android'}, {simulatorUdid:''},
    {apiOrigin:'http://127.0.0.1:8000'}, {metroOrigin:e.apiOrigin}, {username:'anonymous'},
    {apiOrigin:e.apiOrigin.replace('8787','8081')}, {password:'must-not-be-bundled'}]) {
    assert.throws(()=>demoFiles({...e,...delta},modules));
  }
  assert.throws(()=>demoFiles(e,'/tmp/other-dependencies'));
});
test('five exclusive owned files, readonly dependencies, refusal of reuse and safe cleanup', t => {
  const f=fixture();t.after(f.close);
  const {prepareDemo,cleanupDemo}=require('./launcher.cjs'), e=f.expected;
  try {
    const result=prepareDemo(e,modules);
    assert.deepEqual(result,{prepared:true,files:5,native:'NOT_RUN'});
    assert.equal(fs.readdirSync(e.projectRoot).length,5);
    for(const name of fs.readdirSync(e.projectRoot)) assert.equal(fs.statSync(path.join(e.projectRoot,name)).mode&0o777,0o600);
    assert.throws(()=>prepareDemo(e,modules));
    const foreign=path.join(e.projectRoot,'unowned.txt');fs.writeFileSync(foreign,'retain');
    assert.throws(()=>cleanupDemo(e,modules)); assert.equal(fs.readFileSync(foreign,'utf8'),'retain');
    fs.unlinkSync(foreign);
    assert.equal(cleanupDemo(e,modules),true); assert.equal(fs.existsSync(e.projectRoot),false);
  } finally {fs.rmSync(path.dirname(e.projectRoot),{recursive:true,force:true});}
});
test('symlink launcher cannot redirect preparation into another directory', t => {
  const f=fixture();t.after(f.close);
  const {prepareDemo}=require('./launcher.cjs'), e=f.expected, parent=path.dirname(e.projectRoot);
  fs.mkdirSync(parent,{recursive:true});fs.symlinkSync('/tmp',e.projectRoot);
  try {assert.throws(()=>prepareDemo(e,modules));}
  finally {fs.unlinkSync(e.projectRoot);fs.rmdirSync(parent);}
});
