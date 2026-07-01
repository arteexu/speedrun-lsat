# Sync and conflict resolution (Speedrun LSAT)

**Status:** Documented for Friday deliverable; full two-way sync not yet implemented.

## Mechanism (planned)

Both desktop and iOS use Anki's existing sync protocol via a self-hosted sync
server built from `rslib`. Reviews flow both ways with none lost and none
double-counted.

## Conflict rule (stated)

When the same card is reviewed on two devices while offline:

1. Compare review timestamps (real wall-clock time, not device-local guess).
2. **Winner:** the review with the **later timestamp**.
3. **Loser:** recorded in history but does **not** double-count scheduling state.

This prevents FSRS state corruption from duplicate reviews.

## Offline-first requirements

- iOS reviews offline; sync when connection returns.
- Wrong device clock must not corrupt or double-count (server validates ordering).
- Mid-sync disconnect must leave collection consistent (Anki's existing atomic sync).

## Sync test outline (must pass before ship)

```bash
# speedrun/tools/sync_test.py (outline — not yet automated)
# 1. Review 10 cards on phone offline, 10 different on desktop offline.
# 2. Reconnect — verify all 20 reviews appear exactly once.
# 3. Review same card on both offline with different answers.
# 4. Sync — verify later timestamp wins, loser in history only.
```

## Implementation notes

- Reuse `rslib` sync RPCs; no custom merge logic beyond timestamp rule.
- Document merge outcome in sync logs for auditability.
- See PRD §13 for grading requirements.
