# Copyright: Speedrun LSAT contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

"""End-to-end test for the schema-weighted queue RPC (a Rust engine change
called from Python). Verifies ordering by points-at-stake and that the call is
read-only (does not touch undo state or the collection)."""

from tests.shared import getEmptyCol

PREFIX = "sr:schema:"


def _add_card(col, schema: str) -> int:
    note = col.newNote()
    note["Front"] = f"stimulus for {schema}"
    note["Back"] = "answer"
    note.tags.append(PREFIX + schema)
    col.addNote(note)
    return note.cards()[0].id


def test_schema_weighted_queue_orders_by_points_at_stake():
    col = getEmptyCol()

    causal = _add_card(col, "flaw.causal")
    conditional = _add_card(col, "flaw.conditional")
    circular = _add_card(col, "flaw.structure.circular")

    undo_before = col.undo_status().last_step

    result = col._backend.build_schema_weighted_queue(
        search="deck:Default",
        limit=0,
        schema_tag_prefix=PREFIX,
        schema_weight={"flaw.causal": 0.5, "flaw.conditional": 0.2},
        schema_weakness={"flaw.causal": 0.4, "flaw.conditional": 0.9},
        time_pressured_schemas=[],
        time_pressure_factor=1.0,
        default_weight=0.1,
        default_weakness=1.0,
    )

    # causal 0.5*0.4=0.20 > conditional 0.2*0.9=0.18 > circular (defaults) 0.1*1.0=0.10
    assert [c.card_id for c in result] == [causal, conditional, circular]
    assert result[0].schema == "flaw.causal"
    assert abs(result[0].priority - 0.20) < 1e-9
    assert abs(result[1].priority - 0.18) < 1e-9
    assert abs(result[2].priority - 0.10) < 1e-9
    # the schema absent from the weight maps fell back to the defaults
    assert result[2].schema == "flaw.structure.circular"
    assert abs(result[2].schema_weight - 0.1) < 1e-9

    # limit is honored
    top = col._backend.build_schema_weighted_queue(
        search="deck:Default",
        limit=1,
        schema_tag_prefix=PREFIX,
        schema_weight={"flaw.causal": 0.5, "flaw.conditional": 0.2},
        schema_weakness={"flaw.causal": 0.4, "flaw.conditional": 0.9},
        time_pressured_schemas=[],
        time_pressure_factor=1.0,
        default_weight=0.1,
        default_weakness=1.0,
    )
    assert [c.card_id for c in top] == [causal]

    # the RPC is read-only: it must not add an undo step or mutate the collection
    assert col.undo_status().last_step == undo_before

    col.close()
