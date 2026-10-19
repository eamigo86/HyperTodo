module.exports = {
  preset: "jest-expo",
  collectCoverageFrom: ["App.tsx", "index.ts", "src/**/*.{js,jsx,ts,tsx}"],
  coverageReporters: ["text", "json-summary", "lcov"],
  coverageThreshold: {
    global: {
      statements: 95,
      branches: 95,
      functions: 95,
      lines: 95
    }
  },
  transformIgnorePatterns: [
    "node_modules/(?!((jest-)?react-native.*|@react-native(-community)?|expo-modules-core|expo.*|@expo.*|@react-navigation|hyperview)/)"
  ]
};
