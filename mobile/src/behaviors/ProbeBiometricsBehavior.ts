import type { HvBehavior } from "hyperview";
import { getElementById } from "hyperview/src/services/dom";
import { shallowCloneToRoot } from "hyperview/src/services";
import { HYPERVIEW } from "hyperview/src/services/namespaces";

import {
  hasEnrolledBiometrics,
  preferredBiometricIcon,
  readToken,
} from "../biometrics/store";

// The matching HXML <behavior> MUST carry once="true". updateRoot below goes through
// shallowCloneToRoot, which clones every ancestor up to the document, so every
// hyper-ref on the screen changes identity and re-fires its trigger="load" behaviors
// (hyperview/src/components/hyper-ref/hyper-ref.tsx:68-79). Without once="true" this
// probe re-triggers itself forever.
const ProbeBiometricsBehavior: HvBehavior = {
  action: "probe-biometrics",
  callback: async (element, _onUpdate, getRoot, updateRoot) => {
    try {
      if (!(await hasEnrolledBiometrics())) {
        return;
      }
      // Deliberately only reveals; it NEVER pre-selects the enrolment switch. The
      // stored token identifies a device, not a person, so on a shared phone the
      // residue of the previous account would silently enrol whoever signs in next.
      // Opting in stays an act the user performs.
      const reveal = (id: string | null): Element | null => {
        const target = id ? getElementById(getRoot(), id) : null;
        target?.setAttribute("hide", "false");
        return target ?? null;
      };
      let mutated = reveal(element.getAttribute("available-target"));
      if (await readToken()) {
        const button = reveal(element.getAttribute("token-target"));
        mutated = button ?? mutated;
        if (button) {
          // The glyphs carry no id, because on Android an id would become their
          // accessibility label and bury the alt copy, so they are found by
          // traversal and told apart by @variant. Only touched here: a hidden
          // button has no glyph to choose.
          const wanted = await preferredBiometricIcon();
          Array.from(button.getElementsByTagNameNS(HYPERVIEW, "image")).forEach(
            (icon) => {
              const shown = icon.getAttribute("variant") === wanted;
              icon.setAttribute("hide", shown ? "false" : "true");
              if (shown) {
                mutated = icon;
              }
            },
          );
        }
      }
      if (mutated) {
        // One updateRoot covers every mutation above: shallowClone MOVES sibling
        // nodes onto the clone, so the earlier reveals are still in the tree it
        // produces. Cloning from the chosen glyph keeps the whole path fresh.
        updateRoot(shallowCloneToRoot(mutated));
      }
    } catch {
      // A missing or failing native module must never break password sign-in.
    }
  },
};

export default ProbeBiometricsBehavior;
