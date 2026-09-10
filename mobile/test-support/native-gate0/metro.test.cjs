'use strict';
const assert = require('node:assert/strict');
const test = require('node:test');
const {withSharedExpo} = require('./metro.cjs');

test('shared Expo alias survives a resolver context with no nodeModulesPaths', () => {
  const config = {resolver:{nodeModulesPaths:['/readonly/node_modules']}};
  const resolved = withSharedExpo(config, '/readonly/node_modules');
  const rewriteContext = {...resolved.resolver,nodeModulesPaths:[]};
  assert.equal(rewriteContext.extraNodeModules.expo, '/readonly/node_modules/expo');
  assert.equal(config.resolver.extraNodeModules, undefined);
});

test('shared Expo lookup preserves normal lookup, existing aliases and HMR settings', () => {
  const config = {resolver:{nodeModulesPaths:['/readonly/node_modules'],extraNodeModules:{other:'/existing'},useWatchman:false},transformer:{asyncRequireModulePath:'expo/internal/async-require-module'}};
  const resolved = withSharedExpo(config, '/readonly/node_modules');
  assert.equal(resolved.resolver.extraNodeModules.other, '/existing');
  assert.deepEqual(resolved.resolver.nodeModulesPaths, config.resolver.nodeModulesPaths);
  assert.equal(resolved.transformer, config.transformer);
  assert.equal(resolved.resolver.useWatchman, false);
  assert.equal(resolved.resolver.resolveRequest, undefined);
});
