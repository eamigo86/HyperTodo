import { DOMParser } from "@instawork/xmldom";
import { createProps } from "hyperview/src/services";
import { createStylesheets } from "hyperview/src/services/stylesheets";
import type { HvComponentOptions, StyleSheets } from "hyperview/src/types";

// The mobile tsconfig deliberately excludes Node globals. Keep these test-only
// filesystem signatures local instead of changing application compiler settings.
declare const __dirname: string;
const readFileSync = require("node:fs").readFileSync as (path: string, encoding: "utf8") => string;
const resolve = require("node:path").resolve as (...paths: string[]) => string;

const root = resolve(__dirname, "../../backend");
const hashes = JSON.parse(readFileSync(resolve(root, "tests/fixtures/schema_style_hashes.json"), "utf8"));
const ns = "https://hyperview.org/hyperview";
const parse = (source: string) => new DOMParser().parseFromString(source, "application/xml") as unknown as Document;

// Python tests pin every original stylesheet byte and render real contexts.
// This checks the ACTUAL pinned native stylesheet parser, including modifiers,
// on both ownership structures with identical synthetic dynamic values.
describe("schema normalization on the unchanged Hyperview host", () => {
  it.each(Object.keys(hashes))("preserves stylesheet parser output for %s", (name) => {
    const source = readFileSync(resolve(root, "hyperview", name), "utf8");
    expect(source.indexOf("<screen")).toBeLessThan(source.indexOf("<styles>"));
    const stylesheet = source.match(/<styles>[\s\S]*?<\/styles>/)![0]
      .replace(/\{%[\s\S]*?%\}/g, "")
      .replace(/\{\{[\s\S]*?\}\}/g, "10");
    const legacy = parse(`<doc xmlns="${ns}">${stylesheet}<screen><body/></screen></doc>`);
    const normalized = parse(`<doc xmlns="${ns}"><screen>${stylesheet}<body/></screen></doc>`);
    const expected = createStylesheets(legacy);
    expect(Object.keys(expected).length).toBeGreaterThan(0);
    expect(createStylesheets(normalized)).toEqual(expected);
  });

  it("preserves typed string accessibility props and proves boolean forwarding is not support", () => {
    const sheet = {} as StyleSheets;
    const options = {} as HvComponentOptions;
    const original = parse(`<text xmlns="${ns}" accessibilityElementsHidden="true" accessible="false"/>`).documentElement;
    expect(createProps(original, sheet, options).accessibilityElementsHidden).toBe("true");
    expect(createProps(original, sheet, options).accessible).toBe("false");
    const doc = parse(`<text xmlns="${ns}" accessibilityRole="button" accessibilityLabel="English, current language"><text accessibilityRole="none"><text importantForAccessibility="no">🇬🇧</text> English</text></text>`);
    const label = doc.documentElement;
    const content = label.firstChild as Element;
    const flag = content.firstChild as Element;
    expect(createProps(label, sheet, options).accessibilityLabel).toBe("English, current language");
    expect(createProps(label, sheet, options).accessibilityRole).toBe("button");
    expect(createProps(content, sheet, options).accessibilityRole).toBe("none");
    expect(createProps(flag, sheet, options).importantForAccessibility).toBe("no");
    expect(createProps(flag, sheet, options).accessibilityElementsHidden).toBeUndefined();
    expect(createProps(flag, sheet, options).accessibilityLabel).toBeUndefined();
  });
});
