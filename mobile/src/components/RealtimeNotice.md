# RealtimeNotice

An inline, theme-aware card for remote changes that must not silently replace a draft. It is not a toast or a discard confirmation.

```tsx
<RealtimeNotice
  message={labels.changed}
  actionLabel={labels.update}
  onAction={requestRefresh}
  dismissLabel={labels.dismiss}
  onDismiss={dismissCurrentNotice}
  pending={refreshPending}
/>
```

All copy comes from the caller, which reads it from `NoticeLabels` (`src/realtime/resources.tsx`). The gate picks the `message` from `changed`, `resync`, `error`, `csrf` or `newerEdits` according to the notice, and uses `update` and `dismiss` for the two controls. Omit the action label or callback for a dismiss-only notice. `pending` disables the action and exposes its busy state; dismissal stays available.

The caller owns confirmation, dirty state, notice revisions, refresh and acknowledgement. Neither callback implies fresh data. The card has no timer or internal dismissal state, so the caller decides when it leaves the tree. Keep confirmations with the caller: the app asks before discarding edits with a native `Alert.alert` (`confirmDiscard` in `src/realtime/app-session.tsx`), and the Snackbar carries only transient success or error feedback.

Existing HyperTodo palette tokens provide a soft card and integrated blue action in both themes. Text wraps and scales without truncation; controls have a 44-point minimum. The message has polite live-region semantics without duplicating control labels. VoiceOver ignores live regions, so on iOS the message is also announced with `AccessibilityInfo.announceForAccessibility` when the notice appears and when its text changes, not on other re-renders; Android relies on the live region alone. Renderer tests verify callbacks, pending, long copy, optional actions, palette changes and token contrast. Device layout, screen-reader announcements and large-font visual QA remain unverified by this component-only unit.
