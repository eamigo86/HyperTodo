import { decorateOperationHref, readOperationUrl, nextCounter } from "../src/realtime/operation";

const token = "g0-1-0-1";

it("preserves raw canonical query spelling and duplicates through decoration and stripping", () => {
  const href = "https://hypertodo.test/hv/tasks/?q=a%20b&q=a+b&path=%2f%2F&empty=";
  const tagged = decorateOperationHref(href, token);
  expect(tagged).toBe(href + "&__djhv_op=" + token);
  expect(readOperationUrl(tagged + "&title=a%26b&title=two")).toEqual({
    token, canonicalUrl: href + "&title=a%26b&title=two", prefix: href,
  });
});

it.each(["https://hypertodo.test/path", "https://hypertodo.test/path?", "https://hypertodo.test/path?a=1&"])("round trips the exact original query delimiters: %s", (href) => {
  expect(readOperationUrl(decorateOperationHref(href, token)).canonicalUrl).toBe(href);
});

it.each(["", "g0-0-0-1", "g0-1--1-1", "g0-1-01-1", "g0-1-0-0", "g0-1000000000-0-1", "g0-1-0-1000000000", "false"])("rejects malformed operation tokens: %s", value => {
  expect(() => readOperationUrl("https://hypertodo.test/?__djhv_op=" + value)).toThrow("invalid-operation-token");
});

it.each(["__djhv_op", "%5f%5fdjhv_op"])("rejects an existing reserved key without overwriting it: %s", key => {
  expect(() => decorateOperationHref("/hv/tasks/?" + key + "=user-data", token)).toThrow("reserved-parameter");
});

it("rejects duplicate tokens even when their values match", () => {
  expect(() => readOperationUrl("https://hypertodo.test/?__djhv_op=" + token + "&%5f%5fdjhv_op=" + token)).toThrow("duplicate-operation-token");
});

it("rejects remote fragments with a hash rather than misplacing serialized form fields", () => {
  expect(() => decorateOperationHref("/hv/tasks/?q=one#section", token)).toThrow("unsupported-href");
});


it("allocates the last bounded counter exactly once without wrapping", () => {
  expect(nextCounter(999999998)).toBe(999999999);
  expect(() => nextCounter(999999999)).toThrow("counter-exhausted");
  expect(() => nextCounter(Number.MAX_SAFE_INTEGER)).toThrow("counter-exhausted");
});

it.each([-1, 0.5, NaN, Infinity])("rejects invalid internal counter state: %s", state => {
  expect(() => nextCounter(state)).toThrow("counter-exhausted");
});
