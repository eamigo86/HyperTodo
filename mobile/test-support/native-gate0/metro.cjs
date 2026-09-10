'use strict';
const path = require('node:path');

/** Keep the installed Expo package visible to Expo's project-root HMR lookup. */
function withSharedExpo(config, dependencyRoot) {
  return {
    ...config,
    resolver:{
      ...config.resolver,
      extraNodeModules:{
        ...config.resolver.extraNodeModules,
        expo:path.join(dependencyRoot, 'expo'),
      },
    },
  };
}
module.exports = {withSharedExpo};
