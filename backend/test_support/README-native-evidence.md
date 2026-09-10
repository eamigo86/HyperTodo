# Read the collector as upload evidence, not native acceptance

`EvidenceCollector.reject()` immediately persists the first bounded rejection
reason and accepted-record count. Later rejections and close retain that reason;
status I/O failure is reported without recursive writes, and close still releases
owned files. No raw request, cookie, identity or rejected payload is recorded.

Previously rejection changed only memory until a later accepted record or close.
The first reason was already sticky: close did not overwrite it. Closing without
`complete` and without an earlier reason still yields `report-failed`; that alone
cannot identify the first physical client failure or prove authentication failed.

The report endpoint is fixture-only and handled before Django business/auth/CSRF.
Missing or rotated cookies do not require login; duplicate owned cookie names are
rejected. Exact host, POST, JSON content type, no query, ten closed scalar fields,
run ownership,2048-byte body and500 logical records remain enforced. Ordinary
requests keep their existing auth/CSRF and64KiB bound. Fixture lifetime600seconds
and Uvicorn300-request budget are unchanged.

Tests use isolated collector files/ASGI messages. A dropped204 after server append
is a controlled transport scenario, not evidence that it occurred on the iPhone.
Missing foreground/Finish uploads cannot overturn the user's visual report or
upgrade partial records into full Gate0 acceptance.

## Retry only the last accepted record

A response can be lost after the collector has already persisted its record. An
identical retry of **only that last accepted record** receives the same empty204
without another append, count increment or state change. This includes a lost
`complete` ACK while the collector is still open. Validation of all closed scalar
fields, exact run and2048-byte bound occurs before duplicate acknowledgement; JSON
key order/spacing is not authority. Only one immutable validated record is retained.

An older sequence, conflicting last record, invalid fields/run, or any request
after inconclusive/closed state is rejected. A new record after complete is also
rejected. Duplicate record500 does not consume logical capacity; request traffic
still consumes the unchanged Uvicorn quota. No failure reason can be cleared by
replay, and no native acceptance is inferred from an upload ACK.

The matching frontend may retry its same frozen head once after an ambiguous
transport failure, only while active; it must not advance to the next record
until204. HTTP rejection is definitive. This is bounded last-ACK recovery, not
history replay, batching or a replacement for the native lifecycle proof.
