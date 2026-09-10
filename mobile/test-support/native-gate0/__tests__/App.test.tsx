import React from "react";
import { Platform } from "react-native";
import { fireEvent, render, waitFor } from "@testing-library/react-native";

jest.mock("expo/fetch", () => ({fetch:jest.fn()}));
jest.mock("expo-constants", () => ({__esModule:true,default:{executionEnvironment:"storeClient",expoVersion:"1017880",expoConfig:{extra:{gate0BaseUrl:"http://127.0.0.1:8787/probe-synthetic"}}}}));
jest.mock("../probe", () => ({runNativeProbe:jest.fn(async () => ({status:"PASS",checks:{bootstrapOk:true,firstFrameRead:true,secondFrameRead:true,abortRequested:true,serverCloseObserved:true},failedStage:null,errorCode:null,reported:true,cookieCleanup:"done"}))}));

import { fetch as expoFetch } from "expo/fetch";
import { runNativeProbe } from "../probe";
import App from "../App";

it("requires a deliberate Run and uses global bootstrap plus explicit expo/fetch", async () => {
  const constants = Platform.constants;
  const native = jest.spyOn(Platform, "constants", "get").mockReturnValue({...constants,reactNativeVersion:{major:0,minor:86,patch:2,prerelease:null}});
  const screen = render(<App/>);
  expect(runNativeProbe).not.toHaveBeenCalled();
  fireEvent.press(screen.getByRole("button", {name:"Run isolated native I/O probe"}));
  await waitFor(() => expect(runNativeProbe).toHaveBeenCalledTimes(1));
  const options = (runNativeProbe as jest.Mock).mock.calls[0][0];
  expect(options.bootstrapFetch).toBe(globalThis.fetch);
  expect(options.streamFetch).toBe(expoFetch);
  expect(options.metadata).toMatchObject({clientVersion:"1017880",expoVersion:"57.0.21",executionEnvironment:"storeClient",reactNativeVersion:"0.86.2"});
  expect(screen.getByText("Expo client build/version: 1017880")).toBeTruthy();
  expect(await screen.findByText("PASS — native I/O only")).toBeTruthy();
  expect(screen.getByText("This does not approve the full realtime Gate 0.")).toBeTruthy();
  expect(screen.getByRole("button", {name:"Run isolated native I/O probe"})).toBeDisabled();
  native.mockRestore();
});
