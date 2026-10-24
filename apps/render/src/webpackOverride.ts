import type { WebpackOverrideFn } from "@remotion/bundler";

/**
 * Generated files re-export with NodeNext-style "./x.js" specifiers that point at .ts sources;
 * teach webpack to resolve them (used by both `bundle()` and the Studio config).
 */
export const webpackOverride: WebpackOverrideFn = (config) => ({
  ...config,
  resolve: {
    ...config.resolve,
    extensionAlias: { ".js": [".ts", ".tsx", ".js"] },
  },
});
