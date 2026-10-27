import { DOMParser } from "@instawork/xmldom";
import { render } from "@testing-library/react-native";
import HvOption from "hyperview/src/elements/hv-option";
import React from "react";

jest.mock("react-native-webview", () => ({ WebView: () => null }));

it.each([true, false])("exposes the actual Hyperview option selected state (%s)", selected => {
  const doc = new DOMParser().parseFromString(
    `<option xmlns="https://hyperview.org/hyperview" id="choice" selected="${selected}"><text>Choice</text></option>`,
    "application/xml",
  );
  const screen = render(
    <HvOption
      element={doc.documentElement as never}
      onUpdate={jest.fn()}
      options={{} as never}
      stylesheets={{} as never}
    />,
  );

  expect(screen.getByTestId("choice").props.accessibilityState).toEqual({ selected });
});
