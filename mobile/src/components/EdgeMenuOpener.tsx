import type { HvComponentProps } from "hyperview";
import { createStyleProp } from "hyperview";
import React, { useMemo } from "react";
import { PanResponder, View } from "react-native";

const COMPONENT_NAMESPACE = "https://hypertodo.app/components";
const CLAIM_DISTANCE = 8;
const OPEN_DISTANCE = 48;

function EdgeMenuOpenerComponent({
  element,
  onUpdate,
  options,
  stylesheets,
}: HvComponentProps): React.JSX.Element {
  const panResponder = useMemo(
    () =>
      PanResponder.create({
        onMoveShouldSetPanResponder: (_event, gesture) =>
          gesture.dx > CLAIM_DISTANCE && gesture.dx > Math.abs(gesture.dy),
        onMoveShouldSetPanResponderCapture: (_event, gesture) =>
          gesture.dx > CLAIM_DISTANCE && gesture.dx > Math.abs(gesture.dy),
        onPanResponderRelease: (_event, gesture) => {
          if (gesture.dx < OPEN_DISTANCE || gesture.dx <= Math.abs(gesture.dy)) {
            return;
          }
          const href = element.getAttribute("href") ?? "/hv/menu/?active=dashboard";
          const targetId = element.getAttribute("target") ?? "side-menu-host";
          onUpdate(href, "replace", element, { targetId, verb: "get" });
        },
        onPanResponderTerminationRequest: () => false,
      }),
    [element, onUpdate],
  );

  return (
    <View
      accessible={false}
      style={createStyleProp(element, stylesheets, options)}
      testID={element.getAttribute("id") ?? undefined}
      {...panResponder.panHandlers}
    />
  );
}

const EdgeMenuOpener = Object.assign(EdgeMenuOpenerComponent, {
  localName: "edge-menu-opener",
  namespaceURI: COMPONENT_NAMESPACE,
});

export default EdgeMenuOpener;
