import HvList from "hyperview/src/elements/hv-list";
import { Navigator } from "hyperview/src/services/navigator/navigator";
import { CommonActions, StackRouter } from "@react-navigation/native";
import * as DomHelpers from "hyperview/src/services/dom/helpers";
import HvView from "hyperview/src/elements/hv-view";
import * as NavigatorHelpers from "hyperview/src/services/navigator/helpers";
import { DOMParser } from "@instawork/xmldom";
import { needsHyperRef } from "hyperview/src/components/hv-element/utils";

jest.mock("react-native-webview", () => ({ WebView: () => null }));

// The HXML in backend/hyperview encodes assumptions about how this client turns an
// `action` attribute into a React Navigation dispatch. Those assumptions are the
// whole fix for the "blank screen survives in the back stack" family of bugs, and
// nothing on the server can check them. These tests read the real client.

const doc = () => new DOMParser().parseFromString("<r/>", "application/xml");

function element(tag: string, attributes: Record<string, string> = {}): Element {
  const el = doc().createElement(tag);
  Object.entries(attributes).forEach(([name, value]) => el.setAttribute(name, value));
  return el;
}

describe("which route an action opens", () => {
  it("collapses every real href to the literal route name card or modal", () => {
    // getRouteId (services/navigator/helpers.ts:211-220). Routes are NOT named after
    // the url, so two different task urls opened with `navigate` are both `card`.
    expect(NavigatorHelpers.getRouteId("navigate", "/hv/tasks/1/edit/")).toBe("card");
    expect(NavigatorHelpers.getRouteId("push", "/hv/tasks/1/edit/")).toBe("card");
    expect(NavigatorHelpers.getRouteId("new", "/hv/tasks/1/edit/")).toBe("modal");
  });
});

describe("action=close on a stack", () => {
  const stack = (...names: string[]) => ({
    getParent: () => undefined,
    getState: () => ({
      index: names.length - 1,
      routes: names.map((name, key) => ({ key: String(key), name, params: {} })),
      type: "stack",
    }),
  });

  it("pops the screen when the top route was opened with action=new", () => {
    const [action, navigation] = NavigatorHelpers.buildRequest(
      stack("dashboard-route", "modal") as never,
      "close",
    );

    expect(action).toBe("close");
    expect(navigation).toBeDefined();
  });

  it("is a silent no-op when the top route was opened with action=navigate", () => {
    // buildCloseRequest walks for a route whose NAME starts with 'modal'
    // (helpers.ts:301-345); on a card-only stack it hands back no navigation and
    // navigator.ts:89-95 returns early. The user stays on the emptied form.
    const [action, navigation] = NavigatorHelpers.buildRequest(
      stack("dashboard-route", "card") as never,
      "close",
    );

    expect(action).toBe("close");
    expect(navigation).toBeUndefined();
  });
});

describe("which elements can host a trigger=on-event behavior", () => {
  // on-event listeners are registered by HyperRef alone (hyper-ref.tsx:61, :133-157),
  // and hv-element only wraps a component in HyperRef when that component opts in
  // with supportsHyperRef (components/hv-element/utils.tsx:16). HvList does not, so a
  // listener parked on a <list> never fires -- it is silent dead markup.
  const listener = element("behavior", { "event-name": "tasks-changed", trigger: "on-event" });

  it("registers the listener on a <view>", () => {
    const view = element("view");
    view.appendChild(listener.cloneNode(true));

    expect(needsHyperRef(HvView as never, view, {})).toBe(true);
  });

  it("silently drops the listener on a <list>", () => {
    const list = element("list");
    list.appendChild(listener.cloneNode(true));

    expect(needsHyperRef(HvList as never, list, {})).toBe(false);
  });
});

describe("how a form transition dismisses the screen it just emptied", () => {
  // A *_transition.xml is the response to a `replace` that swaps out the whole form
  // panel, so the form screen is left blank and MUST leave the stack. These cases
  // drive the real Navigator to pin which action can do that, and at what cost.
  const stack = (...names: string[]) => {
    const routes = names.map((name, index) => ({
      key: String(index),
      name,
      params: {},
    }));
    return {
      dispatch: jest.fn(),
      getParent: () => undefined,
      getState: () => ({ index: routes.length - 1, routes, type: "stack" }),
      goBack: jest.fn(),
    };
  };

  const navigatorFor = (navigation: ReturnType<typeof stack>, name: string) =>
    new Navigator({
      entrypointUrl: "/hv/",
      navigation: navigation as never,
      rootNavigation: undefined,
      route: { key: String(navigation.getState().index), name, params: {} } as never,
      setElement: jest.fn(),
    });

  const fire = (
    navigator: Navigator,
    action: string,
    opts: Record<string, unknown> = {},
  ) =>
    navigator.navigate(
      "#",
      action as never,
      element("behavior", { action }),
      { getFormData: () => null } as never,
      opts as never,
    );

  it("pops a card-presented form with action=back", () => {
    // routeBackRequest (navigator.ts:33-77) only takes the CommonActions.reset branch
    // for a BACK from a route BELOW the focused one. A transition always runs on the
    // focused form screen, so it lands on plain goBack() -- which is presentation
    // agnostic. That is what lets the forms go back to being cards.
    const navigation = stack("dashboard-route", "card");

    fire(navigatorFor(navigation, "card"), "back");

    expect(navigation.goBack).toHaveBeenCalledTimes(1);
    expect(navigation.dispatch).not.toHaveBeenCalled();
  });

  it("pops a modal-presented form with the same action=back", () => {
    const navigation = stack("dashboard-route", "modal");

    fire(navigatorFor(navigation, "modal"), "back");

    expect(navigation.goBack).toHaveBeenCalledTimes(1);
  });

  it("does nothing at all with action=close on a card", () => {
    // buildCloseRequest walks the hierarchy for a route NAMED modal (helpers.ts:301-345),
    // finds none, and hands back an undefined navigation; sendRequest (navigator.ts:89-95)
    // then returns before dispatching. The user is stranded on the emptied form, which
    // is why `close` may never appear in a transition again.
    const navigation = stack("dashboard-route", "card");

    fire(navigatorFor(navigation, "card"), "close");

    expect(navigation.goBack).not.toHaveBeenCalled();
    expect(navigation.dispatch).not.toHaveBeenCalled();
  });

  it("holds the emptied screen on screen for the whole of a delay", () => {
    // navigator.ts:187-193 wraps sendRequest in setTimeout. The panel is already gone
    // when the timer starts, so `delay` on a dismissal is measured in frames of blank
    // screen. This is why no transition behavior may carry one.
    jest.useFakeTimers();
    const navigation = stack("dashboard-route", "card");

    fire(navigatorFor(navigation, "card"), "back", { delay: 350 });

    expect(navigation.goBack).not.toHaveBeenCalled();
    jest.advanceTimersByTime(350);
    expect(navigation.goBack).toHaveBeenCalledTimes(1);
    jest.useRealTimers();
  });
});

describe("what the Home tab does to the stack", () => {
  // Every screen embeds fragments/bottom_navigation.xml, so Home is tapped from
  // whatever route is focused. These cases drive the REAL StackRouter with the real
  // buildRequest output, because the whole question is whether Home pushes another
  // dashboard or truncates back to the one at index 0.
  const HOME_URL = "/hv/dashboard/";
  const options = {
    routeGetIdList: {
      // Mirrors getId (elements/hv-navigator/index.tsx:121-133): a declared route is
      // identified by its nav-route id, a dynamic one by the url it was opened with.
      card: ({ params }: never) => (params as { url?: string })?.url,
      modal: ({ params }: never) => (params as { url?: string })?.url,
      "root-route": ({ params }: never) => (params as { id?: string })?.id,
    },
    routeNames: ["root-route", "card", "modal"],
    routeParamList: {
      card: {},
      modal: {},
      // buildScreen's initialParams for a declared nav-route.
      "root-route": {
        id: "root-route",
        isModal: false,
        needsSubStack: false,
        url: HOME_URL,
      },
    },
  };

  const nav = { getParent: () => undefined, getState: () => ({ index: 0, routes: [] }) };

  const tap = (router: never, state: never, href: string) => {
    const [, , routeId, params] = NavigatorHelpers.buildRequest(
      nav as never,
      "navigate",
      { behaviorElementId: null, preloadScreen: null, url: href },
    );
    const next = (router as unknown as {
      getStateForAction: (s: unknown, a: unknown, o: unknown) => unknown;
    }).getStateForAction(state, CommonActions.navigate(routeId, params), options);
    expect(next).not.toBeNull();
    return next as never;
  };

  const walk = (homeHref: string) => {
    const router = StackRouter({}) as never;
    let state = (router as unknown as {
      getInitialState: (o: unknown) => unknown;
    }).getInitialState(options) as never;
    // The owner's sequence: Home, Tasks, Home, Categories, Home.
    for (const href of [homeHref, "/hv/tasks/", homeHref, "/hv/categories/", homeHref]) {
      state = tap(router, state, href);
    }
    return (state as unknown as { routes: { name: string; params: { url?: string } }[] })
      .routes;
  };

  it("truncates back to the declared root route when Home is a fragment href", () => {
    // getRouteId returns cleanHrefFragment for a fragment (helpers.ts:211-218), so the
    // dispatch names the DECLARED route; StackRouter NAVIGATE finds it at index 0 and
    // returns routes.slice(0, 0) plus that route, i.e. a real truncation.
    expect(walk("#root-route").map(route => route.name)).toEqual(["root-route"]);
  });

  it("keeps the root route pointed at its own url after the truncation", () => {
    // buildRequest deletes params.url for a fragment (helpers.ts:395-401), so the
    // merge with routeParamList leaves the declared href intact and HvDoc does not
    // refetch (hv-doc.tsx:186-193). That is why dashboard.xml has to listen for the
    // events that can invalidate what it already rendered.
    expect(walk("#root-route")[0].params.url).toBe(HOME_URL);
  });

  it("strands a duplicate dashboard behind Home when Home uses its url", () => {
    // getRouteId collapses a real url to the literal name `card`, and the declared
    // Home route is NOT named card, so the very first Home tap appends a SECOND
    // dashboard instead of returning to the one already at index 0. Later Home taps
    // do truncate back to that duplicate, so the stack settles at depth 2 with the
    // dashboard rendered twice: Back from Home shows Home again.
    expect(walk(HOME_URL).map(route => route.name)).toEqual(["root-route", "card"]);
    expect(walk(HOME_URL).map(route => route.params.url)).toEqual([
      HOME_URL,
      HOME_URL,
    ]);
  });
});

describe("what a reload does to the route it lands on", () => {
  // HvDoc decides between merging and replacing on ONE thing: whether the fetched
  // document's first child is a <navigator> (hv-doc.tsx:120-131). That is the whole
  // reason a transition may not `reload` /hv/.
  const parse = (xml: string) =>
    new DOMParser().parseFromString(xml, "application/xml");
  const NAVIGATOR_DOC = `<doc xmlns="https://hyperview.org/hyperview"><navigator id="root-navigator" type="stack"><nav-route id="root-route" href="/hv/dashboard/" selected="true"/></navigator></doc>`;
  const SCREEN_DOC = `<doc xmlns="https://hyperview.org/hyperview"><screen id="dashboard-screen"><body/></screen></doc>`;
  const firstChildIsNavigator = (xml: string) =>
    DomHelpers.getFirstChildTag(
      DomHelpers.getFirstTag(parse(xml), "doc") as never,
      "navigator",
    ) !== null;

  it("takes the merge path only for a navigator document", () => {
    expect(firstChildIsNavigator(NAVIGATOR_DOC)).toBe(true);
    expect(firstChildIsNavigator(SCREEN_DOC)).toBe(false);
  });

  it("keeps the whole navigator document when it lands on a screen route", () => {
    // mergeDocument bails to the NEW document when the first child elements differ
    // (helpers.ts:534-542). HvRouteInner then renders a whole HvNavigator inside a
    // route that is already a screen: a stack nested one level deeper on every
    // login/logout cycle. This is why the auth transitions reload a SCREEN url.
    const merged = NavigatorHelpers.mergeDocument(
      parse(NAVIGATOR_DOC) as never,
      parse(SCREEN_DOC) as never,
    );

    expect(
      DomHelpers.getFirstChildTag(
        DomHelpers.getFirstTag(merged as never, "doc") as never,
        "navigator",
      ),
    ).not.toBeNull();
  });
});

describe("how many behaviors one press can run", () => {
  it("runs the element's own href first, then its child behaviors", () => {
    // getBehaviorElements unshifts the element itself when it carries href/action
    // (services/dom/helpers.ts:8-18) and TouchableView chains every press behavior in
    // that order (hyper-ref.tsx:238-263). The side menu's Home link relies on it: the
    // navigate truncates the stack, the child replace dismisses the overlay, and on
    // the dashboard the navigate is a no-op so the replace is the only visible half.
    const home = element("view", { action: "navigate", href: "#root-route" });
    const close = element("behavior", {
      action: "replace",
      href: "/hv/menu/close/",
      target: "side-menu-host",
      trigger: "press",
    });
    home.appendChild(close);

    expect(DomHelpers.getBehaviorElements(home)).toEqual([home, close]);
  });
});
