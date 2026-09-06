import type { HvComponentProps } from "hyperview";
import { createStyleProp, renderChildren } from "hyperview";
import React, { useCallback, useMemo, useRef, useState } from "react";
import { Alert, Animated, Easing, PanResponder, Pressable, StyleSheet, Text, View } from "react-native";

const COMPONENT_NAMESPACE = "https://hypertodo.app/components";
const EDIT_ACTION_WIDTH = 68;
const TOGGLE_ACTION_WIDTH = 96;
const DELETE_ACTION_WIDTH = 70;
const ACTIONS_WIDTH = EDIT_ACTION_WIDTH + TOGGLE_ACTION_WIDTH + DELETE_ACTION_WIDTH;
const SWIPE_THRESHOLD = 44;
const ANIMATION_DURATION = 160;

type UpdateAction = "new" | "replace";
type UpdateVerb = "get" | "post";

function SwipeTaskRowComponent({
  element,
  onUpdate,
  options,
  stylesheets,
}: HvComponentProps): React.JSX.Element {
  const completed = element.getAttribute("completed") === "true";
  const rootStyle = createStyleProp(element, stylesheets, options);
  const children = renderChildren(element, stylesheets, onUpdate, options);
  const [actionsOpen, setActionsOpen] = useState(false);
  const actionsTranslateX = useRef(new Animated.Value(ACTIONS_WIDTH)).current;

  const animateActions = useCallback(
    (open: boolean): void => {
      setActionsOpen(open);
      Animated.timing(actionsTranslateX, {
        duration: ANIMATION_DURATION,
        easing: Easing.out(Easing.cubic),
        toValue: open ? 0 : ACTIONS_WIDTH,
        useNativeDriver: true,
      }).start();
    },
    [actionsTranslateX],
  );

  const update = useCallback(
    (hrefAttribute: string, action: UpdateAction, verb: UpdateVerb): void => {
      const href = element.getAttribute(hrefAttribute);
      if (!href) {
        return;
      }
      const targetId = action === "replace" ? element.getAttribute("id") : null;
      onUpdate(href, action, element, {
        ...(targetId ? { targetId } : {}),
        verb,
      });
    },
    [element, onUpdate],
  );

  const panResponder = useMemo(
    () =>
      PanResponder.create({
        onMoveShouldSetPanResponder: (_event, gesture) =>
          Math.abs(gesture.dx) > 8 && Math.abs(gesture.dx) > Math.abs(gesture.dy),
        onMoveShouldSetPanResponderCapture: (_event, gesture) =>
          Math.abs(gesture.dx) > 8 && Math.abs(gesture.dx) > Math.abs(gesture.dy),
        onPanResponderGrant: () => actionsTranslateX.stopAnimation(),
        onPanResponderMove: (_event, gesture) => {
          const origin = actionsOpen ? 0 : ACTIONS_WIDTH;
          const nextPosition = Math.max(
            0,
            Math.min(ACTIONS_WIDTH, origin + gesture.dx),
          );
          actionsTranslateX.setValue(nextPosition);
        },
        onPanResponderRelease: (_event, gesture) => {
          const shouldOpen = actionsOpen
            ? gesture.dx <= SWIPE_THRESHOLD
            : gesture.dx < -SWIPE_THRESHOLD;
          animateActions(shouldOpen);
        },
        onPanResponderTerminate: () => animateActions(actionsOpen),
        onPanResponderTerminationRequest: () => false,
      }),
    [actionsOpen, actionsTranslateX, animateActions],
  );

  return (
    <View
      style={[rootStyle, styles.root]}
      testID={element.getAttribute("id") ?? undefined}
      {...panResponder.panHandlers}
    >
      <View
        style={[styles.content, actionsOpen && styles.contentOpen]}
        testID="task-swipe-content"
      >
        {children}
      </View>
      <Animated.View
        style={[styles.actions, { transform: [{ translateX: actionsTranslateX }] }]}
        testID="task-swipe-actions"
      >
        <Pressable
          accessibilityLabel="Edit task"
          accessibilityRole="button"
          onPress={() => {
            animateActions(false);
            update("edit-href", "new", "get");
          }}
          style={[styles.action, styles.edit, styles.editAction]}
        >
          <Text style={styles.actionText}>Edit</Text>
        </Pressable>
        <Pressable
          accessibilityLabel={completed ? "Reopen task" : "Complete task"}
          accessibilityRole="button"
          onPress={() => {
            animateActions(false);
            update("toggle-href", "replace", "post");
          }}
          style={[styles.action, styles.complete, styles.toggleAction]}
        >
          <Text numberOfLines={1} style={styles.actionText}>
            {completed ? "Reopen" : "Complete"}
          </Text>
        </Pressable>
        <Pressable
          accessibilityLabel="Delete task"
          accessibilityRole="button"
          onPress={() => {
            Alert.alert("Delete task?", "This action cannot be undone.", [
              { text: "Cancel", style: "cancel" },
              {
                text: "Delete",
                style: "destructive",
                onPress: () => {
                  animateActions(false);
                  update("delete-href", "replace", "post");
                },
              },
            ]);
          }}
          style={[styles.action, styles.remove, styles.deleteAction]}
        >
          <Text style={styles.actionText}>Delete</Text>
        </Pressable>
      </Animated.View>
    </View>
  );
}

const SwipeTaskRow = Object.assign(SwipeTaskRowComponent, {
  localName: "swipe-row",
  namespaceURI: COMPONENT_NAMESPACE,
});

const styles = StyleSheet.create({
  root: {
    overflow: "hidden",
    position: "relative",
  },
  content: {
    position: "relative",
  },
  contentOpen: {
    paddingRight: ACTIONS_WIDTH,
  },
  actions: {
    bottom: 0,
    flexDirection: "row",
    position: "absolute",
    right: 0,
    top: 0,
    width: ACTIONS_WIDTH,
  },
  action: {
    alignItems: "center",
    justifyContent: "center",
    paddingHorizontal: 8,
  },
  editAction: {
    width: EDIT_ACTION_WIDTH,
  },
  toggleAction: {
    width: TOGGLE_ACTION_WIDTH,
  },
  deleteAction: {
    width: DELETE_ACTION_WIDTH,
  },
  edit: {
    backgroundColor: "#278CFF",
  },
  complete: {
    backgroundColor: "#2F9E73",
  },
  remove: {
    backgroundColor: "#D92D20",
  },
  actionText: {
    color: "#FFFFFF",
    fontSize: 13,
    fontWeight: "700",
  },
});

export default SwipeTaskRow;
