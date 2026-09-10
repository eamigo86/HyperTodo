export type FixtureConfig = {
  run: string;
  apiOrigin: string;
  metroOrigin: string;
  credentialKey: string;
  themeKey: string;
};
export function validateFixtureConfig(config: unknown): Readonly<FixtureConfig>;
export function validateServedManifest(manifest: unknown, expected: unknown): Readonly<{
  ready: true;
  scope: string;
  native: 'NOT_RUN';
}>;
export function validateDevelopmentJavaScript(result: unknown, expected: unknown): Readonly<{
  ready: true;
  scope: string;
  native: 'NOT_RUN';
}>;
