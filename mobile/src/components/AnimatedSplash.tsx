import * as SplashScreen from "expo-splash-screen";
import LottieView from "lottie-react-native";
import React, { useEffect, useRef, useState } from "react";
import { AccessibilityInfo, StyleSheet, View } from "react-native";

type Props = {
  children: React.ReactNode;
};

// The animation runs for about one second; reveal the app even if Lottie never reports back.
const FAILSAFE_MS = 2500;

function hideNativeSplash(): void {
  Promise.resolve(SplashScreen.hideAsync()).catch(() => undefined);
}

export default function AnimatedSplash({ children }: Props): React.JSX.Element {
  const [finished, setFinished] = useState(false);
  const player = useRef<LottieView>(null);
  const started = useRef(false);

  useEffect(() => {
    if (finished) {
      // Idempotent safety net: the native splash must never outlive the overlay.
      hideNativeSplash();
      return undefined;
    }
    const timer = setTimeout(() => setFinished(true), FAILSAFE_MS);
    return () => clearTimeout(timer);
  }, [finished]);

  useEffect(() => {
    let cancelled = false;
    Promise.resolve()
      .then(() => AccessibilityInfo.isReduceMotionEnabled())
      .then((reduceMotion) => {
        if (reduceMotion && !cancelled) {
          setFinished(true);
        }
      })
      .catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, []);

  const handleLayout = (): void => {
    if (started.current) {
      return;
    }
    started.current = true;
    hideNativeSplash();
    player.current?.play();
  };

  return (
    <View style={styles.container}>
      <View
        accessibilityElementsHidden={!finished}
        importantForAccessibility={finished ? "auto" : "no-hide-descendants"}
        style={styles.content}
      >
        {children}
      </View>
      {!finished ? (
        <View
          accessibilityLabel="HyperTodo splash"
          accessibilityViewIsModal
          onLayout={handleLayout}
          style={styles.overlay}
          testID="animated-splash"
        >
          <LottieView
            autoPlay={false}
            loop={false}
            onAnimationFailure={() => setFinished(true)}
            onAnimationFinish={() => setFinished(true)}
            ref={player}
            resizeMode="contain"
            source={require("../../assets/splash.json")}
            style={styles.lottie}
          />
        </View>
      ) : null}
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
  },
  content: {
    flex: 1,
  },
  overlay: {
    ...StyleSheet.absoluteFill,
    alignItems: "center",
    backgroundColor: "#F7F8FC",
    justifyContent: "center",
  },
  lottie: {
    height: 180,
    width: 180,
  },
});
