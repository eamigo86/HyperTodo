import { ImageManipulator, SaveFormat } from "expo-image-manipulator";
import * as ImagePicker from "expo-image-picker";
import type { HvBehavior } from "hyperview";
import { getElementById } from "hyperview/src/services/dom";
import { shallowCloneToRoot } from "hyperview/src/services";

import { hyperviewLogger } from "../feedback/logging";
import { publishSnackbar } from "../feedback/snackbar";

// No file part can cross a Hyperview form: the component registry serialises a
// field's `value` ATTRIBUTE as a string and has no file path at all, so this
// behavior's whole job is to turn a picked photo into base64 text and write it
// into a hidden <text-field> that the screen's own Save button then posts.
//
// It posts NOTHING itself. The photo used to have its own endpoint and its own
// 422 on a screen that also held an unsaved profile form, so a user could pick a
// photo, mistype an email, tap Save, and get the photo stored and the email
// refused with nothing on screen saying which half had happened.
//
// The 512px cap is not cosmetic. The base64 rides in a form FIELD, and Django
// counts non-file field bytes against DATA_UPLOAD_MAX_MEMORY_SIZE (2.5MB) before
// any view runs; over that it answers with a plain-HTML 400 the client cannot even
// parse. A full-resolution iPhone JPEG base64s to 2.7-6.7MB. At 512/q0.8 it is
// 55-120KB.
const RESIZE_WIDTH = 512;
// JPEG is required, not preferred: Pillow ships no HEIF decoder, so an unconverted
// iPhone photo would be refused server-side as "not an image".
const JPEG_QUALITY = 0.8;

// User-facing, so no error codes and no native vocabulary.
const PICK_FAILED = "Couldn't open your photos. Try again in a moment.";
// The ONLY feedback a screen reader gets for a successful pick. The preview image
// deliberately carries no `alt`, and React Native only makes an Image an
// accessibility node when alt is present (Image.android.js:272-276), so revealing
// it while hiding avatar-current leaves the photo row with zero accessible nodes
// where it had just announced the stored photo or the initials. It also has to say
// that nothing is saved yet, because that is exactly what a pick does not do.
const PICK_READY = "Photo ready. Tap Save settings to keep it.";

// Deliberately NOT once="true" in the HXML: the user must be able to pick again
// after cancelling, or after a refusal.
const PickAvatarBehavior: HvBehavior = {
  action: "pick-avatar",
  callback: async (element, _onUpdate, getRoot, updateRoot) => {
    try {
      const result = await ImagePicker.launchImageLibraryAsync({
        mediaTypes: ["images"],
        // The picker's own editor makes the crop square, which is the shape the
        // server stores and every disc in the app draws.
        allowsEditing: true,
        aspect: [1, 1],
        // Full quality out of the picker; the single compression happens below, so
        // the image is never encoded lossily twice.
        quality: 1,
        // The server strips EXIF anyway. Not asking for it means the GPS
        // coordinates of the photo never enter this process in the first place.
        exif: false,
      });
      if (result.canceled) {
        return;
      }
      const rendered = await ImageManipulator.manipulate(result.assets[0].uri)
        // Width only: allowsEditing already made it square, and passing both axes
        // would stretch anything that is not.
        .resize({ width: RESIZE_WIDTH })
        .renderAsync();
      const { base64 } = await rendered.saveAsync({
        format: SaveFormat.JPEG,
        compress: JPEG_QUALITY,
        base64: true,
      });
      const root = getRoot();
      const field = getElementById(root, element.getAttribute("target") ?? "");
      if (!base64 || !field) {
        return;
      }
      // getNameValueFormInputValues reads the `value` ATTRIBUTE, so this is exactly
      // what the Save button serialises into the POST.
      field.setAttribute("value", base64);
      // The preview, so the pick is visible before it is saved. urlParse round
      // trips a data: URI unchanged (the base64 alphabet carries no ? or #), and
      // HvImage hands React Native {uri: 'data:image/jpeg;base64,...'} intact.
      // Always image/jpeg because the encode above always produces one.
      const preview = getElementById(
        root,
        element.getAttribute("preview-target") ?? "",
      );
      if (preview) {
        preview.setAttribute("source", `data:image/jpeg;base64,${base64}`);
        preview.setAttribute("hide", "false");
      }
      const current = getElementById(
        root,
        element.getAttribute("current-target") ?? "",
      );
      current?.setAttribute("hide", "true");
      // ONE update for all three. shallowClone MOVES the existing children into
      // the clone by reference (services/index.ts:179-188) and shallowCloneToRoot
      // only replaces the ancestors on the field's own path, so the writes to the
      // two sibling subtrees ride along.
      updateRoot(shallowCloneToRoot(field));
      publishSnackbar({ message: PICK_READY, tone: "success" });
    } catch (error) {
      hyperviewLogger.warn("avatar pick failed:", error);
      publishSnackbar({ message: PICK_FAILED, tone: "error" });
    }
  },
};

export default PickAvatarBehavior;
