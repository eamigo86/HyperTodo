import { DOMParser } from "@instawork/xmldom";
import * as ImageManipulator from "expo-image-manipulator";
import * as ImagePicker from "expo-image-picker";
import * as Events from "hyperview/src/services/events";

import PickAvatarBehavior from "../src/behaviors/PickAvatarBehavior";
import { hyperviewLogger } from "../src/feedback/logging";
import { subscribeToSnackbars } from "../src/feedback/snackbar";
import type { SnackbarNotice } from "../src/feedback/snackbar";

jest.mock("expo-image-picker", () => ({ launchImageLibraryAsync: jest.fn() }));

// The chain is what the SDK 57 module actually exposes: manipulateAsync is
// deprecated in favour of ImageManipulator.manipulate(uri).resize().renderAsync()
// followed by ImageRef.saveAsync(). Mocking it as a chain is what would break if a
// future SDK moves it back.
const saveAsync = jest.fn();
const renderAsync = jest.fn();
const resize = jest.fn();
jest.mock("expo-image-manipulator", () => ({
  ImageManipulator: { manipulate: jest.fn() },
  SaveFormat: { JPEG: "jpeg", PNG: "png", WEBP: "webp" },
}));

const mockPicker = ImagePicker as jest.Mocked<typeof ImagePicker>;
const mockManipulator = ImageManipulator.ImageManipulator as unknown as {
  manipulate: jest.Mock;
};

// The nesting the backend actually ships, not a flattened stand-in: the two mutated
// siblings sit two levels down inside avatar-panel > avatar-row, and the hidden
// field is their uncle. That depth is the whole point of the multi-subtree
// assertion below, since shallowCloneToRoot only replaces the ancestors on the
// field's own path. There is no <form> of its own any more: the hidden field is a
// member of settings-form and the Save button is the only thing that posts it.
const PANEL = `<view xmlns="https://hyperview.org/hyperview" id="settings-form-panel">
  <form id="settings-form">
    <view style="card">
      <text style="section">Photo</text>
      <view id="avatar-panel">
        <view style="avatar-row">
          <view id="avatar-current"><image style="avatar-disc avatar-disc-row" /></view>
          <image id="avatar-preview" hide="true" style="avatar-disc avatar-disc-row" />
          <view style="avatar-action"><text style="avatar-action-text">Choose photo</text></view>
        </view>
      </view>
      <text-field hide="true" id="avatar-data" name="avatar_data" value="" />
      <text style="meta">Your photo is saved when you tap Save settings.</text>
    </view>
  </form>
</view>`;

function panel(): Document {
  return new DOMParser().parseFromString(PANEL, "application/xml") as Document;
}

function behaviorElement(attributes: Record<string, string>): Element {
  return { getAttribute: (name: string) => attributes[name] ?? null } as Element;
}

const button = behaviorElement({
  target: "avatar-data",
  "preview-target": "avatar-preview",
  "current-target": "avatar-current",
});

function picked(uri = "file:///tmp/photo.heic") {
  return { canceled: false, assets: [{ uri }] };
}

async function run(doc: Document, element: Element = button) {
  const updateRoot = jest.fn();
  await PickAvatarBehavior.callback(element, jest.fn(), () => doc, updateRoot);
  return updateRoot;
}

function valueOf(doc: Document): string | null {
  return (doc.getElementById("avatar-data") as Element).getAttribute("value");
}

function attrOf(doc: Document, id: string, name: string): string | null {
  return (doc.getElementById(id) as Element).getAttribute(name);
}

let dispatch: jest.SpyInstance;
let notices: SnackbarNotice[];
let unsubscribe: () => void;

beforeEach(() => {
  jest.clearAllMocks();
  resize.mockReturnValue({ renderAsync });
  renderAsync.mockResolvedValue({ saveAsync });
  saveAsync.mockResolvedValue({ base64: "AAAAencodedAAAA" });
  mockManipulator.manipulate.mockReturnValue({ resize });
  dispatch = jest.spyOn(Events, "dispatch").mockImplementation(() => undefined);
  jest.spyOn(hyperviewLogger, "warn").mockImplementation(() => undefined);
  notices = [];
  unsubscribe = subscribeToSnackbars((notice) => notices.push(notice));
});

afterEach(() => {
  dispatch.mockRestore();
  unsubscribe();
});

describe("pick-avatar", () => {
  it("registers the action name the backend HXML names", () => {
    // Rule 11: an unknown action does nothing SILENTLY, so this string is the whole
    // contract between fragments/avatar_panel.xml and this file.
    expect(PickAvatarBehavior.action).toBe("pick-avatar");
  });

  it("arms the field and shows the preview in ONE update, and posts nothing", async () => {
    // The photo is a pending FIELD now, not a request. Three setAttribute writes
    // across two unrelated subtrees survive one shallowCloneToRoot, because
    // shallowClone MOVES the existing children into the clone by reference
    // (services/index.ts:179-188) and only the ancestors on one path are
    // replaced, so everything off that path keeps its mutations.
    mockPicker.launchImageLibraryAsync.mockResolvedValue(picked() as never);

    const updateRoot = await run(panel());

    expect(updateRoot).toHaveBeenCalledTimes(1);
    const newRoot = updateRoot.mock.calls[0][0] as Document;
    // getNameValueFormInputValues serialises the `value` ATTRIBUTE, which is what
    // the Save button posts.
    expect(valueOf(newRoot)).toBe("AAAAencodedAAAA");
    expect(attrOf(newRoot, "avatar-preview", "source")).toBe(
      "data:image/jpeg;base64,AAAAencodedAAAA",
    );
    expect(attrOf(newRoot, "avatar-preview", "hide")).toBe("false");
    expect(attrOf(newRoot, "avatar-current", "hide")).toBe("true");
    // Nothing is dispatched and nothing is posted: the pick writes to the DOM and
    // stops there.
    expect(dispatch).not.toHaveBeenCalled();
  });

  it("says the photo is ready, because the preview announces nothing", async () => {
    // Hiding avatar-current removes the only accessible node in the row: the
    // preview carries no `alt`, and React Native only makes an Image an
    // accessibility node when alt is present (Image.android.js:272-276). Without
    // this a screen-reader user has no way to know the pick landed until after
    // they commit, and the caption cannot help -- it says what Save will do, not
    // that a pick happened.
    mockPicker.launchImageLibraryAsync.mockResolvedValue(picked() as never);

    await run(panel());

    expect(notices).toHaveLength(1);
    expect(notices[0].tone).toBe("success");
    // It must not claim the photo is stored: nothing is written until Save.
    expect(notices[0].message).toMatch(/Save settings/);
  });

  it("still arms the field when the panel ships no preview targets at all", async () => {
    // preview-target and current-target are ATTRIBUTES, and rule 9 makes an
    // unknown attribute inert rather than fatal. A 1.2.0 binary that has not
    // taken this JS update ignores them and still writes the base64, so Save
    // still stores the photo and only the preview is missing. The converse has to
    // hold too: this build must not require them.
    mockPicker.launchImageLibraryAsync.mockResolvedValue(picked() as never);

    const updateRoot = await run(
      panel(),
      behaviorElement({ target: "avatar-data" }),
    );

    expect(updateRoot).toHaveBeenCalledTimes(1);
    expect(valueOf(updateRoot.mock.calls[0][0] as Document)).toBe(
      "AAAAencodedAAAA",
    );
  });

  it("always re-encodes to JPEG, because the server has no HEIF decoder at all", async () => {
    // Pillow 12's OPEN registry has 43 formats and no HEIF entry, so an iPhone HEIC
    // is rejected as "not an image". This conversion is required, not cosmetic.
    mockPicker.launchImageLibraryAsync.mockResolvedValue(picked() as never);

    await run(panel());

    expect(saveAsync).toHaveBeenCalledWith(
      expect.objectContaining({ format: "jpeg", base64: true }),
    );
  });

  it("resizes by width alone so a crop is never stretched", async () => {
    // Passing width AND height to resize distorts anything that is not already
    // square. The picker's own 1:1 crop decides the shape; this only bounds it.
    mockPicker.launchImageLibraryAsync.mockResolvedValue(picked() as never);

    await run(panel());

    expect(resize).toHaveBeenCalledWith({ width: 512 });
  });

  it("asks only for images, and never for the EXIF that rides with them", async () => {
    mockPicker.launchImageLibraryAsync.mockResolvedValue(picked() as never);

    await run(panel());

    expect(mockPicker.launchImageLibraryAsync).toHaveBeenCalledWith(
      expect.objectContaining({ mediaTypes: ["images"], exif: false }),
    );
  });

  it("does nothing at all when the user backs out of the picker", async () => {
    mockPicker.launchImageLibraryAsync.mockResolvedValue({
      canceled: true,
      assets: null,
    } as never);

    const updateRoot = await run(panel());

    expect(updateRoot).not.toHaveBeenCalled();
    expect(dispatch).not.toHaveBeenCalled();
    // Cancelling is a decision the user just made. Narrating it back is noise.
    expect(notices).toEqual([]);
  });

  it("says something when the picker fails, rather than looking dead", async () => {
    mockPicker.launchImageLibraryAsync.mockRejectedValue(new Error("no photos"));

    const updateRoot = await run(panel());

    expect(updateRoot).not.toHaveBeenCalled();
    expect(dispatch).not.toHaveBeenCalled();
    expect(notices).toHaveLength(1);
    expect(notices[0].tone).toBe("error");
    // Never the raw error: it is developer text and this is the most visible copy.
    expect(notices[0].message).not.toMatch(/no photos/);
  });

  it("posts nothing when the encoder hands back no data", async () => {
    mockPicker.launchImageLibraryAsync.mockResolvedValue(picked() as never);
    saveAsync.mockResolvedValue({});

    const updateRoot = await run(panel());

    expect(updateRoot).not.toHaveBeenCalled();
    expect(dispatch).not.toHaveBeenCalled();
  });

  it("is a silent no-op when the target field is not on this screen", async () => {
    mockPicker.launchImageLibraryAsync.mockResolvedValue(picked() as never);

    const updateRoot = await run(panel(), behaviorElement({ target: "missing" }));

    expect(updateRoot).not.toHaveBeenCalled();
    expect(dispatch).not.toHaveBeenCalled();
    expect(notices).toEqual([]);
  });
});
