#!/usr/bin/env python3
"""Two-way sync test (Friday deliverable, PRD §13).

Starts a self-hosted Anki sync server, then simulates a "desktop" and a "phone"
collection of the exam deck. It proves the two guarantees the milestone requires:

  A) Disjoint reviews merge without loss or double-count.
     Review >=10 cards on the desktop and >=10 *different* cards on the phone
     (offline), sync both ways, and assert every review lands exactly once: the
     merged revlog holds the sum of both sides, each reviewed card is counted
     once, and no card row is duplicated by the merge.

  B) Conflict resolution is deterministic.
     Review the *same* card on both clients while offline, with the phone's
     review at a strictly later real timestamp, then sync both ways. Assert the
     documented conflict rule (later real-timestamp review wins for the card's
     scheduling state; both review rows are preserved so nothing double-counts)
     resolves it to one consistent, non-corrupt state on both clients.

The conflict rule and the merge mechanics it relies on are documented in
docs/architecture.md ("Speedrun sync and the conflict rule").

This script starts its own sync server, so it needs no external services. If the
bundled sync server cannot be started it prints a clear SKIP and exits 0 rather
than hanging (it is an environment problem, not a sync defect). Any *lost*,
*double-counted*, or *corrupt* outcome makes it exit non-zero.

Run:
    PYTHONPATH=out/pylib:$PWD out/pyenv/bin/python -m speedrun.tools.sync_test
"""
from __future__ import annotations

import os
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

USER, PASSWORD = "dev", "pass"

# Cards reviewed per side in the disjoint (no-loss) phase. PRD §13 requires >=10
# on each device, on *different* cards.
PER_SIDE = 10


def _free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def _wait_port(port: int, timeout: float = 20.0) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.5):
                return
        except OSError:
            time.sleep(0.2)
    raise RuntimeError("sync server did not start")


def _start_server(base: Path, port: int) -> subprocess.Popen:
    env = dict(os.environ)
    env.update(
        SYNC_USER1=f"{USER}:{PASSWORD}",
        SYNC_HOST="127.0.0.1",
        SYNC_PORT=str(port),
        SYNC_BASE=str(base),
        RUST_LOG="error",
    )
    proc = subprocess.Popen(
        [sys.executable, "-m", "anki.syncserver"],
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    _wait_port(port)
    return proc


def _new_col(path: Path):
    from anki.collection import Collection

    return Collection(str(path))


def _sync(col, url: str) -> str:
    """Login + sync; perform a full up/download when the server asks. Returns the
    resulting `required` name."""
    from anki import sync_pb2

    auth = col._backend.sync_login(
        sync_pb2.SyncLoginRequest(username=USER, password=PASSWORD, endpoint=url)
    )
    resp = col._backend.sync_collection(auth=auth, sync_media=False)
    Req = sync_pb2.SyncCollectionResponse.ChangesRequired
    if resp.required in (Req.FULL_UPLOAD, Req.FULL_SYNC):
        col._backend.full_upload_or_download(
            sync_pb2.FullUploadOrDownloadRequest(auth=auth, upload=True)
        )
        return "FULL_UPLOAD"
    if resp.required == Req.FULL_DOWNLOAD:
        col._backend.full_upload_or_download(
            sync_pb2.FullUploadOrDownloadRequest(auth=auth, upload=False)
        )
        return "FULL_DOWNLOAD"
    return Req.Name(resp.required)


def _sync_both_ways(desktop, phone, url: str) -> None:
    """Converge two clients that each hold pending offline changes.

    desktop pushes, phone pushes+pulls, then both pull again so each client ends
    holding the full merged set (the merge is symmetric once both have seen the
    other's chunk)."""
    _sync(desktop, url)
    _sync(phone, url)
    _sync(desktop, url)
    _sync(phone, url)


def _ordered_card_ids(col) -> list[int]:
    """Card ids in the exam deck, in a stable order shared by both clients."""
    from speedrun.tools.import_seed_deck import DECK_NAME

    did = col.decks.id(DECK_NAME)
    return col.db.list("select id from cards where did = ? order by id", did)


def _answer_cids(col, cids: list[int], rating, base_ms: int) -> int:
    """Record a real review for each specific card id through the shared v3
    scheduler (get states -> build answer -> answer_card), exactly as the GUI
    does. `answered_at_millis` is set explicitly (and made unique via `base_ms`
    + index) so revlog ids never collide and the conflict phase can order the two
    competing reviews by real timestamp. Returns how many were answered."""
    from anki import scheduler_pb2

    done = 0
    for i, cid in enumerate(cids):
        card = col.get_card(cid)
        card.start_timer()
        states = col._backend.get_scheduling_states(cid)
        answer = col.sched.build_answer(card=card, states=states, rating=rating)
        answer.answered_at_millis = base_ms + i
        # A realistic, non-zero latency so latency-aware scoring has data.
        answer.milliseconds_taken = 2500
        col.sched.answer_card(answer)
        done += 1
    return done


def _revlog_count(col) -> int:
    return col.db.scalar("select count() from revlog")


def _card_count(col) -> int:
    return col.db.scalar("select count() from cards")


def _distinct_reviewed_cards(col) -> int:
    return col.db.scalar("select count(distinct cid) from revlog")


def _max_reviews_per_card(col) -> int:
    return (
        col.db.scalar(
            "select max(c) from (select cid, count() c from revlog group by cid)"
        )
        or 0
    )


def _revlog_for(col, cid: int) -> int:
    return col.db.scalar("select count() from revlog where cid = ?", cid)


def _card_state(col, cid: int) -> tuple:
    """The fields the sync merge reconciles for a card: modification time plus
    the scheduling state. Two clients that agree on this tuple hold a single,
    consistent card state."""
    return tuple(
        col.db.first(
            "select mod, reps, ivl, due, type, queue from cards where id = ?", cid
        )
    )


def _integrity_ok(col) -> bool:
    """Anki's own database check ('Check Database'); True if no problems found."""
    _report, ok = col.fix_integrity()
    return ok


def _skip(message: str) -> int:
    print(f"SYNC TEST SKIPPED: {message}")
    print(
        "  This test self-hosts the sync server via `python -m anki.syncserver`.\n"
        "  Ensure it is importable, e.g.:\n"
        "    PYTHONPATH=out/pylib:$PWD out/pyenv/bin/python -m speedrun.tools.sync_test"
    )
    return 0


def main() -> int:
    from anki import scheduler_pb2
    from speedrun.tools.import_seed_deck import DECK_NAME, import_seed_deck

    Rating = scheduler_pb2.CardAnswer

    work = Path(tempfile.mkdtemp(prefix="sync-test-"))
    port = _free_port()
    url = f"http://127.0.0.1:{port}/"
    try:
        server = _start_server(work / "server", port)
    except RuntimeError as err:
        return _skip(str(err))
    except (ImportError, ModuleNotFoundError, FileNotFoundError) as err:
        return _skip(f"could not launch sync server: {err}")

    try:
        # Desktop: import the exam deck and upload it.
        desktop = _new_col(work / "desktop.anki2")
        import_seed_deck(desktop, backup=False)
        desktop.decks.select(desktop.decks.id(DECK_NAME))
        assert _sync(desktop, url) == "FULL_UPLOAD"

        # Phone: empty collection downloads the same deck.
        phone = _new_col(work / "phone.anki2")
        assert _sync(phone, url) == "FULL_DOWNLOAD"

        deck_cards = _card_count(desktop)
        assert _card_count(phone) == deck_cards, "phone did not receive the full deck"

        cids = _ordered_card_ids(desktop)
        need = 2 * PER_SIDE + 1
        assert len(cids) >= need, f"deck too small: {len(cids)} cards, need {need}"

        # --- Phase A: disjoint reviews, no loss, no double-count ---------------
        desktop_cids = cids[:PER_SIDE]
        phone_cids = cids[PER_SIDE : 2 * PER_SIDE]
        assert not set(desktop_cids) & set(phone_cids), "review sets overlap"

        base = int(time.time() * 1000)
        assert _answer_cids(desktop, desktop_cids, Rating.GOOD, base) == PER_SIDE
        # Offset the phone's revlog ids well clear of the desktop's so a merge
        # can never silently collapse two reviews onto one id.
        assert (
            _answer_cids(phone, phone_cids, Rating.GOOD, base + 1_000_000) == PER_SIDE
        )

        _sync_both_ways(desktop, phone, url)

        total = 2 * PER_SIDE
        d, p = _revlog_count(desktop), _revlog_count(phone)
        print(f"[A] disjoint: desktop revlog={d} phone revlog={p} (expect {total} each)")
        assert d == total, f"desktop lost/dup reviews: {d} != {total}"
        assert p == total, f"phone lost/dup reviews: {p} != {total}"
        for name, col in (("desktop", desktop), ("phone", phone)):
            assert _distinct_reviewed_cards(col) == total, (
                f"{name}: expected {total} distinct reviewed cards, "
                f"got {_distinct_reviewed_cards(col)}"
            )
            assert _max_reviews_per_card(col) == 1, (
                f"{name}: a card was counted more than once "
                f"(max reviews/card = {_max_reviews_per_card(col)})"
            )
            assert _card_count(col) == deck_cards, f"{name}: card count drifted (dup cards)"
        print("[A] PASS: 20 reviews, each card counted once, no duplicated cards.")

        # --- Phase B: same card on both, offline, conflict resolution ---------
        conflict_cid = cids[2 * PER_SIDE]
        assert _revlog_for(desktop, conflict_cid) == 0, "conflict card already reviewed"

        # Desktop reviews first (AGAIN), phone reviews the same card >1s later
        # (EASY). The >1s gap guarantees distinct card mtimes (seconds), and the
        # later answered_at gives the phone the later real timestamp -> it must win.
        cbase = int(time.time() * 1000)
        assert _answer_cids(desktop, [conflict_cid], Rating.AGAIN, cbase) == 1
        desktop_local = _card_state(desktop, conflict_cid)
        time.sleep(1.2)
        assert _answer_cids(phone, [conflict_cid], Rating.EASY, cbase + 5_000) == 1
        phone_local = _card_state(phone, conflict_cid)

        assert phone_local[0] > desktop_local[0], (
            f"phone review not strictly later: phone.mod={phone_local[0]} "
            f"desktop.mod={desktop_local[0]}"
        )
        assert phone_local != desktop_local, "AGAIN and EASY produced identical state"

        _sync_both_ways(desktop, phone, url)

        merged_desktop = _card_state(desktop, conflict_cid)
        merged_phone = _card_state(phone, conflict_cid)
        print(
            f"[B] conflict: desktop.mod={desktop_local[0]} phone.mod={phone_local[0]} "
            f"-> merged.mod={merged_desktop[0]}"
        )
        # Both clients converge to one state (no divergence / corruption).
        assert merged_desktop == merged_phone, (
            f"clients diverged on conflict card: {merged_desktop} != {merged_phone}"
        )
        # The later real-timestamp review (phone) wins the scheduling state.
        assert merged_desktop == phone_local, (
            f"conflict winner wrong: merged {merged_desktop} != later/phone {phone_local}"
        )
        assert merged_desktop != desktop_local, "earlier review should not have won"

        # Both review rows survive (history preserved) but the card is counted
        # once: exactly two revlog rows for the card, one card row.
        for name, col in (("desktop", desktop), ("phone", phone)):
            assert _revlog_for(col, conflict_cid) == 2, (
                f"{name}: expected both conflict reviews in history, "
                f"got {_revlog_for(col, conflict_cid)}"
            )
            assert _revlog_count(col) == total + 2, f"{name}: conflict lost/dup a review"
            assert _card_count(col) == deck_cards, f"{name}: card count drifted (dup cards)"
        print("[B] PASS: later timestamp won, both review rows kept, no double-count.")

        # --- Integrity: Anki's own DB check on both clients -------------------
        for name, col in (("desktop", desktop), ("phone", phone)):
            assert _integrity_ok(col), f"{name}: collection failed integrity check"
        print("[C] PASS: both collections pass Anki's database check (not corrupt).")

        desktop.close()
        phone.close()
        print("SYNC TEST PASSED: two-way merge + deterministic conflict resolution.")
        return 0
    finally:
        server.terminate()
        try:
            server.wait(timeout=5)
        except subprocess.TimeoutExpired:
            server.kill()


if __name__ == "__main__":
    raise SystemExit(main())
