import type { HvComponentProps } from "hyperview";
import { createStyleProp, renderChildren } from "hyperview";
import React, { useCallback } from "react";
import { Alert, Pressable, StyleSheet, Text, View } from "react-native";
import Swipeable from "react-native-gesture-handler/Swipeable";

const COMPONENT_NAMESPACE = "https://hypertodo.app/components";

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

  const update = useCallback(
    (hrefAttribute: string, action: UpdateAction, verb: UpdateVerb): void => {
      const href = element.getAttribute(hrefAttribute);
      if (href) {
        onUpdate(href, action, element, { verb });
      }
    },
    [element, onUpdate],
  );

  return (
    <Swipeable
      containerStyle={rootStyle}
      friction={2}
      overshootRight={false}
      rightThreshold={44}
      renderRightActions={(_progress, _drag, swipeable) => (
        <View style={styles.actions}>
          <Pressable
            accessibilityLabel="Edit task"
            accessibilityRole="button"
            onPress={() => {
              swipeable.close();
              update("edit-href", "new", "get");
            }}
            style={[styles.action, styles.edit]}
          >
            <Text style={styles.actionText}>Edit</Text>
          </Pressable>
          <Pressable
            accessibilityLabel={completed ? "Reopen task" : "Complete task"}
            accessibilityRole="button"
            onPress={() => {
              swipeable.close();
              update("toggle-href", "replace", "post");
            }}
            style={[styles.action, styles.complete]}
          >
            <Text style={styles.actionText}>{completed ? "Reopen" : "Complete"}</Text>
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
                    swipeable.close();
                    update("delete-href", "replace", "post");
                  },
                },
              ]);
            }}
            style={[styles.action, styles.remove]}
          >
            <Text style={styles.actionText}>Delete</Text>
          </Pressable>
        </View>
      )}
    >
      {children}
    </Swipeable>
  );
}

const SwipeTaskRow = Object.assign(SwipeTaskRowComponent, {
  localName: "swipe-row",
  namespaceURI: COMPONENT_NAMESPACE,
});

const styles = StyleSheet.create({
  actions: {
    flexDirection: "row",
    overflow: "hidden",
  },
  action: {
    alignItems: "center",
    justifyContent: "center",
    minWidth: 78,
    paddingHorizontal: 10,
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
