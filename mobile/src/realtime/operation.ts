/** App-owned fragment correlation; never use this parameter for navigation. */
export const OPERATION_PARAMETER = "__djhv_op";
const TOKEN = /^g0-[1-9][0-9]{0,8}-(0|[1-9][0-9]{0,8})-[1-9][0-9]{0,8}$/;

function queryParts(value: string) {
  const hash = value.indexOf("#");
  if (hash !== -1) throw new Error("unsupported-href");
  const question = value.indexOf("?");
  return {base: question === -1 ? value : value.slice(0, question), parts: question === -1 ? [] : value.slice(question + 1).split("&")};
}

function reserved(part: string): boolean {
  const key = part.split("=", 1)[0];
  try { return decodeURIComponent(key.replace(/\+/g, " ")) === OPERATION_PARAMETER; }
  catch { return false; }
}

/** Add a token without rewriting query spelling, order or duplicate values. */
export function decorateOperationHref(href: string, token: string): string {
  const {parts} = queryParts(href);
  if (!TOKEN.test(token)) throw new Error("invalid-operation-token");
  if (parts.some(reserved)) throw new Error("reserved-parameter");
  return href + (href.includes("?") ? "&" : "?") + OPERATION_PARAMETER + "=" + token;
}

/** Remove exactly one valid token while preserving every other query segment. */
export function readOperationUrl(url: string): {token: string | null; canonicalUrl: string; prefix: string} {
  const {base, parts} = queryParts(url);
  const matches = parts.map((part,index) => reserved(part) ? index : -1).filter(index => index >= 0);
  if (!matches.length) return {token:null,canonicalUrl:url,prefix:url};
  if (matches.length !== 1) throw new Error("duplicate-operation-token");
  const index = matches[0];
  const raw = parts[index].slice(parts[index].indexOf("=") + 1);
  if (!TOKEN.test(raw)) throw new Error("invalid-operation-token");
  const before = parts.slice(0,index);
  const remaining = parts.filter((_part,position) => position !== index);
  return {token:raw,canonicalUrl:base + (remaining.length ? "?" + remaining.join("&") : ""),prefix:base + (before.length ? "?" + before.join("&") : "")};
}

/** Reject app form fields that collide with the reserved protocol namespace. */
export function hasReservedBody(body: RequestInit["body"]): boolean {
  if (!body || typeof body !== "object") return false;
  const form = body as {getParts?: () => {fieldName: string}[]; entries?: () => IterableIterator<[string, unknown]>};
  if (typeof form.getParts === "function") return form.getParts().some(part => part.fieldName === OPERATION_PARAMETER);
  if (typeof form.entries === "function") return Array.from(form.entries()).some(([key]) => key === OPERATION_PARAMETER);
  return false;
}

/** Advance internal bounded identity state; never wrap or silently reuse it. */
export function nextCounter(current: number): number {
  if (!Number.isSafeInteger(current) || current < 0 || current >= 999999999) throw new Error("counter-exhausted");
  return current + 1;
}
