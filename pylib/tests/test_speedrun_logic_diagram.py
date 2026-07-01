# Copyright: Speedrun LSAT contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

"""Tests for the conditional-logic visualiser engine (flaw.conditional.*).

A -> B means A is sufficient for B and B is necessary for A. Validity is decided
over the closure (given rules + contrapositives + chains); the two classic errors
are named against the rules as authored: affirming the consequent (mistaken
reversal) and denying the antecedent (mistaken negation).
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from speedrun.logic_diagram import (  # noqa: E402
    PROBLEMS,
    VERDICT_NEGATION,
    VERDICT_REVERSAL,
    VERDICT_UNSUPPORTED,
    VERDICT_VALID,
    LogicModel,
    Rule,
    build_logic_graph,
    logic_diagram_payload,
    model_for,
    parse_literal,
    parse_rule,
    problem_payload,
    render_logic_diagram_html,
)


def test_parse_literal_handles_negation_and_whitespace():
    assert parse_literal("A") == parse_literal("A")
    lit = parse_literal("  ~B ")
    assert lit.term == "B" and lit.negated is True
    assert parse_literal("~~C").negated is False  # double negation cancels
    with pytest.raises(ValueError):
        parse_literal("   ")
    with pytest.raises(ValueError):
        parse_literal("~")


def test_parse_rule_arrow_variants():
    for text in ("A -> B", "A => B", "A → B"):
        r = parse_rule(text)
        assert r.suff.id == "A" and r.nec.id == "B"
    with pytest.raises(ValueError):
        parse_rule("A B")


def test_contrapositive():
    r = parse_rule("A -> B")
    c = r.contrapositive()
    assert c.suff.id == "~B" and c.nec.id == "~A"


def test_valid_direct_and_contrapositive():
    m = LogicModel(given=[parse_rule("A -> B")])
    assert m.classify(parse_rule("A -> B")) == VERDICT_VALID
    assert m.classify(parse_rule("~B -> ~A")) == VERDICT_VALID  # contrapositive


def test_valid_chain():
    m = LogicModel(given=[parse_rule("S -> D"), parse_rule("D -> X")])
    assert m.classify(parse_rule("S -> X")) == VERDICT_VALID
    path = m.path("S", "X")
    assert path == ["S", "D", "X"]
    # Contrapositive of the chain is valid too.
    assert m.classify(parse_rule("~X -> ~S")) == VERDICT_VALID


def test_mistaken_reversal_is_affirming_the_consequent():
    m = LogicModel(given=[parse_rule("M -> P")])
    assert m.classify(parse_rule("P -> M")) == VERDICT_REVERSAL
    assert "reversal" in m.explain(parse_rule("P -> M")).lower()


def test_mistaken_negation_is_denying_the_antecedent():
    m = LogicModel(given=[parse_rule("A -> E")])
    assert m.classify(parse_rule("~A -> ~E")) == VERDICT_NEGATION
    assert "negation" in m.explain(parse_rule("~A -> ~E")).lower()


def test_unsupported_between_unrelated_terms():
    m = LogicModel(given=[parse_rule("A -> B"), parse_rule("C -> D")])
    assert m.classify(parse_rule("A -> D")) == VERDICT_UNSUPPORTED


def test_build_graph_has_given_and_contrapositive_edges_and_layout():
    m = LogicModel(given=[parse_rule("A -> B")])
    g = build_logic_graph(m)
    node_ids = {n["id"] for n in g["nodes"]}
    assert node_ids == {"A", "B", "~A", "~B"}
    kinds = {(e["source"], e["target"]): e["kind"] for e in g["edges"]}
    assert kinds[("A", "B")] == "given"
    assert kinds[("~B", "~A")] == "contrapositive"
    # Sufficient sits to the left of necessary (lower layer index).
    layer = {n["id"]: n["layer"] for n in g["nodes"]}
    assert layer["A"] < layer["B"]
    assert layer["~B"] < layer["~A"]


def test_chain_produces_a_derived_edge():
    m = LogicModel(given=[parse_rule("S -> D"), parse_rule("D -> X")])
    g = build_logic_graph(m)
    derived = {(e["source"], e["target"]) for e in g["edges"] if e["kind"] == "derived"}
    assert ("S", "X") in derived


def test_problem_payloads_match_expected_verdicts():
    expected = {
        "calculus": VERDICT_REVERSAL,
        "alarm": VERDICT_NEGATION,
        "scholarship": VERDICT_VALID,
        "permit": VERDICT_REVERSAL,
    }
    by_id = {p.id: p for p in PROBLEMS}
    for pid, verdict in expected.items():
        problem = by_id[pid]
        model = model_for(problem)
        claim = parse_rule(problem.claim)
        assert model.classify(claim) == verdict, pid
        payload = problem_payload(problem)
        key = f"{payload['claim']['suff']}->{payload['claim']['nec']}"
        assert payload["inferences"][key]["verdict"] == verdict


def test_payload_inferences_cover_all_ordered_pairs():
    payload = problem_payload(PROBLEMS[0])
    n = len(payload["nodes"])
    assert len(payload["inferences"]) == n * (n - 1)


def test_render_full_and_embed_and_empty():
    full = render_logic_diagram_html()
    assert full.strip().startswith("<!DOCTYPE html>")
    for token in ("sr-logic-data", "Conditional logic visualizer", "Test an inference"):
        assert token in full
    embed = render_logic_diagram_html(embed=True)
    assert "<!DOCTYPE html>" not in embed
    assert 'class="sr-dash"' in embed
    empty = render_logic_diagram_html(problems=[])
    assert "No conditional problems" in empty


def test_logic_diagram_payload_is_json_serializable():
    import json

    payload = logic_diagram_payload()
    assert json.loads(json.dumps(payload))["problems"]
    assert len(payload["problems"]) == len(PROBLEMS)
