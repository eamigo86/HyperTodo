'use strict';
const fs = require('node:fs'), path = require('node:path');
const MOBILE = path.resolve(__dirname, '..');
const fail = () => { throw Error('fixture-path-provenance'); };
function absolute(value) {
  if (typeof value !== 'string' || !path.isAbsolute(value) || path.resolve(value) !== value || value === path.parse(value).root || /[\0\r\n]/.test(value)) fail();
  return value;
}
/** No symlink in an existing ancestor, including a dangling link. No writes. */
function noSymlink(value) {
  absolute(value);
  let current=path.parse(value).root;
  for (const part of value.slice(current.length).split(path.sep)) {
    current=path.join(current,part);
    let stat;try { stat=fs.lstatSync(current); } catch(error) { if(error.code==='ENOENT') break; throw error; }
    if (stat.isSymbolicLink()) fail();
  }
  return value;
}
function roots(expected={}) {
  const sourceRoot=absolute(expected.sourceRoot ?? MOBILE);
  const dependencies=absolute(expected.dependencies ?? path.join(sourceRoot,'node_modules'));
  return {sourceRoot,dependencies};
}
const contains=(parent,child)=>child===parent || child.startsWith(parent+path.sep);
function output(expected) {
  const directory=absolute(expected.projectRoot), {sourceRoot,dependencies}=roots(expected);
  if (path.basename(directory)!=='metro' || !new RegExp(`^(?:sse-demo|native-app)-${expected.run}$`).test(path.basename(path.dirname(directory))) ||
      [sourceRoot,dependencies].some(root=>contains(root,directory)||contains(directory,root))) fail();
  noSymlink(directory);return directory;
}
module.exports={MOBILE,absolute,noSymlink,roots,output};
