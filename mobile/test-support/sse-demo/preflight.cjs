'use strict';
const fs=require('node:fs'), path=require('node:path'), {createHash}=require('node:crypto');
const {textBounded}=require('../native-app/check-development.cjs');
const {absolute,noSymlink,roots,output}=require('../portable-paths.cjs');
const fail=()=>{throw Error('sse-demo-preflight-failed');};
const sha=bytes=>createHash('sha256').update(bytes).digest('hex');
function validateExpectations(e) {
  const fields=['run','apiOrigin','metroOrigin','platform','username','slug','mainModuleName','projectRoot','simulatorUdid','sourceManifest','sourceManifestSha256'];
  if(!e || Object.keys(e).some(k=>![...fields,'sourceRoot','dependencies'].includes(k)) || fields.some(k=>typeof e[k]!=='string') ||
    !/^[a-f0-9]{32}$/.test(e.run) || e.platform!=='ios' || e.slug!=='hypertodo-sse-demo' ||
    e.mainModuleName!=='index' || e.username==='anonymous' || !/^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$/.test(e.username) ||
    !/^[A-Fa-f0-9]{8}(?:-[A-Fa-f0-9]{4}){3}-[A-Fa-f0-9]{12}$/.test(e.simulatorUdid) ||
    !/^[a-f0-9]{64}$/.test(e.sourceManifestSha256)) fail();
  output(e);absolute(e.sourceManifest);
  for(const [key,prefix] of [['apiOrigin','hvt'],['metroOrigin','hvtm']]) {
    let u;try{u=new URL(e[key]);}catch{fail();}
    if(u.protocol!=='http:' || u.hostname!==`${prefix}-${e.run}.local` || u.origin!==e[key] ||
      u.username || u.password || !u.port || Number(u.port)<1024 || u.port==='8081') fail();
  }
  if(new URL(e.apiOrigin).port===new URL(e.metroOrigin).port) fail();
  return true;
}
/** Inventory only. A maintainer reviews and pins the manifest separately. */
function sourceFiles(sourceRoot) {
  noSymlink(sourceRoot);
  const names=[];
  function walk(directory) {
    for(const name of fs.readdirSync(directory).sort()) {
      if(['node_modules','.git','assets'].includes(name)) continue;
      const file=path.join(directory,name),stat=fs.lstatSync(file);
      if(stat.isSymbolicLink()) fail();
      if(stat.isDirectory()) walk(file);
      else if(stat.isFile() && (/\.(?:[cm]?[jt]s|[jt]sx|json)$/.test(name) || name==='yarn.lock')) names.push(path.relative(sourceRoot,file));
      if(names.length>2000) fail();
    }
  }
  walk(sourceRoot);return names.sort();
}
/** Verify independent reviewed bytes and the complete executable/config inventory. */
function verifyCandidate(e,read=name=>fs.readFileSync(name)) {
  validateExpectations(e);
  const {sourceRoot}=roots(e);noSymlink(e.sourceManifest);
  if(!fs.lstatSync(e.sourceManifest).isFile() || fs.statSync(e.sourceManifest).size>1024*1024) fail();
  const raw=read(e.sourceManifest);if(sha(raw)!==e.sourceManifestSha256) fail();
  const manifest=JSON.parse(raw);
  if(!manifest || Object.keys(manifest).sort().join('|')!=='files|version' || manifest.version!==1 ||
    !manifest.files || Array.isArray(manifest.files) || typeof manifest.files!=='object') fail();
  const names=sourceFiles(sourceRoot);
  if(!names.includes('App.tsx') || names.join('|')!==Object.keys(manifest.files).sort().join('|')) fail();
  for(const [name,hash] of Object.entries(manifest.files)) {
    if(path.resolve(sourceRoot,name)!==sourceRoot+'/'+name || !/^[a-f0-9]{64}$/.test(hash) || sha(read(path.join(sourceRoot,name)))!==hash) fail();
  }
  return Object.freeze({sources:names.length,native:'NOT_RUN'});
}
function validateManifest(m,e) {
  validateExpectations(e);
  const go=m?.extra?.expoGo, client=m?.extra?.expoClient, extra=client?.extra;
  if(!go || !client || !/^57\.\d+\.\d+$/.test(client.sdkVersion) || go.username!==e.username ||
    go.developer?.projectRoot!==e.projectRoot || client.slug!==e.slug || go.mainModuleName!=='index' ||
    go.debuggerHost!==new URL(e.metroOrigin).host || client.hostUri!==new URL(e.metroOrigin).host ||
    !extra || Object.keys(extra).join('|')!=='apiUrl' || extra.apiUrl!==e.apiOrigin+'/hv/') fail();
  let asset;try{asset=new URL(m.launchAsset.url);}catch{fail();}
  if(asset.origin!==e.metroOrigin || asset.pathname!=='/index.bundle' || asset.username || asset.password ||
    asset.hash || asset.searchParams.get('platform')!=='ios' || asset.searchParams.get('dev')!=='true') fail();
  return true;
}
async function checkDevelopment(e,{http=fetch,readEntry=()=>fs.readFileSync(e.projectRoot+'/index.js','utf8')}={}) {
  validateExpectations(e);const candidate=verifyCandidate(e);
  require('./launcher.cjs').validateEntry(readEntry(),e);
  const m=await http(e.metroOrigin,{headers:{'expo-platform':'ios',Accept:'application/expo+json,application/json'},
    redirect:'error',signal:AbortSignal.timeout(15000)});
  if(m.status!==200 || m.redirected) fail();
  const manifest=JSON.parse(await textBounded(m,1024*1024));validateManifest(manifest,e);
  const response=await http(manifest.launchAsset.url,{redirect:'error',signal:AbortSignal.timeout(120000)});
  if(response.status!==200 || response.redirected || !/javascript/i.test(response.headers.get('content-type')||'')) fail();
  const source=await textBounded(response,32*1024*1024);
  for(const marker of ['DefaultApp','createSessionApp','createEventStream','/realtime/events/','expo/fetch','expo/src/async-require/hmr.ts']) if(!source.includes(marker)) fail();
  if(source.includes('realtime-native-app-v1')) fail();
  verifyCandidate(e); // Detect a source change while Metro was producing its response.
  return Object.freeze({manifest:true,developmentJavaScript:true,entry:true,sources:candidate.sources,native:'NOT_RUN'});
}
module.exports={validateExpectations,verifyCandidate,validateManifest,checkDevelopment,sourceFiles};
if(require.main===module) void (async()=>{
  if(process.argv.length!==3 || fs.statSync(process.argv[2]).size>4096) fail();
  const result=await checkDevelopment(JSON.parse(fs.readFileSync(process.argv[2],'utf8')));
  process.stdout.write(JSON.stringify(result)+'\n');
})().catch(()=>{process.stderr.write('sse-demo-preflight: failed\n');process.exitCode=1;});
