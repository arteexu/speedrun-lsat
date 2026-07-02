#!/usr/bin/env python3
"""Append a batch of ORIGINAL, license-clean LSAT-style practice items to the seed
deck, adding depth (multiple analogs per schema, per SPOV1/Insight 3) and filling
taxonomy gaps.

Idempotent: items whose id already exists are skipped, so it is safe to re-run.
All items are hand-authored originals (source: "original") -- no copyrighted LSAT
content. Run:

    PYTHONPATH=out/pylib out/pyenv/bin/python speedrun/tools/add_practice_items.py

Then regenerate the bundled iOS exam deck so mobile stays in sync:

    PYTHONPATH=out/pylib out/pyenv/bin/python speedrun/tools/export_exam_deck.py
"""
from __future__ import annotations

import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SEED = REPO_ROOT / "speedrun" / "data" / "seed_deck.json"


def _c(cid, text, correct=False, trap=None):
    return {"id": cid, "text": text, "trap": trap, "correct": correct}


NEW_ITEMS: list[dict] = [
    # ---------------- gaps: missing flaws ----------------
    {
        "id": "lr-0035", "section": "LR", "stem_type": "qt.flaw",
        "schemas": ["flaw.structure.appeal_authority_emotion", "qt.flaw"],
        "difficulty": 2, "source": "original",
        "stimulus": "A famous film star endorses this multivitamin, so it must be the most effective one available.",
        "question": "The reasoning is most vulnerable to criticism on the grounds that it",
        "choices": [
            _c("A", "relies on the endorsement of someone whose expertise is unrelated to nutrition.", correct=True),
            _c("B", "assumes the multivitamin works equally well for everyone.", trap="trap.too_strong_extreme"),
            _c("C", "fails to specify what 'effective' means.", trap="trap.out_of_scope"),
            _c("D", "overlooks the price of the multivitamin.", trap="trap.out_of_scope"),
            _c("E", "restates that the star endorses the product.", trap="trap.premise_restatement"),
        ],
        "two_answer_fork": {"runner_up": "B", "why_runner_up_wrong": "B flags an overgeneralization, but the decisive defect is treating an irrelevant celebrity as an authority (A)."},
    },
    {
        "id": "lr-0036", "section": "LR", "stem_type": "qt.flaw",
        "schemas": ["flaw.structure.comparison", "qt.flaw"],
        "difficulty": 3, "source": "original",
        "stimulus": "A new textbook raised test scores at Lincoln High more than the old one did. So adopting it will raise scores at Kennedy High more than Kennedy's current book does.",
        "question": "The argument is most vulnerable to criticism because it",
        "choices": [
            _c("A", "assumes that what held at one school will hold at another that may differ in relevant ways.", correct=True),
            _c("B", "presumes the old textbook was completely ineffective.", trap="trap.half_right"),
            _c("C", "ignores the quality of teachers entirely.", trap="trap.out_of_scope"),
            _c("D", "concludes that every student's score will rise.", trap="trap.too_strong_extreme"),
            _c("E", "merely restates that scores rose at Lincoln.", trap="trap.premise_restatement"),
        ],
        "two_answer_fork": {"runner_up": "C", "why_runner_up_wrong": "C names one possible difference, but the general flaw is assuming the two schools are comparable at all (A); C is one instance, not the defect itself."},
    },
    {
        "id": "lr-0037", "section": "LR", "stem_type": "qt.flaw",
        "schemas": ["flaw.structure.self_contradiction", "qt.flaw"],
        "difficulty": 4, "source": "original",
        "stimulus": "No sweeping generalization is ever fully true. That, at least, is a claim we can assert with complete confidence.",
        "question": "The reasoning is most vulnerable to criticism because it",
        "choices": [
            _c("A", "asserts a sweeping generalization with full confidence while denying any such claim can be fully true.", correct=True),
            _c("B", "relies on a term it never defines.", trap="trap.out_of_scope"),
            _c("C", "provides too little evidence for its conclusion.", trap="trap.too_weak"),
            _c("D", "restates its premise as its conclusion.", trap="trap.premise_restatement"),
            _c("E", "could be true under some interpretations.", trap="trap.could_be_true"),
        ],
        "two_answer_fork": {"runner_up": "D", "why_runner_up_wrong": "It can look circular, but the precise defect is self-contradiction: the claim disqualifies itself (A), which is stronger than mere restatement."},
    },
    # ---------------- depth: causal ----------------
    {
        "id": "lr-0038", "section": "LR", "stem_type": "qt.weaken",
        "schemas": ["flaw.causal.correlation_causation", "qt.weaken"],
        "difficulty": 2, "source": "original",
        "stimulus": "Neighborhoods with more coffee shops have higher home values. Clearly, opening coffee shops raises nearby home values.",
        "question": "Which one of the following, if true, most weakens the argument?",
        "choices": [
            _c("A", "Developers deliberately open coffee shops in areas where home values are already climbing.", correct=True),
            _c("B", "Some coffee shops close within their first year.", trap="trap.too_weak"),
            _c("C", "The city should approve more coffee-shop permits.", trap="trap.right_answer_wrong_question"),
            _c("D", "Property taxes tend to rise as home values rise.", trap="trap.out_of_scope"),
            _c("E", "A few high-value neighborhoods have very few coffee shops.", trap="trap.too_weak"),
        ],
        "two_answer_fork": {"runner_up": "E", "why_runner_up_wrong": "E is too weak — a few exceptions don't undo an average trend; A supplies a reverse/common-cause alternative that attacks the causal claim directly."},
    },
    {
        "id": "lr-0039", "section": "LR", "stem_type": "qt.flaw",
        "schemas": ["flaw.causal.reversed", "qt.flaw"],
        "difficulty": 3, "source": "original",
        "stimulus": "Students who report high confidence tend to score well on the exam. So building students' confidence will raise their exam scores.",
        "question": "The reasoning is most vulnerable to criticism because it",
        "choices": [
            _c("A", "overlooks that scoring well may be what produces the confidence.", correct=True),
            _c("B", "assumes confidence can be measured precisely.", trap="trap.out_of_scope"),
            _c("C", "concludes that every confident student scores well.", trap="trap.too_strong_extreme"),
            _c("D", "ignores students who lack confidence.", trap="trap.too_weak"),
            _c("E", "recommends a study schedule.", trap="trap.right_answer_wrong_question"),
        ],
        "two_answer_fork": {"runner_up": "C", "why_runner_up_wrong": "C attacks an overgeneralization the argument doesn't quite make; A identifies reversed causation, the actual gap."},
    },
    {
        "id": "lr-0040", "section": "LR", "stem_type": "qt.weaken",
        "schemas": ["flaw.causal.common_cause", "qt.weaken"],
        "difficulty": 3, "source": "original",
        "stimulus": "Children who take music lessons have better math grades. Therefore, music lessons improve mathematical ability.",
        "question": "Which one of the following, if true, most weakens the argument?",
        "choices": [
            _c("A", "Families that can afford music lessons also tend to afford math tutoring.", correct=True),
            _c("B", "Some talented musicians dislike mathematics.", trap="trap.too_weak"),
            _c("C", "Music and math both involve patterns.", trap="trap.premise_restatement"),
            _c("D", "Music lessons are expensive.", trap="trap.out_of_scope"),
            _c("E", "Schools should fund music programs.", trap="trap.right_answer_wrong_question"),
        ],
        "two_answer_fork": {"runner_up": "B", "why_runner_up_wrong": "B cites isolated exceptions (too weak); A introduces a common cause (family resources) explaining both variables."},
    },
    {
        "id": "lr-0041", "section": "LR", "stem_type": "qt.flaw",
        "schemas": ["flaw.causal.post_hoc", "qt.flaw"],
        "difficulty": 2, "source": "original",
        "stimulus": "Right after the company introduced standing desks, sick days dropped. The standing desks must have made employees healthier.",
        "question": "The reasoning is most vulnerable to criticism because it",
        "choices": [
            _c("A", "infers a causal link merely from one change following another in time.", correct=True),
            _c("B", "assumes all employees used the standing desks.", trap="trap.too_strong_extreme"),
            _c("C", "fails to define 'healthier'.", trap="trap.out_of_scope"),
            _c("D", "ignores the cost of the desks.", trap="trap.out_of_scope"),
            _c("E", "restates that sick days dropped.", trap="trap.premise_restatement"),
        ],
        "two_answer_fork": {"runner_up": "B", "why_runner_up_wrong": "B raises a coverage worry, but the core error is post hoc reasoning — treating temporal sequence as causation (A)."},
    },
    # ---------------- depth: conditional ----------------
    {
        "id": "lr-0042", "section": "LR", "stem_type": "qt.flaw",
        "schemas": ["flaw.conditional.nec_suff_confusion", "qt.flaw"],
        "difficulty": 3, "source": "original",
        "stimulus": "To pass the bar, you must study hard. Maria studied hard, so she will pass the bar.",
        "question": "The reasoning is most vulnerable to criticism because it",
        "choices": [
            _c("A", "treats a necessary condition for passing as if it were sufficient.", correct=True),
            _c("B", "assumes Maria wants to pass the bar.", trap="trap.out_of_scope"),
            _c("C", "concludes that everyone who studies passes.", trap="trap.too_strong_extreme"),
            _c("D", "ignores how long Maria studied.", trap="trap.too_weak"),
            _c("E", "restates that studying is required.", trap="trap.premise_restatement"),
        ],
        "two_answer_fork": {"runner_up": "C", "why_runner_up_wrong": "C describes a broader overgeneralization; the precise defect is confusing a necessary condition for a sufficient one (A)."},
    },
    {
        "id": "lr-0043", "section": "LR", "stem_type": "qt.parallel_flaw",
        "schemas": ["flaw.conditional.mistaken_reversal", "qt.parallel_flaw"],
        "difficulty": 4, "source": "original",
        "stimulus": "If a plant is a fern, then it reproduces by spores. This plant reproduces by spores, so it is a fern.",
        "question": "The flawed reasoning above is most similar to which one of the following?",
        "choices": [
            _c("A", "If a road is icy, it is dangerous. This road is dangerous, so it is icy.", correct=True),
            _c("B", "If it rains, the game is canceled. It did not rain, so the game was not canceled.", trap="trap.half_right"),
            _c("C", "All ferns are plants, and this is a fern, so it is a plant.", trap="trap.opposite"),
            _c("D", "Most spore-bearers are ferns, so this is probably a fern.", trap="trap.too_weak"),
            _c("E", "Ferns are common, so many plants reproduce by spores.", trap="trap.out_of_scope"),
        ],
        "two_answer_fork": {"runner_up": "B", "why_runner_up_wrong": "B is a mistaken negation (denying the antecedent), not a mistaken reversal; A matches the affirm-the-consequent structure exactly."},
    },
    {
        "id": "lr-0044", "section": "LR", "stem_type": "qt.flaw",
        "schemas": ["flaw.conditional.mistaken_negation", "qt.flaw"],
        "difficulty": 3, "source": "original",
        "stimulus": "If a bill has bipartisan support, it will pass. This bill lacks bipartisan support, so it will not pass.",
        "question": "The reasoning is most vulnerable to criticism because it",
        "choices": [
            _c("A", "assumes that without the stated condition the outcome cannot occur.", correct=True),
            _c("B", "takes for granted that all bills should pass.", trap="trap.out_of_scope"),
            _c("C", "concludes that bipartisan bills always pass instantly.", trap="trap.too_strong_extreme"),
            _c("D", "restates that the bill lacks support.", trap="trap.premise_restatement"),
            _c("E", "reverses the stated conditional.", trap="trap.half_right"),
        ],
        "two_answer_fork": {"runner_up": "E", "why_runner_up_wrong": "E names the wrong conditional error — this is denying the antecedent (mistaken negation, A), not a reversal."},
    },
    # ---------------- depth: sampling ----------------
    {
        "id": "lr-0045", "section": "LR", "stem_type": "qt.weaken",
        "schemas": ["flaw.sampling.unrepresentative", "qt.weaken"],
        "difficulty": 2, "source": "original",
        "stimulus": "A magazine polled its readers online and found 90% support a longer school year. So most people in the country support a longer school year.",
        "question": "Which one of the following, if true, most weakens the argument?",
        "choices": [
            _c("A", "The magazine's readers are mostly educators, who differ from the general public on this issue.", correct=True),
            _c("B", "The poll received thousands of responses.", trap="trap.opposite"),
            _c("C", "A longer school year would raise costs.", trap="trap.out_of_scope"),
            _c("D", "Some readers did not answer the poll.", trap="trap.too_weak"),
            _c("E", "Schools should survey parents directly.", trap="trap.right_answer_wrong_question"),
        ],
        "two_answer_fork": {"runner_up": "D", "why_runner_up_wrong": "Nonresponse alone is too weak; A shows the sample is unrepresentative of the population the conclusion is about."},
    },
    {
        "id": "lr-0046", "section": "LR", "stem_type": "qt.flaw",
        "schemas": ["flaw.sampling.appeal_to_ignorance", "qt.flaw"],
        "difficulty": 3, "source": "original",
        "stimulus": "No study has ever shown this supplement to be unsafe. Therefore, it is safe.",
        "question": "The reasoning is most vulnerable to criticism because it",
        "choices": [
            _c("A", "treats the absence of evidence of harm as evidence of safety.", correct=True),
            _c("B", "assumes the supplement is widely used.", trap="trap.out_of_scope"),
            _c("C", "concludes the supplement cures illness.", trap="trap.too_strong_extreme"),
            _c("D", "ignores the supplement's cost.", trap="trap.out_of_scope"),
            _c("E", "restates that no study found harm.", trap="trap.premise_restatement"),
        ],
        "two_answer_fork": {"runner_up": "E", "why_runner_up_wrong": "E notes a restatement, but the defect is the inference from 'not shown unsafe' to 'safe' — an appeal to ignorance (A)."},
    },
    # ---------------- depth: scope ----------------
    {
        "id": "lr-0047", "section": "LR", "stem_type": "qt.flaw",
        "schemas": ["flaw.scope.part_whole", "qt.flaw"],
        "difficulty": 3, "source": "original",
        "stimulus": "Each player on the team is excellent. Therefore, the team as a whole is excellent.",
        "question": "The reasoning is most vulnerable to criticism because it",
        "choices": [
            _c("A", "assumes that what is true of each part must be true of the whole.", correct=True),
            _c("B", "presumes the players want to win.", trap="trap.out_of_scope"),
            _c("C", "concludes the team will win every game.", trap="trap.too_strong_extreme"),
            _c("D", "ignores the coaching staff.", trap="trap.too_weak"),
            _c("E", "restates that the players are excellent.", trap="trap.premise_restatement"),
        ],
        "two_answer_fork": {"runner_up": "C", "why_runner_up_wrong": "C attacks a prediction not made; the flaw is a part-to-whole inference (A)."},
    },
    {
        "id": "lr-0048", "section": "LR", "stem_type": "qt.flaw",
        "schemas": ["flaw.scope.percent_vs_number", "qt.flaw"],
        "difficulty": 3, "source": "original",
        "stimulus": "This year a larger percentage of the small county's residents were hospitalized than in the huge neighboring city. So the county had more hospitalizations than the city.",
        "question": "The reasoning is most vulnerable to criticism because it",
        "choices": [
            _c("A", "confuses a higher proportion with a larger absolute number.", correct=True),
            _c("B", "assumes hospitalization rates are stable.", trap="trap.out_of_scope"),
            _c("C", "concludes the county is less healthy overall.", trap="trap.too_strong_extreme"),
            _c("D", "ignores the reasons for hospitalization.", trap="trap.out_of_scope"),
            _c("E", "restates that the percentage was higher.", trap="trap.premise_restatement"),
        ],
        "two_answer_fork": {"runner_up": "E", "why_runner_up_wrong": "E flags a restatement, but the decisive error is inferring a larger count from a larger percentage (A)."},
    },
    {
        "id": "lr-0049", "section": "LR", "stem_type": "qt.flaw",
        "schemas": ["flaw.scope.equivocation", "qt.flaw"],
        "difficulty": 4, "source": "original",
        "stimulus": "Any law limiting speech is wrong, because it is wrong to limit a person's natural freedom to speak, and law is a limit on freedom.",
        "question": "The reasoning is most vulnerable to criticism because it",
        "choices": [
            _c("A", "uses 'freedom' in two different senses across the argument.", correct=True),
            _c("B", "assumes all speech is valuable.", trap="trap.out_of_scope"),
            _c("C", "concludes that all laws are wrong.", trap="trap.too_strong_extreme"),
            _c("D", "ignores the benefits of some speech limits.", trap="trap.too_weak"),
            _c("E", "restates that limiting freedom is wrong.", trap="trap.premise_restatement"),
        ],
        "two_answer_fork": {"runner_up": "C", "why_runner_up_wrong": "C overstates the conclusion; the actual defect is equivocation on 'freedom' (A)."},
    },
    # ---------------- depth: assumption + structure ----------------
    {
        "id": "lr-0050", "section": "LR", "stem_type": "qt.necessary_assumption",
        "schemas": ["flaw.gap.unwarranted_assumption", "qt.necessary_assumption"],
        "difficulty": 3, "source": "original",
        "stimulus": "The new bridge will reduce commute times, because it gives drivers a shorter route downtown.",
        "question": "The argument depends on assuming which one of the following?",
        "choices": [
            _c("A", "A meaningful number of drivers will actually use the shorter route.", correct=True),
            _c("B", "The bridge is the shortest possible route downtown.", trap="trap.too_strong_extreme"),
            _c("C", "Commute times are the city's biggest problem.", trap="trap.out_of_scope"),
            _c("D", "The bridge was inexpensive to build.", trap="trap.out_of_scope"),
            _c("E", "Drivers dislike their current routes.", trap="trap.could_be_true"),
        ],
        "two_answer_fork": {"runner_up": "B", "why_runner_up_wrong": "B is too strong — the route need not be the shortest, only shorter; the argument only needs drivers to use it (A)."},
    },
    {
        "id": "lr-0051", "section": "LR", "stem_type": "qt.flaw",
        "schemas": ["flaw.structure.false_dilemma", "qt.flaw"],
        "difficulty": 2, "source": "original",
        "stimulus": "Either we cut the arts budget or the school goes bankrupt. We cannot let the school go bankrupt, so we must cut the arts budget.",
        "question": "The reasoning is most vulnerable to criticism because it",
        "choices": [
            _c("A", "presents only two options when others may be available.", correct=True),
            _c("B", "assumes the arts have no value.", trap="trap.half_right"),
            _c("C", "concludes the school is already bankrupt.", trap="trap.opposite"),
            _c("D", "ignores how much the arts cost.", trap="trap.out_of_scope"),
            _c("E", "restates that bankruptcy is bad.", trap="trap.premise_restatement"),
        ],
        "two_answer_fork": {"runner_up": "B", "why_runner_up_wrong": "B imports a value claim the argument never makes; the flaw is offering a false either/or (A)."},
    },
    {
        "id": "lr-0052", "section": "LR", "stem_type": "qt.flaw",
        "schemas": ["flaw.structure.straw_man", "qt.flaw"],
        "difficulty": 3, "source": "original",
        "stimulus": "My opponent wants to reduce the military budget. But leaving the nation defenseless is reckless, so her plan should be rejected.",
        "question": "The reasoning is most vulnerable to criticism because it",
        "choices": [
            _c("A", "distorts the opponent's position into a more extreme one that is easier to attack.", correct=True),
            _c("B", "relies on the opinion of an expert.", trap="trap.out_of_scope"),
            _c("C", "assumes the budget cannot be cut at all.", trap="trap.too_strong_extreme"),
            _c("D", "ignores the opponent's credentials.", trap="trap.out_of_scope"),
            _c("E", "restates that defense matters.", trap="trap.premise_restatement"),
        ],
        "two_answer_fork": {"runner_up": "C", "why_runner_up_wrong": "C misreads the conclusion; the defect is misrepresenting 'reduce' as 'leave defenseless' — a straw man (A)."},
    },
    {
        "id": "lr-0053", "section": "LR", "stem_type": "qt.flaw",
        "schemas": ["flaw.structure.ad_hominem", "qt.flaw"],
        "difficulty": 2, "source": "original",
        "stimulus": "The scientist's argument that the lake is polluted can be dismissed. After all, she once received funding from an environmental group.",
        "question": "The reasoning is most vulnerable to criticism because it",
        "choices": [
            _c("A", "attacks the source of the argument rather than its reasoning.", correct=True),
            _c("B", "assumes the lake is definitely clean.", trap="trap.opposite"),
            _c("C", "concludes all funded research is biased.", trap="trap.too_strong_extreme"),
            _c("D", "ignores the group's mission.", trap="trap.out_of_scope"),
            _c("E", "restates that she received funding.", trap="trap.premise_restatement"),
        ],
        "two_answer_fork": {"runner_up": "C", "why_runner_up_wrong": "C generalizes beyond the argument; the flaw is dismissing a claim by attacking its source (A)."},
    },
    {
        "id": "lr-0054", "section": "LR", "stem_type": "qt.strengthen",
        "schemas": ["flaw.causal.correlation_causation", "qt.strengthen"],
        "difficulty": 3, "source": "original",
        "stimulus": "Offices that added indoor plants reported higher worker satisfaction. The company concludes that the plants caused the increase.",
        "question": "Which one of the following, if true, most strengthens the argument?",
        "choices": [
            _c("A", "Offices otherwise identical but without added plants showed no rise in satisfaction over the same period.", correct=True),
            _c("B", "Workers generally find plants pleasant to look at.", trap="trap.premise_restatement"),
            _c("C", "The plants were inexpensive to maintain.", trap="trap.out_of_scope"),
            _c("D", "Satisfaction is hard to measure precisely.", trap="trap.too_weak"),
            _c("E", "Every office should add plants.", trap="trap.right_answer_wrong_question"),
        ],
        "two_answer_fork": {"runner_up": "B", "why_runner_up_wrong": "B merely restates plausibility; A rules out an alternative explanation with a controlled comparison, strengthening the causal claim."},
    },
    # ---------------- RC passage: fills rc.viewpoint_attribution + depth ----------------
    {
        "id": "rc-0025-q1", "section": "RC", "stem_type": "rc.viewpoint_attribution",
        "schemas": ["rc.viewpoint_attribution"], "difficulty": 3, "source": "original",
        "passage_id": "rc-0025",
        "passage": "For decades economists treated household saving as a purely rational response to interest rates. Behavioral researchers challenged this, arguing that habits and mental 'accounts' drive saving more than rates do. Traditional economists have not conceded the point; they respond that once uncertainty is modeled, the classical view still fits the data. A few younger scholars propose a synthesis: rates set the outer bounds of saving, while psychological factors determine where within those bounds a household lands.",
        "question": "The 'younger scholars' would most likely agree with which one of the following?",
        "choices": [
            _c("A", "Both interest rates and psychological factors shape how much households save.", correct=True),
            _c("B", "Interest rates have no effect on household saving.", trap="trap.rc.wrong_viewpoint"),
            _c("C", "Behavioral research has been entirely refuted.", trap="trap.rc.distortion_author_view"),
            _c("D", "Saving is a purely rational response to interest rates.", trap="trap.rc.wrong_viewpoint"),
            _c("E", "Economists should abandon modeling uncertainty.", trap="trap.out_of_scope"),
        ],
        "two_answer_fork": {"runner_up": "B", "why_runner_up_wrong": "B is the extreme behavioral view, not the synthesis; the younger scholars keep a role for rates (A)."},
    },
    {
        "id": "rc-0025-q2", "section": "RC", "stem_type": "rc.author_attitude",
        "schemas": ["rc.author_attitude"], "difficulty": 3, "source": "original",
        "passage_id": "rc-0025",
        "passage": "For decades economists treated household saving as a purely rational response to interest rates. Behavioral researchers challenged this, arguing that habits and mental 'accounts' drive saving more than rates do. Traditional economists have not conceded the point; they respond that once uncertainty is modeled, the classical view still fits the data. A few younger scholars propose a synthesis: rates set the outer bounds of saving, while psychological factors determine where within those bounds a household lands.",
        "question": "The author's attitude toward the synthesis proposed by the younger scholars is best described as",
        "choices": [
            _c("A", "neutral presentation without explicit endorsement or rejection.", correct=True),
            _c("B", "open hostility.", trap="trap.rc.tone_mismatch"),
            _c("C", "unqualified enthusiasm.", trap="trap.rc.tone_mismatch"),
            _c("D", "dismissive skepticism.", trap="trap.rc.tone_mismatch"),
            _c("E", "personal regret.", trap="trap.out_of_scope"),
        ],
        "two_answer_fork": {"runner_up": "C", "why_runner_up_wrong": "The author reports the synthesis without praising it; 'unqualified enthusiasm' overstates a neutral, descriptive tone (A)."},
    },
    {
        "id": "rc-0025-q3", "section": "RC", "stem_type": "rc.function_of_detail",
        "schemas": ["rc.function_of_detail"], "difficulty": 3, "source": "original",
        "passage_id": "rc-0025",
        "passage": "For decades economists treated household saving as a purely rational response to interest rates. Behavioral researchers challenged this, arguing that habits and mental 'accounts' drive saving more than rates do. Traditional economists have not conceded the point; they respond that once uncertainty is modeled, the classical view still fits the data. A few younger scholars propose a synthesis: rates set the outer bounds of saving, while psychological factors determine where within those bounds a household lands.",
        "question": "The mention that traditional economists 'have not conceded the point' functions primarily to",
        "choices": [
            _c("A", "show that the debate remained unresolved before the synthesis was offered.", correct=True),
            _c("B", "prove that the behavioral researchers were mistaken.", trap="trap.rc.distortion_author_view"),
            _c("C", "introduce the author's own original theory.", trap="trap.rc.wrong_viewpoint"),
            _c("D", "criticize traditional economists for stubbornness.", trap="trap.rc.tone_mismatch"),
            _c("E", "recommend a new savings policy.", trap="trap.right_answer_wrong_question"),
        ],
        "two_answer_fork": {"runner_up": "B", "why_runner_up_wrong": "The detail shows an ongoing standoff, not that either side was proven wrong; B distorts the author's neutral report (A)."},
    },
]


def main() -> int:
    data = json.loads(SEED.read_text(encoding="utf-8"))
    existing = {i["id"] for i in data["items"]}
    added = 0
    for item in NEW_ITEMS:
        if item["id"] in existing:
            continue
        # sanity: exactly one correct choice
        n_correct = sum(1 for c in item["choices"] if c.get("correct"))
        assert n_correct == 1, f"{item['id']} must have exactly one correct choice"
        data["items"].append(item)
        existing.add(item["id"])
        added += 1
    SEED.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"Added {added} new items. Total now: {len(data['items'])}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
