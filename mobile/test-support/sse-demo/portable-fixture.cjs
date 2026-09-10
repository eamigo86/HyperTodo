'use strict';
// Test-owned files only; never an approval of a live candidate.
const fs = require('node:fs'), path = require('node:path'), os = require('node:os');
const {createHash, randomBytes} = require('node:crypto');
const hash = bytes => createHash('sha256').update(bytes).digest('hex');
const mobile = path.resolve(__dirname, '../..');
const dependencies = process.env.NATIVE_TEST_NODE_MODULES || path.join(mobile, 'node_modules');
function fixture() {
  const root = fs.realpathSync(fs.mkdtempSync(path.join(os.tmpdir(), 'hypertodo-portable-')));
  const sourceRoot = path.join(root, 'relocated', 'mobile');
  fs.cpSync(mobile, sourceRoot, {recursive:true, filter: name => !['node_modules','.git','assets'].includes(path.basename(name))});
  const files = {};
  function walk(dir) {
    for (const name of fs.readdirSync(dir).sort()) {
      const file = path.join(dir, name), stat = fs.lstatSync(file);
      if (stat.isDirectory()) walk(file);
      else if (/\.(?:[cm]?[jt]s|[jt]sx|json)$/.test(name) || name === 'yarn.lock') files[path.relative(sourceRoot,file)] = hash(fs.readFileSync(file));
    }
  }
  walk(sourceRoot);
  const bytes = JSON.stringify({version:1,files})+'\n', sourceManifest = path.join(root,'reviewed.json');
  fs.writeFileSync(sourceManifest, bytes);
  const run=randomBytes(16).toString('hex');
  const expected={run,apiOrigin:`http://hvt-${run}.local:8787`,metroOrigin:`http://hvtm-${run}.local:8082`,
    platform:'ios',username:'verified-test-account',slug:'hypertodo-sse-demo',mainModuleName:'index',
    projectRoot:path.join(root,`sse-demo-${run}`,'metro'),simulatorUdid:'AAAAAAAA-BBBB-4CCC-8DDD-EEEEEEEEEEEE',
    sourceRoot,dependencies,sourceManifest,sourceManifestSha256:hash(bytes)};
  return {root,expected,files,close:()=>fs.rmSync(root,{recursive:true,force:true})};
}
module.exports={fixture,dependencies,hash};
