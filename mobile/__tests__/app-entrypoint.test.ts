import "react-native-gesture-handler/jestSetup";

jest.mock("expo", () => ({ ...jest.requireActual("expo"), registerRootComponent: jest.fn() }));
jest.mock("expo-splash-screen", () => ({ preventAutoHideAsync: jest.fn(), hideAsync: jest.fn() }));
jest.mock("lottie-react-native", () => ({ __esModule: true, default: () => null }));
jest.mock("react-native-safe-area-context", () => jest.requireActual("react-native-safe-area-context/jest/mock").default);
jest.mock("react-native-webview", () => ({ WebView: () => null }));
jest.mock("expo-secure-store", () => ({ getItem: jest.fn(() => null), setItem: jest.fn() }));

import { registerRootComponent } from "expo";
import App from "../App";

it("registers the real application component at the mobile entrypoint", () => {
  require("../index");
  expect(registerRootComponent).toHaveBeenCalledTimes(1);
  expect(registerRootComponent).toHaveBeenCalledWith(App);
});
