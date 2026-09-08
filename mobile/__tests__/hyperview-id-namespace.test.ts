import { DOMParser } from "@instawork/xmldom";
import * as Dom from "hyperview/src/services/dom";

// This is why the backend forbids a <style id> from equalling an element id
// (backend/tests/test_fragment_contract.py,
// test_no_style_id_is_also_an_element_id_anywhere_in_the_app).
//
// Hyperview resolves every behavior `target` with Dom.getElementById
// (hyperview.tsx:413), which delegates to xmldom's getElementById: a depth-first
// FIRST match over ONE shared id namespace. A screen emits <styles> before
// <screen>, so a colliding style id always wins, and `replace target="x"` splices
// the new content INSIDE <styles> instead of over the rendered element -- with no
// error, because UpdateMissingTargetError only fires when NOTHING matches.
//
// If a future hyperview release makes this test fail -- namespaced style ids, a
// styles-aware lookup -- the backend guard can be relaxed.
const DOCUMENT = `<doc xmlns="https://hyperview.org/hyperview">
  <styles>
    <style id="x" flex="1" />
  </styles>
  <screen>
    <body>
      <view id="x" />
    </body>
  </screen>
</doc>`;

describe("hyperview id namespace", () => {
  it("resolves a target to the <style> that shares the element's id", () => {
    const doc = new DOMParser().parseFromString(
      DOCUMENT,
      "application/xml",
    ) as unknown as Document;

    const found = Dom.getElementById(doc, "x");

    expect(found).not.toBeNull();
    expect(found?.localName).toBe("style");
  });
});
