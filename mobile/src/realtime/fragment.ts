import type {HvComponentOptions} from "hyperview";

/** Locate a target in the live tree, not an obsolete ownerDocument pointer. */
export function findTarget(boundary: Element, origin: Element, options: HvComponentOptions): Element | null {
  let root: Node = boundary;
  while (root.parentNode) root = root.parentNode;
  const nodes = Array.from((root as Document).getElementsByTagName("*"));
  if (options.targetId) {
    const target = nodes.find(node=>node.getAttribute("id")===options.targetId);
    if (target) return target;
  }
  if (options.behaviorElement && nodes.includes(options.behaviorElement)) return options.behaviorElement.parentNode as Element;
  return nodes.includes(origin) ? origin : null;
}

/** Prepare one public swap, preserving unchanged child identities and structure. */
export function fragmentReplacement(target: Element, source: Element, action: string): Element {
  if (action === "replace") return source;
  if (action !== "append") throw new Error("Unsupported owned fragment action");
  const replacement = target.cloneNode(false) as Element;
  for (const child of Array.from(target.childNodes)) replacement.appendChild(child);
  replacement.appendChild(source);
  return replacement;
}
