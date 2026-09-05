# Findings

## Confirmed integration behavior

- A successful session login must return the destination HXML directly. A cookie delivered through an iOS 302 response is not a reliable React Native contract.
- Hyperview 0.110.0 provides a native date field but not a time field; the consumer uses validated HH:MM text and combines it in Django.
- Database publication invalidates warmed source cache entries after commit. Inactive rows correctly fall back to physical XML.
- Shared Redis can be tested safely with logical database 14 and a unique namespace; no destructive cleanup is necessary.

## Tooling findings

- Expo 57 uses `expo-splash-screen` 57.0.8 and `jest-expo` 57.0.5 at the time of this implementation.
- Jest 30 cannot execute the Expo 57 preset's TypeScript ESM polyfill in this setup. Jest 29.7.0 is the compatible test runner.
- Jest must transform Expo, React Native, React Navigation, and Hyperview modules rather than applying the default node_modules exclusion.
- Hyperview's published peer ranges describe its previous demo stack and produce expected warnings with Expo 57. The selected matrix still passes Expo Doctor 21 of 21 checks.

## Package findings for a later dj-hyperview release

No new confirmed dj-hyperview defect was found by the automated consumer suite. Any issue discovered during manual iOS or Android smoke testing must be recorded here before changing the package in a release after 0.1.0a7.
