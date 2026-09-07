import React, { useEffect, useState } from "react";
import type { RefreshControlProps } from "react-native";
import { RefreshControl } from "react-native";

import { subscribeToNetworkFailures } from "../feedback/failure";
import { THEME_TOKENS, useThemeName } from "../theme";

// ponytail: hyperview 0.110 never runs a list's `onEnd` callback when a fragment fetch
// fails -- hyperview.tsx:203 returns null on error and :406-408 reads null as a dropped
// sync request and bails early -- so hv-list's own `refreshing` state (hv-list/index.tsx:35)
// stays true forever and the pull-to-refresh spinner freezes. The `refreshControl` prop is
// the only app-side lever over that state. Delete this wrapper once upstream clears
// `refreshing` on failure.
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
