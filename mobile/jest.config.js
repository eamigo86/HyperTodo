module.exports = {
  preset: "jest-expo",
  transformIgnorePatterns: [
    "node_modules/(?!((jest-)?react-native.*|@react-native(-community)?|expo-modules-core|expo.*|@expo.*|@react-navigation|hyperview)/)"
  ]
};
