import { runNativeProbe } from "../probe";

const BASE = "http://127.0.0.1:8787/probe-synthetic";
const metadata = { platform: "ios", clientVersion: "57.0.9", expoVersion: "57.0.21", executionEnvironment: "storeClient", reactNativeVersion: "0.86.3" };
const frame = (stage: number, token: string) => `event: probe\ndata: ${JSON.stringify({stage,token})}\n\n`;
const response = (status: number, json: unknown = {}) => ({ status, ok: status >= 200 && status < 300, json: async () => json, headers: new Headers() } as Response);

function fixture({ ignoreAbort = false, buffered = false, streamStatus = 200, badFrame = false, reportFailure = false, resetFailure = false, malformedReport = false } = {}) {
  const events: string[] = [];
  const queue: Uint8Array[] = [];
  let waiting: ((value: ReadableStreamReadResult<Uint8Array>) => void) | undefined;
  let closed = false;
  let firstAck = false;
  let secondAck = false;
  let clientReport: unknown;
  const push = (text: string) => {
    const value = new TextEncoder().encode(text);
    if (waiting) { const receive = waiting; waiting = undefined; receive({done:false,value}); }
    else queue.push(value);
  };
  const reader = {
    read: jest.fn(async (): Promise<ReadableStreamReadResult<Uint8Array>> => {
      events.push("read");
      if (queue.length) return {done:false,value:queue.shift()!};
      if (closed) return {done:true,value:undefined};
      return new Promise(resolve => { waiting = resolve; });
    }),
    cancel: jest.fn(async () => { events.push("cancel"); closed = true; waiting?.({done:true,value:undefined}); waiting = undefined; }),
    releaseLock: jest.fn(),
  };
  const bootstrapFetch = jest.fn(async (url: string, init?: RequestInit): Promise<Response> => {
    const endpoint = url.slice(BASE.length);
    events.push(endpoint);
    expect(init?.credentials).toBe("include");
    if (endpoint === "/bootstrap") return response(200, {ok:true});
    if (endpoint === "/ack") {
      const token = JSON.parse(String(init?.body)).token;
      if (token === "one") { firstAck = true; events.push("ack1"); push(frame(2,"two")); }
      else if (token === "two") { secondAck = true; events.push("ack2"); }
      else throw new Error("Unexpected token");
      return response(204);
    }
    if (endpoint === "/reset") { if (resetFailure) throw new Error("Reset failed"); return response(204); }
    if (endpoint === "/report" && malformedReport) return response(200, {server:{passed:"false",streamAuthorized:"false",firstAckReceived:"false",secondAckReceived:"false",streamClosed:"false",activeStreams:0,closeReason:"client"}});
    if (endpoint === "/report") return response(200, {server:{passed:firstAck && secondAck && closed,firstFrameSent:true,firstAckReceived:firstAck,secondFrameSent:firstAck,secondAckReceived:secondAck,streamAuthorized:true,streamClosed:closed,activeStreams:closed?0:1,closeReason:closed?"client":null}});
    if (endpoint === "/client-report") {
      clientReport = JSON.parse(String(init?.body));
      if (reportFailure) throw new Error("Private URL/token must not escape");
      return response(204);
    }
    throw new Error("Unknown endpoint");
  });
  const streamFetch = jest.fn(async (_url: string, init?: RequestInit): Promise<Response> => {
    expect(init?.credentials).toBe("include");
    expect(events[0]).toBe("/bootstrap");
    init?.signal?.addEventListener("abort", () => {
      events.push("abort");
      if (!ignoreAbort) { closed=true; waiting?.({done:true,value:undefined}); waiting=undefined; }
    });
    if (!buffered) {
      const first = badFrame ? "event: probe\ndata: invalid\n\n" : frame(1,"one");
      push(first.slice(0,9)); push(first.slice(9));
    }
    return {...response(streamStatus),headers:new Headers({"Content-Type":"text/event-stream"}),body:{getReader:()=>reader}} as unknown as Response;
  });
  return { events, reader, bootstrapFetch, streamFetch, getReport:()=>clientReport };
}

it("ACKs only complete observed frames and proves abort before any cancel fallback", async () => {
  const server = fixture();
  const result = await runNativeProbe({baseUrl:BASE,metadata,...server,timeoutMs:100});
  expect(result.status).toBe("PASS");
  expect(result.checks).toEqual({bootstrapOk:true,firstFrameRead:true,secondFrameRead:true,abortRequested:true,serverCloseObserved:true});
  expect(server.events.indexOf("ack1")).toBeGreaterThan(server.events.indexOf("read"));
  expect(server.events.indexOf("ack2")).toBeGreaterThan(server.events.indexOf("ack1"));
  expect(server.events.indexOf("abort")).toBeGreaterThan(server.events.indexOf("ack2"));
  expect(server.reader.cancel).not.toHaveBeenCalled();
  expect(server.getReport()).toMatchObject({platform:"ios",executionEnvironment:"storeClient",failedStage:null,errorCode:null});
  expect(JSON.stringify(server.getReport())).not.toMatch(/"one"|"two"|cookie|127\.0\.0\.1/);
});

it("does not turn a buffered stream into an incremental streaming pass", async () => {
  const server = fixture({buffered:true});
  const result = await runNativeProbe({baseUrl:BASE,metadata,...server,timeoutMs:10});
  expect(result.status).not.toBe("PASS");
  expect(result.checks.firstFrameRead).toBe(false);
  expect(result.errorCode).toBe("timeout");
});

it("records failure before cleanup if AbortController alone does not close the stream", async () => {
  const server = fixture({ignoreAbort:true});
  const result = await runNativeProbe({baseUrl:BASE,metadata,...server,timeoutMs:10});
  expect(result.status).not.toBe("PASS");
  expect(result.checks.serverCloseObserved).toBe(false);
  expect(server.reader.cancel).toHaveBeenCalledTimes(1);
  expect(server.events.indexOf("/client-report")).toBeLessThan(server.events.indexOf("cancel"));
  expect(server.getReport()).toMatchObject({failedStage:"abort",errorCode:"timeout"});
});

it.each([{streamStatus:401}, {badFrame:true}])("fails closed on unauthorized or malformed streaming data: %j", async options => {
  const server = fixture(options);
  const result = await runNativeProbe({baseUrl:BASE,metadata,...server,timeoutMs:30});
  expect(result.status).toBe("FAIL");
  expect(result.checks.firstFrameRead).toBe(false);
  expect(server.events).not.toContain("ack1");
});

it("does not count a browser or unit-test platform as a native result", async () => {
  const server = fixture();
  const result = await runNativeProbe({baseUrl:BASE,metadata:{...metadata,platform:"web"},...server,timeoutMs:10});
  expect(result.status).toBe("INCONCLUSIVE");
  expect(result.errorCode).toBe("unsupported-runtime");
  expect(server.bootstrapFetch).not.toHaveBeenCalled();
  expect(server.streamFetch).not.toHaveBeenCalled();
});

it("distinguishes report delivery failure and never exposes raw exception content", async () => {
  const server = fixture({reportFailure:true});
  const result = await runNativeProbe({baseUrl:BASE,metadata,...server,timeoutMs:50});
  expect(result.status).toBe("INCONCLUSIVE");
  expect(result.errorCode).toBe("report-upload-failed");
  expect(JSON.stringify(result)).not.toContain("Private URL/token");
});


it.each([{}, {badFrame:true}])("clears only the fixture cookie after recording success or failure: %j", async options => {
  const server = fixture(options);
  const result = await runNativeProbe({baseUrl:BASE,metadata,...server,timeoutMs:30});
  expect(result.cookieCleanup).toBe("done");
  expect(server.events.at(-1)).toBe("/reset");
  expect(server.events.indexOf("/client-report")).toBeLessThan(server.events.indexOf("/reset"));
});

it("records pending cleanup when the fixture reset request fails", async () => {
  const server = fixture({resetFailure:true});
  const result = await runNativeProbe({baseUrl:BASE,metadata,...server,timeoutMs:30});
  expect(result.cookieCleanup).toBe("pending");
  expect(server.events).toContain("/reset");
});

it("never accepts truthy strings as server-side abort evidence", async () => {
  const server = fixture({malformedReport:true});
  const result = await runNativeProbe({baseUrl:BASE,metadata,...server,timeoutMs:30});
  expect(result.status).toBe("FAIL");
  expect(result.checks.serverCloseObserved).toBe(false);
  expect(result.failedStage).toBe("report");
});

it("preserves the observed iOS native build identifier independently of the source SDK", async () => {
  const server = fixture();
  const observed = {platform:"ios",executionEnvironment:"storeClient",clientVersion:"1017880",expoVersion:"57.0.21",reactNativeVersion:"0.86.2"};
  const result = await runNativeProbe({baseUrl:BASE,metadata:observed,...server,timeoutMs:100});
  expect(result.status).toBe("PASS");
  expect(server.getReport()).toMatchObject(observed);
  expect(result.checks.serverCloseObserved).toBe(true);
});

it.each([
  {platform:"web"}, {executionEnvironment:"bare"}, {executionEnvironment:"unknown"},
  {expoVersion:"56.0.0"}, {expoVersion:"57.unknown"}, {expoVersion:""},
  {clientVersion:""}, {clientVersion:"unknown"}, {clientVersion:"1".repeat(65)},
  {clientVersion:"1017880\n"}, {reactNativeVersion:""}, {reactNativeVersion:"unknown"},
])("rejects unsupported or missing runtime metadata before network: %j", async invalid => {
  const server = fixture();
  const result = await runNativeProbe({baseUrl:BASE,metadata:{...metadata,...invalid},...server,timeoutMs:100});
  expect(result.status).toBe("INCONCLUSIVE");
  expect(result.errorCode).toBe("unsupported-runtime");
  expect(result.cookieCleanup).toBe("not-created");
  expect(server.bootstrapFetch).not.toHaveBeenCalled();
  expect(server.streamFetch).not.toHaveBeenCalled();
});
