import "react-native-gesture-handler/jestSetup";

import React from "react";
import { act, fireEvent, render, waitFor } from "@testing-library/react-native";
import { NavigationContainer, createNavigationContainerRef } from "@react-navigation/native";
import Hyperview, { renderChildren } from "hyperview";
import { Text } from "react-native";
import { createStackNavigator } from "@react-navigation/stack";

import { createRealtimeGate } from "../src/realtime/gate";
import * as operation from "../src/realtime/operation";
import { createHyperviewFetch } from "../src/network";

// Native WebView is irrelevant to this fixture. Hyperview, its parser, component
// registry, navigation and DOM updates are REAL, not mocked by this suite.
jest.mock("react-native-webview", () => ({ WebView: () => null }));
jest.mock("expo-secure-store", () => ({getItem: () => null, setItem: () => undefined}));

const Stack = createStackNavigator();
function Host({ children }: { children: React.ReactNode }) {
  return <NavigationContainer><Stack.Navigator screenOptions={{ animationEnabled: false }}><Stack.Screen name="fixture">{() => children}</Stack.Screen></Stack.Navigator></NavigationContainer>;
}

const NS = "https://hypertodo.app/components";
const BASE = "https://hypertodo.test/hv/tasks/?status=active&category=7";
const document = (requestId: string, page = 1) => `<doc xmlns="https://hyperview.org/hyperview" xmlns:app="${NS}"><screen><body><app:realtime refresh-href="/hv/tasks/?status=active&amp;category=7&amp;fragment=list" target="task-list" mode="list"><list id="task-list"><item key="task-1"><app:realtime-page request-id="${requestId}" page="${page}"/><text>Task one</text></item></list></app:realtime></body></screen></doc>`;

function response(body: string): Response {
  return { status: 200, ok: true, url: BASE, headers: new Headers({ "Content-Type": "application/vnd.hyperview+xml" }), text: async () => body } as Response;
}

it("ACKs the real Hyperview document only after its outer component commits", async () => {
  const gate = createRealtimeGate();
  let duringFetch = 0;
  let duringParse = 0;
  const transport = jest.fn(async (_url: RequestInfo | URL, init?: RequestInit): Promise<Response> => {
    duringFetch = gate.snapshot().pending;
    const id = new Headers(init?.headers).get("X-HyperTodo-Request-ID")!;
    return response(document(id));
  });
  const screen = render(<Host><Hyperview formatDate={() => undefined} entrypointUrl={BASE} fetch={gate.wrapFetch(transport)} components={gate.components} onParseAfter={() => { duringParse = gate.snapshot().pending; }} /></Host>);
  await screen.findByText("Task one");
  await waitFor(() => expect(gate.snapshot().pending).toBe(0));
  expect(duringFetch).toBe(1);
  expect(duringParse).toBe(1);
  expect(gate.snapshot().routes).toHaveLength(1);
  expect(gate.snapshot().routes[0]).toMatchObject({ focused: true, pages: [1], refreshHref: "/hv/tasks/?status=active&category=7&fragment=list" });
  expect(gate.snapshot().routes[0].key).toEqual(expect.any(String));
});

it("does not interpret a completed fetch as a committed ACK", async () => {
  const gate = createRealtimeGate();
  const fetch = gate.wrapFetch(async () => response("<view/>"));
  await fetch(BASE);
  expect(gate.snapshot().pending).toBe(1);
  act(() => gate.invalidate());
  expect(gate.snapshot().pending).toBe(1);
});

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason: Error) => void;
  const promise = new Promise<T>((yes, no) => { resolve = yes; reject = no; });
  return { promise, resolve, reject };
}

const list = (id: string, page: number, tag = "list", label = `Page ${page}`) => `<${tag} xmlns="https://hyperview.org/hyperview" xmlns:app="${NS}"${tag === "list" ? ' id="task-list"' : ''}><item key="page-${page}"><app:realtime-page request-id="${id}" page="${page}"/><text>${label}</text></item></${tag}>`;
const withControls = (id: string, mode = "list") => document(id).replace('mode="list"', `mode="${mode}"`).replace('</app:realtime>', '<view href="/hv/tasks/?status=active&amp;category=7&amp;page=2&amp;fragment=items" action="append" target="task-list"><text>More</text></view><form id="edit-form"><text-field id="draft" name="title" value="seed"/></form></app:realtime>');

function mount(gate: ReturnType<typeof createRealtimeGate>, fetch: ReturnType<ReturnType<typeof createRealtimeGate>["wrapFetch"]>, props: Partial<React.ComponentProps<typeof Hyperview>> = {}) {
  return render(<Host><gate.Root formatDate={() => undefined} entrypointUrl={BASE} fetch={fetch} components={gate.components} {...props}/></Host>);
}

it("counts append markers in the complete XML, not virtualized item lifetimes", async () => {
  const gate = createRealtimeGate();
  const transport = jest.fn(async (_url: RequestInfo | URL, init?: RequestInit): Promise<Response> => {
    const id = new Headers(init?.headers).get("X-HyperTodo-Request-ID")!;
    return response(transport.mock.calls.length === 1 ? withControls(id) : list(id, 2, "items"));
  });
  const screen = mount(gate, gate.wrapFetch(transport));
  await screen.findByText("Task one");
  fireEvent.press(screen.getByText("More"));
  await screen.findByText("Page 2");
  await waitFor(() => expect(gate.snapshot().routes[0].pages).toEqual([1, 2]));
  expect(gate.snapshot().pending).toBe(0);
});

it("waits for append commit before deciding that accumulated pages need notice", async () => {
  const gate = createRealtimeGate();
  const append = deferred<Response>();
  let appendId = "";
  const transport = jest.fn(async (_url: RequestInfo | URL, init?: RequestInit): Promise<Response> => {
    const id = new Headers(init?.headers).get("X-HyperTodo-Request-ID")!;
    if (transport.mock.calls.length === 1) return response(withControls(id));
    appendId = id;
    return append.promise;
  });
  const screen = mount(gate, gate.wrapFetch(transport));
  await screen.findByText("Task one");
  fireEvent.press(screen.getByText("More"));
  await waitFor(() => expect(transport).toHaveBeenCalledTimes(2));
  act(() => gate.invalidate());
  expect(transport).toHaveBeenCalledTimes(2);
  await act(async () => append.resolve(response(list(appendId, 2, "items"))));
  await screen.findByText("Page 2");
  expect(gate.snapshot().routes[0]).toMatchObject({ pages: [1, 2], notice: true });
  expect(transport).toHaveBeenCalledTimes(2);
});

it("serializes an append dispatch behind a refresh commit without losing filters", async () => {
  const gate = createRealtimeGate();
  const refresh = deferred<Response>();
  let refreshId = "";
  const transport = jest.fn(async (_url: RequestInfo | URL, init?: RequestInit): Promise<Response> => {
    const id = new Headers(init?.headers).get("X-HyperTodo-Request-ID")!;
    if (transport.mock.calls.length === 1) return response(withControls(id));
    if (transport.mock.calls.length === 2) { refreshId = id; return refresh.promise; }
    return response(list(id, 2, "items"));
  });
  const screen = mount(gate, gate.wrapFetch(transport));
  await screen.findByText("Task one");
  act(() => gate.invalidate());
  expect(transport).toHaveBeenCalledTimes(2);
  fireEvent.press(screen.getByText("More"));
  expect(transport).toHaveBeenCalledTimes(2);
  await act(async () => refresh.resolve(response(list(refreshId, 1, "list", "Refreshed first page"))));
  await screen.findByText("Page 2");
  expect(screen.getByText("Refreshed first page")).toBeTruthy();
  expect(transport).toHaveBeenCalledTimes(3);
  expect(String(transport.mock.calls[1][0])).toContain("status=active&category=7&fragment=list");
  expect(gate.snapshot().routes[0].pages).toEqual([1, 2]);
});

it("retains a form draft and marks a visible-notice policy instead of refreshing", async () => {
  const gate = createRealtimeGate();
  const transport = jest.fn(async (_url: RequestInfo | URL, init?: RequestInit): Promise<Response> => response(withControls(new Headers(init?.headers).get("X-HyperTodo-Request-ID")!, "notice")));
  const screen = mount(gate, gate.wrapFetch(transport));
  await screen.findByDisplayValue("seed");
  fireEvent.changeText(screen.getByDisplayValue("seed"), "unsaved draft");
  act(() => gate.invalidate());
  expect(screen.getByDisplayValue("unsaved draft")).toBeTruthy();
  expect(gate.snapshot().routes[0].notice).toBe(true);
  expect(transport).toHaveBeenCalledTimes(1);
});

it("rejects an old-epoch response rather than exposing it to Hyperview", async () => {
  const gate = createRealtimeGate();
  const old = deferred<Response>();
  const promise = gate.wrapFetch(() => old.promise)(BASE);
  gate.resetEpoch();
  old.resolve(response(document("old")));
  await expect(promise).rejects.toThrow("Stale realtime epoch");
  expect(gate.snapshot().pending).toBe(0);
});

it("does not refresh hidden mounted routes, and refreshes the same instance on focus", async () => {
  const gate = createRealtimeGate();
  const navigation = createNavigationContainerRef();
  const transport = jest.fn(async (_url: RequestInfo | URL, init?: RequestInit): Promise<Response> => {
    const id = new Headers(init?.headers).get("X-HyperTodo-Request-ID")!;
    return response(transport.mock.calls.length === 1 ? document(id) : list(id, 1, "list", "After focus"));
  });
  const fetch = gate.wrapFetch(transport);
  const screen = render(<NavigationContainer ref={navigation}><Stack.Navigator screenOptions={{ animationEnabled: false }}><Stack.Screen name="fixture">{() => <Hyperview formatDate={() => undefined} entrypointUrl={BASE} fetch={fetch} components={gate.components}/>}</Stack.Screen><Stack.Screen name="other">{() => <Text>Other screen</Text>}</Stack.Screen></Stack.Navigator></NavigationContainer>);
  await screen.findByText("Task one");
  const key = gate.snapshot().routes[0].key;
  act(() => navigation.navigate("other" as never));
  await waitFor(() => expect(gate.snapshot().routes[0].focused).toBe(false));
  act(() => gate.invalidate());
  expect(transport).toHaveBeenCalledTimes(1);
  act(() => navigation.goBack());
  await waitFor(() => expect(transport).toHaveBeenCalledTimes(2));
  expect(gate.snapshot().routes[0].key).toBe(key);
  expect(gate.snapshot().routes[0].focused).toBe(true);
  await screen.findByText("After focus");
  expect(gate.snapshot().pending).toBe(0);
});

it.each(["post-first", "refresh-first"])("serializes POST and refresh commit: %s", async (order) => {
  const gate = createRealtimeGate();
  const delayed = deferred<Response>();
  let delayedId = "";
  const transport = jest.fn(async (_url: RequestInfo | URL, init?: RequestInit): Promise<Response> => {
    const id = new Headers(init?.headers).get("X-HyperTodo-Request-ID")!;
    if (transport.mock.calls.length === 1) return response(withControls(id).replace('</app:realtime>', '<view href="/hv/tasks/1/toggle/" verb="post" action="replace" target="task-list"><text>Toggle</text></view></app:realtime>'));
    if (transport.mock.calls.length === 2) { delayedId = id; return delayed.promise; }
    return response(list(id, 1, "list", "Final state"));
  });
  const screen = mount(gate, gate.wrapFetch(transport));
  await screen.findByText("Task one");
  if (order === "post-first") fireEvent.press(screen.getByText("Toggle"));
  else act(() => gate.invalidate());
  await waitFor(() => expect(transport).toHaveBeenCalledTimes(2));
  if (order === "post-first") act(() => gate.invalidate());
  else fireEvent.press(screen.getByText("Toggle"));
  expect(transport).toHaveBeenCalledTimes(2);
  await act(async () => delayed.resolve(response(list(delayedId, 1, "list", "Intermediate state"))));
  await screen.findByText("Final state");
  expect(transport).toHaveBeenCalledTimes(3);
  const mutation = transport.mock.calls.find(([, init]) => init?.method === "post");
  expect(mutation).toBeDefined();
  expect(gate.snapshot().pending).toBe(0);
});

it.each(["network failure", "AbortError"])("retires failed requests without automatic refresh: %s", async (message) => {
  const gate = createRealtimeGate();
  const signal = new AbortController().signal;
  const transport = jest.fn(async (_url: RequestInfo | URL, _init?: RequestInit): Promise<Response> => { throw new Error(message); });
  await expect(gate.wrapFetch(transport)(BASE, { signal })).rejects.toThrow(message);
  gate.invalidate();
  expect(gate.snapshot()).toMatchObject({ pending: 0, blocked: true });
  expect(transport).toHaveBeenCalledTimes(1);
  expect(transport.mock.calls[0][1]?.signal).toBe(signal);
});

it("keeps a successful empty response unacknowledged without a timer escape", async () => {
  const gate = createRealtimeGate();
  await gate.wrapFetch(async () => response(""))(BASE);
  gate.invalidate();
  expect(gate.snapshot().pending).toBe(1);
  expect(gate.snapshot().queued).toBe(0);
});

it("rejects a stale body after headers resolve through the real Hyperview parser", async () => {
  const gate = createRealtimeGate();
  const body = deferred<string>();
  let requestId = "";
  const textStarted = jest.fn(() => body.promise);
  const fetch = gate.wrapFetch(async (_url, init) => {
    requestId = new Headers(init?.headers).get("X-HyperTodo-Request-ID")!;
    return { ...response(""), text: textStarted };
  });
  const screen = render(<Host><Hyperview formatDate={() => undefined} entrypointUrl={BASE} fetch={fetch} components={gate.components} errorScreen={() => <Text>Blocked stale response</Text>}/></Host>);
  await waitFor(() => expect(textStarted).toHaveBeenCalledTimes(1));
  act(() => gate.resetEpoch());
  await act(async () => body.resolve(document(requestId)));
  expect(screen.queryByText("Task one")).toBeNull();
  expect(await screen.findByText("Blocked stale response")).toBeTruthy();
  expect(gate.snapshot().routes).toHaveLength(0);
});

it("retains an invalidation received while the initial document was in flight", async () => {
  const gate = createRealtimeGate();
  const initial = deferred<Response>();
  let initialId = "";
  const transport = jest.fn(async (_url: RequestInfo | URL, init?: RequestInit): Promise<Response> => {
    const id = new Headers(init?.headers).get("X-HyperTodo-Request-ID")!;
    if (transport.mock.calls.length === 1) { initialId = id; return initial.promise; }
    return response(list(id, 1, "list", "Current state"));
  });
  const screen = mount(gate, gate.wrapFetch(transport));
  await waitFor(() => expect(transport).toHaveBeenCalledTimes(1));
  act(() => gate.invalidate());
  await act(async () => initial.resolve(response(document(initialId))));
  expect(await screen.findByText("Current state")).toBeTruthy();
  expect(transport).toHaveBeenCalledTimes(2);
  expect(gate.snapshot().pending).toBe(0);
});


it("never commits prior-epoch XML outside the boundary when reset happens after parsing", async () => {
  const gate = createRealtimeGate();
  const committed: string[] = [];
  function CommitProbeComponent() {
    React.useLayoutEffect(() => { committed.push("prior epoch"); }, []);
    return <Text>Outside boundary prior epoch</Text>;
  }
  const CommitProbe = Object.assign(CommitProbeComponent, { namespaceURI: NS, localName: "commit-probe" });
  const transport = jest.fn(async (_url: RequestInfo | URL, init?: RequestInit): Promise<Response> => {
    const id = new Headers(init?.headers).get("X-HyperTodo-Request-ID")!;
    return response(document(id).replace("<body>", "<body><app:commit-probe/>"));
  });
  const onParseAfter = jest.fn(() => gate.resetEpoch());
  const screen = mount(gate, gate.wrapFetch(transport), {
    components: [...gate.components, CommitProbe], onParseAfter,
  });
  await waitFor(() => expect(onParseAfter).toHaveBeenCalledTimes(1));
  expect(screen.queryByText("Outside boundary prior epoch")).toBeNull();
  expect(committed).toEqual([]);
  expect(screen.queryByText("Task one")).toBeNull();
  expect(gate.snapshot().routes).toHaveLength(0);
  expect(transport).toHaveBeenCalledTimes(1);
});

it("suspends already committed HXML and resumes only after current auth confirmation", async () => {
  const gate = createRealtimeGate();
  const transport = jest.fn(async (_url: RequestInfo | URL, init?: RequestInit): Promise<Response> => {
    const id = new Headers(init?.headers).get("X-HyperTodo-Request-ID")!;
    const label = transport.mock.calls.length === 1 ? "Old account outside boundary" : "New account outside boundary";
    return response(document(id).replace("<body>", `<body><text>${label}</text>`));
  });
  const screen = mount(gate, gate.wrapFetch(transport));
  await screen.findByText("Old account outside boundary");
  let first!: number;
  act(() => { first = gate.resetEpoch(); });
  expect(screen.queryByText("Old account outside boundary")).toBeNull();
  expect(gate.snapshot().routes).toHaveLength(0);
  expect(transport).toHaveBeenCalledTimes(1);
  let current!: number;
  act(() => { current = gate.resetEpoch(); });
  act(() => { expect(gate.resumeEpoch(first)).toBe(false); });
  expect(transport).toHaveBeenCalledTimes(1);
  act(() => { expect(gate.resumeEpoch(current)).toBe(true); });
  await screen.findByText("New account outside boundary");
  expect(screen.queryByText("Old account outside boundary")).toBeNull();
  expect(transport).toHaveBeenCalledTimes(2);
  act(() => { expect(gate.resumeEpoch(current)).toBe(false); });
  expect(transport).toHaveBeenCalledTimes(2);
});

it("does not let an old request failure block a resumed authentication epoch", async () => {
  const gate = createRealtimeGate();
  const old = deferred<Response>();
  const transport = jest.fn(async (_url: RequestInfo | URL, init?: RequestInit): Promise<Response> => {
    if (transport.mock.calls.length === 1) return old.promise;
    const id = new Headers(init?.headers).get("X-HyperTodo-Request-ID")!;
    return response(document(id).replace("Task one", "Current account"));
  });
  const screen = mount(gate, gate.wrapFetch(transport));
  await waitFor(() => expect(transport).toHaveBeenCalledTimes(1));
  act(() => { const token = gate.resetEpoch(); gate.resumeEpoch(token); });
  await screen.findByText("Current account");
  await act(async () => old.reject(new Error("Old request failed")));
  expect(gate.snapshot()).toMatchObject({ pending: 0, blocked: false, suspended: false });
  expect(screen.getByText("Current account")).toBeTruthy();
});

it("preserves an admitted delayed POST across blur while another route commits independently", async () => {
  const gate = createRealtimeGate();
  const navigation = createNavigationContainerRef();
  const posted = deferred<Response>();
  let postId = "";
  const transport = jest.fn(async (url: RequestInfo | URL, init?: RequestInit): Promise<Response> => {
    const id = new Headers(init?.headers).get("X-HyperTodo-Request-ID")!;
    if (String(url).includes("/delayed-post/")) {postId=id;return posted.promise;}
    if (String(url).includes("/other/")) return response(String(url).includes("fragment=list") ? list(id,1,"list","Other refreshed") : document(id).replaceAll("Task one","Other route").replaceAll("/hv/tasks/?status=active&amp;category=7&amp;fragment=list","/hv/other/?fragment=list"));
    return response(document(id).replace('</app:realtime>', '<view id="delayed-origin"><behavior trigger="press" href="/hv/tasks/delayed-post/" action="append" target="task-list" verb="post" delay="100000"/><text>Delayed POST</text></view></app:realtime>'));
  });
  const fetch = gate.wrapFetch(transport);
  const screen = render(<NavigationContainer ref={navigation}><Stack.Navigator screenOptions={{animationEnabled:false}}><Stack.Screen name="first">{() => <gate.Root formatDate={() => undefined} entrypointUrl={BASE} fetch={fetch} components={gate.components}/>}</Stack.Screen><Stack.Screen name="second">{() => <gate.Root formatDate={() => undefined} entrypointUrl="https://hypertodo.test/hv/other/" fetch={fetch} components={gate.components}/>}</Stack.Screen></Stack.Navigator></NavigationContainer>);
  await screen.findByText("Task one");
  const firstKey=gate.snapshot().routes[0].key;
  jest.useFakeTimers({doNotFake:["queueMicrotask"]});
  try {
    await act(async () => fireEvent.press(screen.getByText("Delayed POST")));
    expect(gate.snapshot()).toMatchObject({operations:1,pending:0});
    expect(transport).toHaveBeenCalledTimes(1);
    act(() => navigation.navigate("second" as never));
    await screen.findByText("Other route");
    expect(gate.snapshot().routes).toHaveLength(2);
    expect(gate.snapshot()).toMatchObject({operations:1,pending:0,blocked:false});
    expect(transport).toHaveBeenCalledTimes(2);
    act(() => gate.invalidate());
    expect(transport).toHaveBeenCalledTimes(2);
    await act(async () => {jest.advanceTimersByTime(100000);});
    expect(transport).toHaveBeenCalledTimes(3);
    expect(transport.mock.calls[2][1]?.method).toBe("post");
    expect(gate.snapshot()).toMatchObject({operations:1,pending:1});
    await act(async () => posted.resolve(response(list(postId,2,"items","Delayed POST committed"))));
    await screen.findByText("Other refreshed");
    expect(gate.snapshot().routes.find(route => route.key===firstKey)).toMatchObject({focused:false,pages:[1,2]});
    expect(gate.snapshot()).toMatchObject({operations:0,pending:0,blocked:false});
    expect(transport.mock.calls.filter(([,init]) => init?.method === "post")).toHaveLength(1);
    expect(transport).toHaveBeenCalledTimes(4);
  } finally {
    screen.unmount();posted.resolve(response(list(postId,2,"items")));
    jest.clearAllTimers();jest.useRealTimers();
  }
});

it.each([null, "#missing-local-source"])("terminates a no-fetch action without inventing ACK or poisoning later work: %s", async (href) => {
  const gate = createRealtimeGate();
  const ended = jest.fn();
  const NoFetch = Object.assign(({element,onUpdate}: import("hyperview").HvComponentProps) => <Text onPress={() => onUpdate(href, "replace", element, {onEnd:ended})}>No fetch</Text>, {localName:"no-fetch",namespaceURI:NS});
  const transport = jest.fn(async (_url: RequestInfo | URL, init?: RequestInit): Promise<Response> => {
    const id = new Headers(init?.headers).get("X-HyperTodo-Request-ID")!;
    return response(transport.mock.calls.length === 1
      ? withControls(id).replace('</app:realtime>', '<app:no-fetch/></app:realtime>')
      : list(id, 2, "items"));
  });
  const screen = mount(gate, gate.wrapFetch(transport), {components:[...gate.components,NoFetch]});
  await screen.findByText("Task one");
  await act(async () => fireEvent.press(screen.getByText("No fetch")));
  expect(gate.snapshot().pending).toBe(0);
  expect(transport).toHaveBeenCalledTimes(1);
  expect(ended).not.toHaveBeenCalled(); // Rejection is not a successful completion or ACK.
  expect(gate.snapshot().lastRejection).toMatchObject({reason: href === null ? "missing-href" : "missing-local-source"});
  fireEvent.press(screen.getByText("More"));
  await waitFor(() => expect(transport).toHaveBeenCalledTimes(2));
  await screen.findByText("Page 2");
});

it("serializes a public custom behavior's nested append behind a refresh", async () => {
  const gate = createRealtimeGate();
  const refresh = deferred<Response>();
  let refreshId = "";
  const custom = {action:"nested-append",callback:(behavior: Element, onUpdate: import("hyperview").HvComponentOnUpdate) => {
    onUpdate("/hv/tasks/?page=2&fragment=items", "append", behavior.parentNode as Element, {targetId:"task-list"});
  }};
  const transport = jest.fn(async (_url: RequestInfo | URL, init?: RequestInit): Promise<Response> => {
    const id = new Headers(init?.headers).get("X-HyperTodo-Request-ID")!;
    if (transport.mock.calls.length === 1) return response(withControls(id).replace('</app:realtime>', '<view><behavior trigger="press" action="nested-append"/><text>Custom more</text></view></app:realtime>'));
    if (transport.mock.calls.length === 2) {refreshId=id;return refresh.promise;}
    return response(list(id, 2, "items"));
  });
  const screen = mount(gate, gate.wrapFetch(transport), {behaviors:[gate.ownBehavior(custom)]});
  await screen.findByText("Task one");
  act(() => gate.invalidate());
  expect(transport).toHaveBeenCalledTimes(2);
  await act(async () => fireEvent.press(screen.getByText("Custom more")));
  try {
    expect(transport).toHaveBeenCalledTimes(2);
  } finally {
    await act(async () => refresh.resolve(response(list(refreshId, 1, "list", "Refreshed first page"))));
    screen.unmount();
  }
});

it("denies a retained fetch callback during suspended authentication without starting transport", async () => {
  const gate = createRealtimeGate();
  const transport = jest.fn(async () => response("<view/>"));
  const retained = gate.wrapFetch(transport);
  gate.resetEpoch();
  await expect(retained(BASE, {method:"POST",body:"private=not-sent"})).rejects.toThrow("Realtime authentication is suspended");
  expect(transport).not.toHaveBeenCalled();
  expect(gate.snapshot()).toMatchObject({pending:0,suspended:true,blocked:true});
});

it("retires once completion without a document ACK and permits the next ordinary action", async () => {
  const gate = createRealtimeGate();
  const transport = jest.fn(async (_url: RequestInfo | URL, init?: RequestInit): Promise<Response> => {
    const id = new Headers(init?.headers).get("X-HyperTodo-Request-ID")!;
    if (transport.mock.calls.length === 1) return response(withControls(id).replace('action="append" target="task-list"', 'action="append" target="task-list" once="true"').replace('</app:realtime>', '<view href="/hv/tasks/?page=3" action="append" target="task-list"><text>Third page</text></view></app:realtime>'));
    return response(list(id, transport.mock.calls.length, "items"));
  });
  const screen = mount(gate, gate.wrapFetch(transport));
  await screen.findByText("Task one");
  fireEvent.press(screen.getByText("More"));
  await screen.findByText("Page 2");
  expect(gate.snapshot().pending).toBe(0);
  fireEvent.press(screen.getByText("More"));
  expect(transport).toHaveBeenCalledTimes(2);
  expect(gate.snapshot().pending).toBe(0);
  fireEvent.press(screen.getByText("Third page"));
  await waitFor(() => expect(transport).toHaveBeenCalledTimes(3));
  await screen.findByText("Page 3");
});

it("does not send an old tree's delayed POST after a new authentication generation resumes", async () => {
  const gate = createRealtimeGate();
  const transport = jest.fn(async (_url: RequestInfo | URL, init?: RequestInit): Promise<Response> => {
    const id = new Headers(init?.headers).get("X-HyperTodo-Request-ID")!;
    return response(withControls(id).replace('action="append" target="task-list"', 'action="append" target="task-list" verb="post" delay="1000"'));
  });
  const screen = mount(gate, gate.wrapFetch(transport), {onError:jest.fn()});
  await screen.findByText("Task one");
  jest.useFakeTimers();
  try {
    fireEvent.press(screen.getByText("More"));
    expect(transport).toHaveBeenCalledTimes(1);
    let token = 0;
    act(() => {token=gate.resetEpoch();});
    expect(screen.queryByText("Task one")).toBeNull();
    act(() => {expect(gate.resumeEpoch(token)).toBe(true);});
    await screen.findByText("Task one");
    expect(transport).toHaveBeenCalledTimes(2);
    await act(async () => {jest.advanceTimersByTime(1000);});
    expect(transport).toHaveBeenCalledTimes(2);
    expect(gate.snapshot()).toMatchObject({blocked:false,suspended:false,pending:0});
  } finally {
    screen.unmount();jest.clearAllTimers();jest.useRealTimers();
  }
});

it("rejects an old tree's retained public behavior callback after authentication resumes", async () => {
  const gate = createRealtimeGate();
  let invokeOldCallback: (() => void) | undefined;
  const retain = { action: "retain-native-callback", callback: (behavior: Element, onUpdate: import("hyperview").HvComponentOnUpdate) => {
    invokeOldCallback = () => onUpdate("/hv/tasks/private-write/", "append", behavior.parentNode as Element, {targetId:"task-list",verb:"post"});
  }};
  const transport = jest.fn(async (_url: RequestInfo | URL, init?: RequestInit): Promise<Response> => {
    const id = new Headers(init?.headers).get("X-HyperTodo-Request-ID")!;
    return response(withControls(id).replace('</app:realtime>', '<view><behavior trigger="press" action="retain-native-callback"/><text>Open native callback</text></view></app:realtime>'));
  });
  const onError = jest.fn();
  const screen = mount(gate, gate.wrapFetch(transport), {behaviors:[retain],onError});
  await screen.findByText("Task one");
  await act(async () => fireEvent.press(screen.getByText("Open native callback")));
  expect(invokeOldCallback).toEqual(expect.any(Function));
  let token = 0;
  act(() => {token=gate.resetEpoch();});
  act(() => {expect(gate.resumeEpoch(token)).toBe(true);});
  await screen.findByText("Task one");
  expect(transport).toHaveBeenCalledTimes(2);
  await act(async () => invokeOldCallback!());
  expect(transport).toHaveBeenCalledTimes(2);
  expect(onError).toHaveBeenCalledWith(expect.objectContaining({message:"Stale realtime root"}));
  expect(gate.snapshot()).toMatchObject({blocked:false,suspended:false,pending:0});
});

it("carries an explicit token before fragment fetch while the actual HTTP URL remains canonical", async () => {
  const gate = createRealtimeGate();
  const transport = jest.fn(async (_url: RequestInfo | URL, init?: RequestInit): Promise<Response> => {
    const id = new Headers(init?.headers).get("X-HyperTodo-Request-ID")!;
    return response(transport.mock.calls.length === 1 ? withControls(id) : list(id,2,"items"));
  });
  const publicFetch = jest.fn(gate.wrapFetch(transport));
  const screen = mount(gate, publicFetch);
  await screen.findByText("Task one");
  fireEvent.press(screen.getByText("More"));
  await screen.findByText("Page 2");
  expect(String(publicFetch.mock.calls[0][0])).toBe(BASE);
  expect(String(publicFetch.mock.calls[1][0])).toMatch(/&__djhv_op=g0-[1-9][0-9]{0,8}-0-[1-9][0-9]{0,8}$/);
  expect(String(transport.mock.calls[1][0])).toBe("https://hypertodo.test/hv/tasks/?status=active&category=7&page=2&fragment=items");
  const replay = publicFetch.mock.calls[1][0];
  await expect(publicFetch(replay)).rejects.toThrow("unknown-operation");
  expect(transport).toHaveBeenCalledTimes(2);
  expect(gate.snapshot().pending).toBe(0);
});

it.each(["g0-999999999-0-1", "g0-1-999999999-1", "false"])("rejects unknown or malformed explicit tokens before transport: %s", async token => {
  const gate = createRealtimeGate();
  const transport = jest.fn(async () => response("<view/>"));
  await expect(gate.wrapFetch(transport)(BASE + "&__djhv_op=" + token)).rejects.toThrow();
  expect(transport).not.toHaveBeenCalled();
  expect(gate.snapshot().pending).toBe(0);
});

it("does not let an unrelated initial load block a fragment or ACK its copied attempt on another route", async () => {
  const gate = createRealtimeGate();
  const navigation = createNavigationContainerRef();
  const first = deferred<Response>();
  const refresh = deferred<Response>();
  let refreshId = "";
  const transport = jest.fn(async (url: RequestInfo | URL, init?: RequestInit): Promise<Response> => {
    const id = new Headers(init?.headers).get("X-HyperTodo-Request-ID")!;
    if (String(url).includes("/waiting/")) return first.promise;
    if (transport.mock.calls.length === 2) return response(document(id).replaceAll("Task one", "Active route"));
    refreshId = id;
    return refresh.promise;
  });
  const fetch = gate.wrapFetch(transport);
  const screen = render(<NavigationContainer ref={navigation}><Stack.Navigator screenOptions={{animationEnabled:false}}><Stack.Screen name="waiting">{() => <gate.Root formatDate={() => undefined} entrypointUrl="https://hypertodo.test/waiting/" fetch={fetch} components={gate.components}/>}</Stack.Screen><Stack.Screen name="active">{() => <gate.Root formatDate={() => undefined} entrypointUrl={BASE} fetch={fetch} components={gate.components}/>}</Stack.Screen></Stack.Navigator></NavigationContainer>);
  await waitFor(() => expect(transport).toHaveBeenCalledTimes(1));
  act(() => navigation.navigate("active" as never));
  await screen.findByText("Active route");
  act(() => gate.invalidate());
  try {
    expect(transport).toHaveBeenCalledTimes(3);
    await act(async () => first.resolve(response(document(refreshId).replaceAll("Task one", "Copied foreign marker"))));
    expect(gate.snapshot()).toMatchObject({operations:1,pending:2,blocked:false});
    await act(async () => refresh.resolve(response(list(refreshId,1,"list","Active refreshed"))));
    await screen.findByText("Active refreshed");
    expect(gate.snapshot()).toMatchObject({operations:0,pending:1});
  } finally {
    screen.unmount();
    first.resolve(response(document("no-ack")));refresh.resolve(response(list(refreshId,1)));
  }
});

it("preserves the form's duplicate fields and wire encoding when a fragment token is stripped", async () => {
  const gate = createRealtimeGate();
  const transport = jest.fn(async (_url: RequestInfo | URL, init?: RequestInit): Promise<Response> => {
    const id = new Headers(init?.headers).get("X-HyperTodo-Request-ID")!;
    return response(transport.mock.calls.length === 1 ? document(id).replace('</app:realtime>', '<form><text-field name="q" value="a b"/><text-field name="q" value="two&amp;three"/><view href="/hv/tasks/?q=a+b&amp;path=%2f%2F" action="append" target="task-list"><text>Form page</text></view></form></app:realtime>') : list(id,2,"items"));
  });
  const screen = mount(gate,gate.wrapFetch(transport));
  await screen.findByText("Task one");
  fireEvent.press(screen.getByText("Form page"));
  await screen.findByText("Page 2");
  expect(String(transport.mock.calls[1][0])).toBe("https://hypertodo.test/hv/tasks/?q=a+b&path=%2f%2F&q=a%20b&q=two%26three");
});

it("rejects reserved POST form fields before sending transport or creating pending state", async () => {
  const gate = createRealtimeGate();
  const form = new FormData();form.append("__djhv_op","user-value");
  const transport = jest.fn(async () => response("<view/>"));
  await expect(gate.wrapFetch(transport)(BASE,{method:"post",body:form})).rejects.toThrow("reserved-parameter");
  expect(transport).not.toHaveBeenCalled();
  expect(gate.snapshot().pending).toBe(0);
});

it("rejects remote hash and preexisting reserved href before SDK dispatch, then permits an ordinary append", async () => {
  const gate = createRealtimeGate();
  const transport = jest.fn(async (_url: RequestInfo | URL, init?: RequestInit): Promise<Response> => {
    const id = new Headers(init?.headers).get("X-HyperTodo-Request-ID")!;
    return response(transport.mock.calls.length === 1 ? withControls(id).replace('</app:realtime>', '<view href="/hv/tasks/#section" action="append"><text>Hash source</text></view><view href="/hv/tasks/?__djhv_op=user-value" action="append"><text>Reserved source</text></view></app:realtime>') : list(id,2,"items"));
  });
  const screen = mount(gate,gate.wrapFetch(transport));
  await screen.findByText("Task one");
  await act(async () => fireEvent.press(screen.getByText("Hash source")));
  expect(gate.snapshot().lastRejection).toMatchObject({reason:"unsupported-href"});
  await act(async () => fireEvent.press(screen.getByText("Reserved source")));
  expect(gate.snapshot().lastRejection).toMatchObject({reason:"reserved-parameter"});
  expect(gate.snapshot()).toMatchObject({operations:0,pending:0});
  expect(transport).toHaveBeenCalledTimes(1);
  fireEvent.press(screen.getByText("More"));
  await screen.findByText("Page 2");
});

it("does not poison a ready route when an unrelated initial document request fails", async () => {
  const gate = createRealtimeGate();
  const navigation = createNavigationContainerRef();
  const first = deferred<Response>();
  const transport = jest.fn(async (url: RequestInfo | URL, init?: RequestInit): Promise<Response> => {
    const id = new Headers(init?.headers).get("X-HyperTodo-Request-ID")!;
    return String(url).includes("/waiting/") ? first.promise : response(document(id));
  });
  const fetch = gate.wrapFetch(transport);
  const screen = render(<NavigationContainer ref={navigation}><Stack.Navigator screenOptions={{animationEnabled:false}}><Stack.Screen name="waiting">{() => <gate.Root formatDate={() => undefined} entrypointUrl="https://hypertodo.test/waiting/" fetch={fetch} components={gate.components} onError={jest.fn()}/>}</Stack.Screen><Stack.Screen name="active">{() => <gate.Root formatDate={() => undefined} entrypointUrl={BASE} fetch={fetch} components={gate.components}/>}</Stack.Screen></Stack.Navigator></NavigationContainer>);
  await waitFor(() => expect(transport).toHaveBeenCalledTimes(1));
  act(() => navigation.navigate("active" as never));
  await screen.findByText("Task one");
  await act(async () => first.reject(new Error("Initial request failed")));
  expect(gate.snapshot().blocked).toBe(false);
  act(() => gate.invalidate());
  await waitFor(() => expect(transport).toHaveBeenCalledTimes(3));
  screen.unmount();
});

it("rejects a token moved to another HTTP method without sending or releasing unrelated work", async () => {
  const gate = createRealtimeGate();
  const transport = jest.fn(async (_url: RequestInfo | URL, init?: RequestInit): Promise<Response> => {
    const id = new Headers(init?.headers).get("X-HyperTodo-Request-ID")!;
    return response(transport.mock.calls.length === 1 ? withControls(id) : list(id,2,"items"));
  });
  const wrapped = gate.wrapFetch(transport);
  const errors = jest.fn();
  const publicFetch = (input: RequestInfo | URL, init?: RequestInit) => wrapped(input, String(input).includes("__djhv_op") ? {...init,method:"post"} : init);
  const screen = mount(gate,publicFetch,{onError:errors});
  await screen.findByText("Task one");
  await act(async () => fireEvent.press(screen.getByText("More")));
  expect(transport).toHaveBeenCalledTimes(1);
  expect(errors).toHaveBeenCalledWith(expect.objectContaining({message:"operation-owner-mismatch"}));
  expect(gate.snapshot().pending).toBe(0);
});

it("bounds live operation reservations without evicting earlier work", async () => {
  const gate = createRealtimeGate();
  const waiting = deferred<Response>();
  const transport = jest.fn(async (_url: RequestInfo | URL, init?: RequestInit): Promise<Response> => {
    const id = new Headers(init?.headers).get("X-HyperTodo-Request-ID")!;
    return transport.mock.calls.length === 1 ? response(withControls(id)) : waiting.promise;
  });
  const screen = mount(gate,gate.wrapFetch(transport),{onError:jest.fn()});
  await screen.findByText("Task one");
  await act(async () => {for (let i=0;i<65;i+=1) fireEvent.press(screen.getByText("More"));});
  expect(gate.snapshot()).toMatchObject({operations:64,queued:63,pending:1,lastRejection:{reason:"operation-capacity"}});
  expect(transport).toHaveBeenCalledTimes(2);
  act(() => {gate.resetEpoch();});
  await act(async () => waiting.resolve(response("<view/>")));
  screen.unmount();
});

it("keeps an owned custom callback usable after a normal committed document clone", async () => {
  const gate = createRealtimeGate();
  const custom = gate.ownBehavior({action:"owned-page",callback:(behavior,onUpdate) => onUpdate("/hv/tasks/?page=next","append",behavior.parentNode as Element,{targetId:"task-list"})});
  const transport = jest.fn(async (_url: RequestInfo | URL, init?: RequestInit): Promise<Response> => {
    const id = new Headers(init?.headers).get("X-HyperTodo-Request-ID")!;
    return response(transport.mock.calls.length === 1 ? document(id).replace('</app:realtime>', '<view><behavior trigger="press" action="owned-page"/><text>Owned page</text></view></app:realtime>') : list(id,transport.mock.calls.length,"items"));
  });
  const screen = mount(gate,gate.wrapFetch(transport),{behaviors:[custom]});
  await screen.findByText("Task one");
  await act(async () => fireEvent.press(screen.getByText("Owned page")));
  await screen.findByText("Page 2");
  await act(async () => fireEvent.press(screen.getByText("Owned page")));
  expect(gate.snapshot().lastRejection).toBeNull();
  await screen.findByText("Page 3");
  expect(gate.snapshot()).toMatchObject({operations:0,pending:0,lastRejection:null});
});

it.each(["method", "url"])("a forged %s rejection leaves the original operation available for its one valid attempt", async mode => {
  const gate = createRealtimeGate();
  const transport = jest.fn(async (_url: RequestInfo | URL, init?: RequestInit): Promise<Response> => {
    const id = new Headers(init?.headers).get("X-HyperTodo-Request-ID")!;
    return response(transport.mock.calls.length === 1 ? withControls(id) : list(id,2,"items"));
  });
  const wrapped = gate.wrapFetch(transport);
  const publicFetch = async (input: RequestInfo | URL, init?: RequestInit) => {
    if (String(input).includes("__djhv_op")) {
      const forgedInput = mode === "url" ? String(input).replace("/hv/tasks/", "/hv/other/") : input;
      const forgedInit = mode === "method" ? {...init,method:"post"} : init;
      await expect(wrapped(forgedInput,forgedInit)).rejects.toThrow("operation-owner-mismatch");
      expect(gate.snapshot()).toMatchObject({operations:1,pending:0,blocked:false});
      expect(transport).toHaveBeenCalledTimes(1);
    }
    return wrapped(input,init);
  };
  const screen = mount(gate,publicFetch);
  await screen.findByText("Task one");
  fireEvent.press(screen.getByText("More"));
  await screen.findByText("Page 2");
  expect(gate.snapshot()).toMatchObject({operations:0,pending:0,blocked:false});
  expect(transport).toHaveBeenCalledTimes(2);
});

it("rejects a captured owned callback when its originating behavior has been removed", async () => {
  const gate = createRealtimeGate();
  let later: (() => void) | undefined;
  const owned = gate.ownBehavior({action:"retain-owned",callback:(element,onUpdate) => {
    later=() => onUpdate("/hv/tasks/private-write/","append",element.parentNode as Element,{verb:"post",targetId:"task-list"});
  }});
  const transport = jest.fn(async (_url: RequestInfo | URL, init?: RequestInit): Promise<Response> => {
    const id = new Headers(init?.headers).get("X-HyperTodo-Request-ID")!;
    if (transport.mock.calls.length === 1) return response(document(id).replace('</app:realtime>', '<view id="callback-owner"><behavior trigger="press" action="retain-owned"/><text>Retain owned</text></view><view href="/hv/remove-callback/" action="replace" target="callback-owner"><text>Remove callback</text></view></app:realtime>'));
    return response(`<view xmlns="https://hyperview.org/hyperview" xmlns:app="${NS}" id="callback-owner"><list><item key="owner"><app:realtime-page request-id="${id}" page="1"/><text>Removed owner</text></item></list></view>`);
  });
  const screen=mount(gate,gate.wrapFetch(transport),{behaviors:[owned]});
  await screen.findByText("Task one");
  await act(async () => fireEvent.press(screen.getByText("Retain owned")));
  expect(later).toEqual(expect.any(Function));
  fireEvent.press(screen.getByText("Remove callback"));
  await screen.findByText("Removed owner");
  expect(gate.snapshot().operations).toBe(0);
  await act(async () => later!());
  expect(transport).toHaveBeenCalledTimes(2);
  expect(gate.snapshot().lastRejection).toMatchObject({reason:"missing-origin"});
});


describe("C1 independent review regressions", () => {
const BASE="https://hypertodo.test/hv/tasks/";
const doc=(id:string,extra="")=>`<doc xmlns="https://hyperview.org/hyperview" xmlns:app="${NS}"><screen><body><app:realtime refresh-href="/hv/tasks/?fragment=list" target="task-list" mode="list"><list id="task-list"><item key="task-1"><app:realtime-page request-id="${id}" page="1"/><text>Task one</text></item></list>${extra}</app:realtime></body></screen></doc>`;
const fragment=(id:string,tag="items",label="Updated")=>`<${tag} xmlns="https://hyperview.org/hyperview" xmlns:app="${NS}"${tag==="list"?' id="task-list"':""}><item key="${id}"><app:realtime-page request-id="${id}" page="1"/><text>${label}</text></item></${tag}>`;
const response=(body:string):Response=>({status:200,ok:true,url:BASE,headers:new Headers({"Content-Type":"application/vnd.hyperview+xml"}),text:async()=>body} as Response);
const idOf=(init?:RequestInit)=>new Headers(init?.headers).get("X-HyperTodo-Request-ID")!;
function deferred<T>(){let resolve!:(value:T)=>void;let reject!:(error:Error)=>void;const promise=new Promise<T>((a,b)=>{resolve=a;reject=b;});return {promise,resolve,reject};}
function mount(gate:ReturnType<typeof createRealtimeGate>,fetch:ReturnType<ReturnType<typeof createRealtimeGate>["wrapFetch"]>,behaviors:import("hyperview").HvBehavior[]=[]){return render(<NavigationContainer><Stack.Navigator screenOptions={{animationEnabled:false}}><Stack.Screen name="only">{()=> <gate.Root entrypointUrl={BASE} fetch={fetch} formatDate={()=>undefined} components={gate.components} behaviors={behaviors} onError={jest.fn()}/>}</Stack.Screen></Stack.Navigator></NavigationContainer>);}

it("C1 admitted GET cannot become POST through retained mutable options while queued",async()=>{
 const gate=createRealtimeGate();const refresh=deferred<Response>();let refreshId="";
 const owned=gate.ownBehavior({action:"mutate-options",callback:(element,onUpdate)=>{
  const options={verb:"get",targetId:"task-list"};
  onUpdate("/hv/tasks/queued/","append",element.parentNode as Element,options);
  options.verb="post";
 }});
 const transport=jest.fn(async(_url:RequestInfo|URL,init?:RequestInit):Promise<Response>=>{
  const id=idOf(init);
  if(transport.mock.calls.length===1)return response(doc(id,'<view><behavior trigger="press" action="mutate-options"/><text>Queue GET</text></view>'));
  if(transport.mock.calls.length===2){refreshId=id;return refresh.promise;}
  return response(fragment(id));
 });
 const screen=mount(gate,gate.wrapFetch(transport),[owned]);
 try{
  await screen.findByText("Task one");act(()=>gate.invalidate());expect(transport).toHaveBeenCalledTimes(2);
  await act(async()=>fireEvent.press(screen.getByText("Queue GET")));expect(transport).toHaveBeenCalledTimes(2);
  await act(async()=>refresh.resolve(response(fragment(refreshId,"list","Refreshed"))));
  await waitFor(()=>expect(transport).toHaveBeenCalledTimes(3));
  expect(transport.mock.calls[2][1]?.method).toBe("get");
 }finally{screen.unmount();refresh.resolve(response(fragment(refreshId)));}
});

it("C1 failed unrelated initial load before another initial commit cannot poison the ready owner",async()=>{
 const gate=createRealtimeGate();const navigation=createNavigationContainerRef();const first=deferred<Response>();const second=deferred<Response>();let secondId="";
 const more='<view href="/hv/tasks/?page=2" action="append" target="task-list"><text>More</text></view>';
 const transport=jest.fn(async(url:RequestInfo|URL,init?:RequestInit):Promise<Response>=>{
  if(String(url).includes("/waiting/"))return first.promise;
  if(transport.mock.calls.length===2){secondId=idOf(init);return second.promise;}
  return response(fragment(idOf(init)));
 });
 const fetch=gate.wrapFetch(transport);
 const screen=render(<NavigationContainer ref={navigation}><Stack.Navigator screenOptions={{animationEnabled:false}}><Stack.Screen name="waiting">{()=> <gate.Root entrypointUrl="https://hypertodo.test/waiting/" fetch={fetch} formatDate={()=>undefined} components={gate.components} onError={jest.fn()}/>}</Stack.Screen><Stack.Screen name="active">{()=> <gate.Root entrypointUrl={BASE} fetch={fetch} formatDate={()=>undefined} components={gate.components} onError={jest.fn()}/>}</Stack.Screen></Stack.Navigator></NavigationContainer>);
 try{
  await waitFor(()=>expect(transport).toHaveBeenCalledTimes(1));act(()=>navigation.navigate("active" as never));
  await waitFor(()=>expect(transport).toHaveBeenCalledTimes(2));
  await act(async()=>first.reject(new Error("Unrelated initial request failed before B commits")));
  await act(async()=>second.resolve(response(doc(secondId,more))));await screen.findByText("Task one");
  await act(async()=>fireEvent.press(screen.getByText("More")));
  await waitFor(()=>expect(transport).toHaveBeenCalledTimes(3));
  expect(gate.snapshot().blocked).toBe(false);
 }finally{screen.unmount();second.resolve(response(doc(secondId)));}
});

it("C1 reserved form rejection cannot strand a new unrelated valid append",async()=>{
 const gate=createRealtimeGate();const transport=jest.fn(async(_url:RequestInfo|URL,init?:RequestInit):Promise<Response>=>response(transport.mock.calls.length===1?doc(idOf(init),'<form><text-field name="__djhv_op" value="user-value"/><view href="/hv/tasks/?fragment=items" verb="post" action="append" target="task-list"><text>Collision</text></view></form><view href="/hv/tasks/?page=2" action="append" target="task-list"><text>More</text></view>'):fragment(idOf(init))));
 const screen=mount(gate,gate.wrapFetch(transport));
 try{
  await screen.findByText("Task one");await act(async()=>fireEvent.press(screen.getByText("Collision")));
  expect(transport).toHaveBeenCalledTimes(1);expect(gate.snapshot().pending).toBe(0);
  await act(async()=>fireEvent.press(screen.getByText("More")));
  await waitFor(()=>expect(transport).toHaveBeenCalledTimes(2));
 }finally{screen.unmount();}
});

// Both wrappers are registered public components in one real document/route.
it("C1 multiple live boundaries are ambiguous before invoking an owned user callback",async()=>{
 const gate=createRealtimeGate();const callback=jest.fn();const owned=gate.ownBehavior({action:"ambiguous-owned",callback});
 const transport=jest.fn(async(_url:RequestInfo|URL,init?:RequestInit):Promise<Response>=>{
  const id=idOf(init);
  const first=doc(id,'<view><behavior trigger="press" action="ambiguous-owned"/><text>Owned action</text></view>');
  const second=`<app:realtime refresh-href="/hv/second/" target="second-list" mode="notice"><list id="second-list"><item key="second"><app:realtime-page request-id="${id}" page="1"/><text>Second boundary</text></item></list></app:realtime>`;
  return response(first.replace('</body>',second+'</body>'));
 });
 const screen=mount(gate,gate.wrapFetch(transport),[owned]);
 try{
  await screen.findByText("Task one");await screen.findByText("Second boundary");
  await act(async()=>fireEvent.press(screen.getByText("Owned action")));
  expect(callback).not.toHaveBeenCalled();
  expect(gate.snapshot().lastRejection).toMatchObject({reason:"ambiguous-owner"});
 }finally{screen.unmount();}
});

});

it("rejects a reserved GET field before SDK dispatch without stranding the next valid operation", async () => {
  const gate=createRealtimeGate();
  const transport=jest.fn(async (_url:RequestInfo|URL,init?:RequestInit):Promise<Response> => {
    const id=new Headers(init?.headers).get("X-HyperTodo-Request-ID")!;
    return response(transport.mock.calls.length===1 ? withControls(id).replace('</app:realtime>','<form><text-field name="__djhv_op" value="user-value"/><view href="/hv/tasks/?fragment=items" action="append" target="task-list"><text>GET collision</text></view></form></app:realtime>') : list(id,2,"items"));
  });
  const screen=mount(gate,gate.wrapFetch(transport),{onError:jest.fn()});
  await screen.findByText("Task one");
  await act(async () => fireEvent.press(screen.getByText("GET collision")));
  expect(transport).toHaveBeenCalledTimes(1);
  expect(gate.snapshot()).toMatchObject({operations:0,pending:0,lastRejection:{reason:"reserved-parameter"}});
  fireEvent.press(screen.getByText("More"));
  await screen.findByText("Page 2");
});

it("carries immutable current-Root provenance through real network composition without leaking it to transport", async () => {
  const gate=createRealtimeGate();
  const transport=jest.fn(async (_url:RequestInfo|URL,init?:RequestInit):Promise<Response> => response(document(new Headers(init?.headers).get("X-HyperTodo-Request-ID")!)));
  const composed=createHyperviewFetch(BASE,gate.wrapFetch(transport),"fixture");
  let captured:RequestInit|undefined;
  const publicFetch=(input:RequestInfo|URL,init?:RequestInit) => {captured=init;return composed(input,init);};
  const screen=mount(gate,publicFetch);
  await screen.findByText("Task one");
  const keys=Object.getOwnPropertySymbols(captured!);
  expect(keys).toHaveLength(1);
  expect(Object.isFrozen((captured as Record<symbol,unknown>)[keys[0]])).toBe(true);
  expect(Object.getOwnPropertySymbols(transport.mock.calls[0][1]!)).toEqual([]);
  expect(transport.mock.calls[0][1]).toMatchObject({credentials:"include",cache:"no-store"});
  for (const invalid of [null, false, undefined, {...(captured as Record<symbol,object>)[keys[0]]}]) {
    const altered={...captured,[keys[0]]:invalid};
    await expect(gate.wrapFetch(transport)(BASE,altered)).rejects.toThrow("Invalid realtime root provenance");
    expect(transport).toHaveBeenCalledTimes(1);
  }
  const other=createRealtimeGate();const otherTransport=jest.fn(async()=>response("<view/>"));
  await expect(other.wrapFetch(otherTransport)(BASE,captured)).rejects.toThrow("Invalid realtime root provenance");
  expect(otherTransport).not.toHaveBeenCalled();
  const old=captured;
  act(() => {const token=gate.resetEpoch();gate.resumeEpoch(token);});
  await screen.findByText("Task one");
  await expect(gate.wrapFetch(transport)(BASE,old)).rejects.toThrow("Invalid realtime root provenance");
  expect(transport).toHaveBeenCalledTimes(2);
});

it.each([
  ["get","../tasks/?tag=a&tag=b&q=a%2Bb"],
  ["get","?tag=a&tag=b&q=a%2Bb"],
  ["get","https://hypertodo.test/hv/nested/tasks/?tag=a&tag=b&q=a%2Bb"],
  ["post","../tasks/?tag=a&tag=b&q=a%2Bb"],
  ["post","?tag=a&tag=b&q=a%2Bb"],
  ["post","https://hypertodo.test/hv/nested/tasks/?tag=a&tag=b&q=a%2Bb"],
])("matches the undecorated real parser for %s %s", async (method,href) => {
  const base="https://hypertodo.test/hv/nested/current/?base=one";
  const bare=Object.assign(({element,stylesheets,onUpdate,options}:import("hyperview").HvComponentProps) => <>{renderChildren(element,stylesheets,onUpdate,options)}</>,{localName:"realtime",namespaceURI:NS});
  const marker=Object.assign(()=>null,{localName:"realtime-page",namespaceURI:NS});
  async function collect(owned:boolean) {
    const gate=createRealtimeGate();
    const transport=jest.fn(async (_url:RequestInfo|URL,init?:RequestInit):Promise<Response> => {
      const id=new Headers(init?.headers).get("X-HyperTodo-Request-ID") ?? "control";
      return response(transport.mock.calls.length===1 ? document(id).replace('</app:realtime>',`<form><text-field name="tag" value="c"/><text-field name="q" value="a b"/><view href="${href.replaceAll("&","&amp;")}" verb="${method}" action="append" target="task-list"><text>Compare parser</text></view></form></app:realtime>`) : list(id,2,"items"));
    });
    const onParseAfter=jest.fn();
    const screen=owned
      ? render(<Host><gate.Root formatDate={()=>undefined} entrypointUrl={base} fetch={gate.wrapFetch(transport)} components={gate.components} onParseAfter={onParseAfter}/></Host>)
      : render(<Host><Hyperview formatDate={()=>undefined} entrypointUrl={base} fetch={transport} components={[bare,marker]} onParseAfter={onParseAfter}/></Host>);
    try {
      await screen.findByText("Task one");fireEvent.press(screen.getByText("Compare parser"));await screen.findByText("Page 2");
      const [url,init]=transport.mock.calls[1];
      expect(String(url)).not.toContain("__djhv_op");
      expect(Object.getOwnPropertySymbols(init!)).toEqual([]);
      const parserUrl=String(onParseAfter.mock.calls.at(-1)?.[0]);
      expect(parserUrl.includes("__djhv_op")).toBe(owned);
      const body=init?.body as FormData & {getParts?:()=>unknown[]};
      const payload=body ? typeof body.getParts==="function" ? body.getParts() : Array.from(body.entries()) : null;
      return {url:String(url),method:init?.method,payload};
    } finally {screen.unmount();}
  }
  const baseline=await collect(false);const owned=await collect(true);
  expect(owned).toEqual(baseline);
  expect(owned.method).toBe(method);
  if(method==="get") expect(owned.url).toContain("tag=a&tag=b&q=a%2Bb&tag=c&q=a%20b");
  else expect(owned.payload).not.toBeNull();
});

it.each(["same-owner","blur","remove"])("keeps captured callback ownership after a real form clone: %s", async transition => {
  const gate=createRealtimeGate();const navigation=createNavigationContainerRef();
  let later:(()=>void)|undefined;
  const behavior=gate.ownBehavior({action:"after-clone",callback:(element,onUpdate)=>{later=()=>onUpdate("/hv/tasks/?page=2","append",element.parentNode as Element,{targetId:"task-list"});}});
  const transport=jest.fn(async (url:RequestInfo|URL,init?:RequestInit):Promise<Response> => {
    const id=new Headers(init?.headers).get("X-HyperTodo-Request-ID")!;
    return response(String(url).includes("page=2") ? list(id,2,"items") : String(url).includes("/other/") ? document(id).replaceAll("Task one","Other owner") : withControls(id).replace('</app:realtime>','<view><behavior trigger="press" action="after-clone"/><text>Keep owner</text></view></app:realtime>'));
  });
  const fetch=gate.wrapFetch(transport);
  const screen=render(<NavigationContainer ref={navigation}><Stack.Navigator screenOptions={{animationEnabled:false}}><Stack.Screen name="first">{()=> <gate.Root entrypointUrl={BASE} fetch={fetch} formatDate={()=>undefined} components={gate.components} behaviors={[behavior]}/>}</Stack.Screen><Stack.Screen name="other">{()=> <gate.Root entrypointUrl="https://hypertodo.test/other/" fetch={fetch} formatDate={()=>undefined} components={gate.components}/>}</Stack.Screen></Stack.Navigator></NavigationContainer>);
  try {
    await screen.findByText("Task one");await act(async()=>fireEvent.press(screen.getByText("Keep owner")));
    fireEvent.changeText(screen.getByDisplayValue("seed"),"preserved draft");await screen.findByDisplayValue("preserved draft");
    if(transition==="blur") act(()=>navigation.navigate("other" as never));
    if(transition==="remove") act(()=>navigation.reset({index:0,routes:[{name:"other"}]}));
    if(transition!=="same-owner") await screen.findByText("Other owner");
    await act(async()=>later!());
    if(transition==="same-owner") {await screen.findByText("Page 2");expect(screen.getByDisplayValue("preserved draft")).toBeTruthy();}
    else {expect(gate.snapshot().lastRejection).toMatchObject({reason:transition==="blur" ? "inactive-owner" : "missing-owner"});expect(transport.mock.calls.some(([url])=>String(url).includes("page=2"))).toBe(false);}
    expect(gate.snapshot()).toMatchObject({operations:0,pending:0,blocked:false});
  } finally {screen.unmount();}
});


it("cannot resume a consumed authentication epoch after counter exhaustion", async () => {
  const gate = createRealtimeGate();
  // Seed only the preceding state without a billion resets. The allocator is
  // REAL again before exercising reset exhaustion and the public resume API.
  const seed = jest.spyOn(operation, "nextCounter").mockReturnValueOnce(999999999);
  let token: number;
  try { token = gate.resetEpoch(); } finally { seed.mockRestore(); }
  expect(token).toBe(999999999);
  expect(gate.resumeEpoch(token)).toBe(true);
  expect(() => gate.resetEpoch()).toThrow("counter-exhausted");
  expect(gate.snapshot()).toMatchObject({epoch:999999999, suspended:true, blocked:true});
  expect(gate.resumeEpoch(token)).toBe(false);
  expect(gate.resumeEpoch(token)).toBe(false);
  expect(() => gate.resetEpoch()).toThrow("counter-exhausted");
  expect(gate.resumeEpoch(token)).toBe(false);
  const transport = jest.fn(async () => response(document("unused")));
  await expect(gate.wrapFetch(transport)(BASE)).rejects.toThrow("Realtime authentication is suspended");
  expect(transport).not.toHaveBeenCalled();
  expect(gate.snapshot()).toMatchObject({epoch:999999999, suspended:true, blocked:true});
});
