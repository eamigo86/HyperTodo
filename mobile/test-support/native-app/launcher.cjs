'use strict';

const path = require('node:path');
const {roots,noSymlink}=require('../portable-paths.cjs');
const {
  validateFixtureConfig,
  validateExpectations
} = require('./preflight.cjs');
const mobile = path.resolve(__dirname, '../..');
const entry = sourceRoot => `require(${JSON.stringify(path.join(sourceRoot, 'test-support/native-app/index.tsx'))});\n`;
function validateEntry(source, sourceRoot=mobile) {
  if (source !== entry(sourceRoot)) throw new Error('entry-provenance');
  return true;
}
/** Return text only. Writing is explicit CLI preparation; no server, install or build. */
function launcherFiles(expected, dependencies=roots(expected).dependencies, sourceRoot=roots(expected).sourceRoot) {
  if ((expected.dependencies && expected.dependencies!==dependencies) || (expected.sourceRoot && expected.sourceRoot!==sourceRoot)) throw new Error('dependency-provenance');
  validateExpectations({...expected,dependencies,sourceRoot});
  if (!path.isAbsolute(dependencies)) throw new Error('dependency-provenance');
  const config = validateFixtureConfig(Object.fromEntries(['run', 'apiOrigin', 'metroOrigin', 'credentialKey', 'themeKey'].map(key => [key, expected[key]])));
  const json = value => JSON.stringify(value, null, 2) + '\n';
  return {
    'package.json': json({
      name: 'hypertodo-native-app-private',
      private: true,
      main: 'index.js',
      dependencies: {
        expo: '57.0.21',
        react: '19.2.3',
        'react-native': '0.86.3'
      }
    }),
    'index.js': entry(sourceRoot),
    'app.config.cjs': 'module.exports = ' + json({
      expo: {
        name: 'HyperTodo Native App Fixture',
        slug: expected.slug,
        platforms: ['ios', 'android'],
        orientation: 'portrait',
        extra: {
          nativeApp: config
        }
      }
    }) + ';\n',
    'babel.config.cjs': `module.exports = {presets:[${JSON.stringify(path.join(dependencies, 'babel-preset-expo'))}]};\n`,
    'metro.config.cjs': `const {getDefaultConfig}=require(${JSON.stringify(path.join(dependencies, 'expo/metro-config'))});\nconst {FileStore}=require(${JSON.stringify(path.join(dependencies, 'metro-cache'))});\nconst config=getDefaultConfig(__dirname);\nconfig.watchFolders=${JSON.stringify([sourceRoot, dependencies])};\nconfig.resolver.nodeModulesPaths=${JSON.stringify([dependencies])};\nconfig.resolver.useWatchman = false;\nconfig.cacheStores=[new FileStore({root:${JSON.stringify(path.join(expected.projectRoot, 'metro-cache'))}})];\nconfig.maxWorkers=2;\nconst {withSharedExpo}=require(${JSON.stringify(path.join(sourceRoot, 'test-support/native-gate0/metro.cjs'))});\nmodule.exports=withSharedExpo(config,${JSON.stringify(dependencies)});\n`
  };
}
module.exports = {
  launcherFiles,
  validateEntry
};
if (require.main === module) {
  try {
    const fs = require('node:fs');
    if (process.argv.length !== 4) throw new Error('arguments');
    const expected = JSON.parse(fs.readFileSync(process.argv[2], 'utf8')),
      dependencies = process.argv[3];
    noSymlink(dependencies);noSymlink(roots(expected).sourceRoot);
    for (const [name, version] of [['expo', '57.0.21'], ['react', '19.2.3'], ['react-native', '0.86.3'], ['hyperview', '0.110.0']]) if (JSON.parse(fs.readFileSync(path.join(dependencies, name, 'package.json'), 'utf8')).version !== version) throw new Error('dependency-provenance');
    const files = launcherFiles(expected, dependencies),
      directory = expected.projectRoot;
    if (fs.existsSync(directory)) throw new Error('existing-launcher');
    let ancestor = path.dirname(directory);
    while (!fs.existsSync(ancestor)) ancestor = path.dirname(ancestor);
    if (fs.realpathSync(ancestor) !== ancestor) throw new Error('symlink-launcher');
    fs.mkdirSync(directory, {
      recursive: true,
      mode: 0o700
    });
    for (const [name, source] of Object.entries(files)) fs.writeFileSync(path.join(directory, name), source, {
      flag: 'wx',
      mode: 0o600
    });
    process.stdout.write(JSON.stringify({
      prepared: true,
      files: 5,
      native: 'NOT_RUN'
    }) + '\n');
  } catch {
    process.stderr.write('native-app-launcher: preparation failed\n');
    process.exitCode = 1;
  }
}
