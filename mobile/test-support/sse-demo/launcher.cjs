'use strict';
const fs=require('node:fs'), path=require('node:path');
const {launcherFiles}=require('../native-app/launcher.cjs');
const {validateExpectations,verifyCandidate}=require('./preflight.cjs');
const {roots,noSymlink}=require('../portable-paths.cjs');
const entry=e=>`const {registerRootComponent}=require("expo");\nregisterRootComponent(require(${JSON.stringify(path.join(roots(e).sourceRoot,'App.tsx'))}).default);\n`;
const fail=()=>{throw Error('sse-demo-launcher-failed');};
function validateEntry(source,e={}) {if(source!==entry(e)) fail();return true;}
/** Reuse tested Metro/shared-Expo generation; replace only the entry and App config. */
function demoFiles(e,dependencies=roots(e).dependencies) {
  validateExpectations(e);if(dependencies!==roots(e).dependencies) fail();
  const files=launcherFiles({...e,slug:'hypertodo-native-app',credentialKey:`hvt-native-${e.run}.credential`,themeKey:`hvt-native-${e.run}.theme`},dependencies,roots(e).sourceRoot);
  files['index.js']=entry(e);
  const pkg=JSON.parse(files['package.json']);pkg.name='hypertodo-sse-demo-private';
  files['package.json']=JSON.stringify(pkg,null,2)+'\n';
  files['app.config.cjs']='module.exports = '+JSON.stringify({expo:{name:'HyperTodo SSE Demo',slug:e.slug,
    platforms:['ios'],orientation:'portrait',extra:{apiUrl:e.apiOrigin+'/hv/'}}},null,2)+';\n';
  return files;
}
function checkDependencies(dependencies) {
  noSymlink(dependencies);
  for(const [name,version] of [['expo','57.0.21'],['react','19.2.3'],['react-native','0.86.3'],['hyperview','0.110.0']])
    if(JSON.parse(fs.readFileSync(path.join(dependencies,name,'package.json'),'utf8')).version!==version) fail();
}
function prepareDemo(e,dependencies=roots(e).dependencies) {
  const files=demoFiles(e,dependencies);verifyCandidate(e);checkDependencies(dependencies);
  if(fs.existsSync(e.projectRoot)) fail();noSymlink(e.projectRoot);
  fs.mkdirSync(e.projectRoot,{recursive:true,mode:0o700});
  const written=[];
  try {for(const [name,source] of Object.entries(files)) {
    fs.writeFileSync(path.join(e.projectRoot,name),source,{flag:'wx',mode:0o600});written.push(name);
  }} catch(error) {
    for(const name of written) fs.unlinkSync(path.join(e.projectRoot,name));
    // Do not recursively delete anything created concurrently by another actor.
    try{fs.rmdirSync(e.projectRoot);}catch{}
    throw error;
  }
  return Object.freeze({prepared:true,files:5,native:'NOT_RUN'});
}
/** Only unchanged generated files; caller must stop owned processes/cache first. */
function cleanupDemo(e,dependencies=roots(e).dependencies) {
  const files=demoFiles(e,dependencies);noSymlink(e.projectRoot);
  if(fs.readdirSync(e.projectRoot).sort().join('|')!==Object.keys(files).sort().join('|')) fail();
  for(const [name,source] of Object.entries(files)) {
    const file=path.join(e.projectRoot,name);
    if(!fs.lstatSync(file).isFile() || fs.readFileSync(file,'utf8')!==source) fail();
  }
  for(const name of Object.keys(files)) fs.unlinkSync(path.join(e.projectRoot,name));
  fs.rmdirSync(e.projectRoot);return true;
}
module.exports={demoFiles,validateEntry,prepareDemo,cleanupDemo};
if(require.main===module) {
  try {
    if(process.argv.length!==3 || fs.statSync(process.argv[2]).size>4096) fail();
    const result=prepareDemo(JSON.parse(fs.readFileSync(process.argv[2],'utf8')));
    process.stdout.write(JSON.stringify(result)+'\n');
  } catch {process.stderr.write('sse-demo-launcher: preparation failed\n');process.exitCode=1;}
}
