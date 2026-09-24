import React, { useEffect, useState } from "react";
import type { RefreshControlProps } from "react-native";
import { RefreshControl } from "react-native";

import { subscribeToNetworkFailures } from "../feedback/failure";
import { THEME_TOKENS, useThemeName } from "../theme";

// Hyperview 0.111.0 runs list onEnd after a failed fragment fetch. Keep this
// app-owned failure guard for other failure paths and the themed native spinner;
// mounted regressions verify the SDK cleanup without depending on this wrapper.
export default function OfflineRefreshControl({
  onRefresh,
  refreshing,
  ...rest
}: RefreshControlProps): React.JSX.Element {
  const [failed, setFailed] = useState(false);
  const t = THEME_TOKENS[useThemeName()];
  useEffect(() => subscribeToNetworkFailures(() => setFailed(true)), []);

  // hv-list renders `<RefreshControl onRefresh refreshing />` and nothing else
  // (hv-list/index.tsx:263), so this wrapper is the only place the spinner can be
  // told about the palette. Without it Android draws its default white puck on the
  // #0F1118 canvas on every pull. `colors` and `progressBackgroundColor` are
  // Android, `tintColor` is iOS; all three are inert on the other platform. They
  // sit before the spread so a caller that ever passes its own still wins.
  return (
    <RefreshControl
      colors={[t.brand_ink]}
      progressBackgroundColor={t.surface}
      tintColor={t.spinner}
      {...rest}
      onRefresh={() => {
        setFailed(false);
        onRefresh?.();
      }}
      refreshing={refreshing && !failed}
    />
  );
}
