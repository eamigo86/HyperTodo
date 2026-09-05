# Acceptance checklist

## Automated

- [x] Django 6.1.1 installs with Python 3.14 through uv.
- [x] Published dj-hyperview 0.1.0a7 is the installed package.
- [x] Backend tests pass above the 95 percent statement-and-branch gate.
- [x] Source precedence and shared Redis invalidation tests pass without flushing Redis.
- [x] Every tested response is valid UTF-8 HXML with the package media type.
- [x] CSRF, session expiry, no-redirect login, and two-user isolation pass.
- [x] Mobile TypeScript passes.
- [x] Mobile Jest tests pass.
- [x] Expo Doctor passes all 21 checks.

## Manual iOS smoke

- [ ] Development build launches and branded splash/loading appears.
- [ ] Login establishes and retains the Django session.
- [ ] Only the signed-in user's tasks and categories appear.
- [ ] Create, edit, complete, reopen, filter, and delete a task.
- [ ] Create, edit, filter by, and delete a category.
- [ ] Invalid forms remain on an HXML form with visible feedback.
- [ ] Session expiry returns to the dedicated sign-in path.
- [ ] A database template override is visible after refresh.

## Manual Android smoke

- [ ] Repeat the complete iOS flow with `10.0.2.2` or a reachable LAN address.
- [ ] Confirm local cleartext development traffic works.
- [ ] Confirm date picker, separate time entry, and back navigation behave correctly.

## Acceptance evidence

Record date, platform version, simulator/device, backend commit, result, and any finding below before declaring the consumer trial complete.
