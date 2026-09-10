# RealtimeNotice

An inline, theme-aware card for remote changes that must not silently replace a draft. It is not a toast or a discard confirmation.

```tsx
<RealtimeNotice
  message={labels.changesAvailable}
  actionLabel={labels.reviewChanges}
  onAction={requestRefresh}
  dismissLabel={labels.dismissChanges}
  onDismiss={dismissCurrentNotice}
  pending={refreshPending}
/>
```

All copy comes from the caller. Omit the action label or callback for a dismiss-only notice. `pending` disables the action and exposes its busy state; dismissal stays available.

The caller owns confirmation, dirty state, notice revisions, refresh and acknowledgement. Neither callback implies fresh data. The card has no timer or internal dismissal state, so the caller decides when it leaves the tree. Keep confirmations in the existing Snackbar flow.

Existing HyperTodo palette tokens provide a soft card and integrated blue action in both themes. Text wraps and scales without truncation; controls have a 44-point minimum. The message has polite live-region semantics without duplicating control labels. Renderer tests verify callbacks, pending, long copy, optional actions, palette changes and token contrast. Device layout, screen-reader announcements and large-font visual QA remain unverified by this component-only unit.
