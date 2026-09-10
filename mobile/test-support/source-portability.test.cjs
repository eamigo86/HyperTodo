'use strict';
const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),os=require('node:os'),vm=require('node:vm');
const mobile=path.resolve(__dirname,'..');
const ts=require(path.join(process.env.NATIVE_TEST_NODE_MODULES||path.join(mobile,'node_modules'),'typescript'));
for(const name of ['realtime-sse-app.test.tsx','realtime-app-integration.test.tsx','realtime-app-hooks.test.tsx','realtime-session-recovery.test.ts']) {
  test(`${name} reads actual backend HXML from its relocated checkout, independent of cwd`,()=>{
    const root=fs.realpathSync(fs.mkdtempSync(path.join(os.tmpdir(),'hypertodo-templates-')));
    try {
      fs.cpSync(path.join(mobile,'../backend/hyperview'),path.join(root,'backend/hyperview'),{recursive:true});
      const file=path.join(mobile,'__tests__',name),source=fs.readFileSync(file,'utf8');
      const parsed=ts.createSourceFile(file,source,ts.ScriptTarget.Latest,true),calls=[];
      function visit(node){
        if(ts.isCallExpression(node) && ts.isPropertyAccessExpression(node.expression) && node.expression.name.text==='readFileSync') calls.push(node.arguments[0].getText(parsed));
        ts.forEachChild(node,visit);
      }
      visit(parsed);assert.ok(calls.length>0);
      // Execute only existing read-path expressions, not the Jest suite or App.
      for(const expression of calls) {
        const actual=vm.runInNewContext(expression,{__dirname:path.join(root,'mobile/__tests__'),require, jest:{requireActual:require}});
        assert.ok(actual.startsWith(root+path.sep),`${name} escaped its relocated checkout`);
        assert.match(fs.readFileSync(actual,'utf8'),/<(?:doc|view)/);
      }
    }finally{fs.rmSync(root,{recursive:true,force:true});}
  });
}
