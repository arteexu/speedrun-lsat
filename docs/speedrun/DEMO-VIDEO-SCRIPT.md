# Speedrun LSAT — Demo Video Script (read aloud)

One consolidated spoken-word narration for a 3–5 minute demo. The learning-science
rationale is woven into each demo beat, so you can just read the lines top to bottom.
Stage cues are in *italics* — don't read those aloud.

**Before you hit record:**
1. Seed demo stats so everything is populated: quit Anki, then
   `PYTHONPATH=out/pylib out/pyenv/bin/python speedrun/tools/seed_demo_stats.py --col "$HOME/dev/speedrun-lsat/.ankidata/User 1/collection.anki2"`, relaunch.
2. Enable AI: Tools → LSAT Speedrun → **AI Settings** → tick Enable, paste your key (so generative answers name the model live).
3. Sync server running on `http://127.0.0.1:8090/`; iOS simulator app open.

---

### [0:00–0:30] Hook + the core idea
*On screen: desktop dashboard (Tools → LSAT Speedrun → Dashboard).*

"This is Speedrun LSAT — an accelerated LSAT trainer I built as a fork of Anki, right inside its Rust engine. The whole thing is built on one conviction from the learning science: the LSAT isn't a memorization test, it's a *transfer* test. So the unit of mastery here isn't a flashcard — it's the *schema*, the reusable reasoning pattern behind a question. Everything you're about to see is organized around schemas, and the app is honesty-first: it refuses to show you a score until it actually has the evidence to back it up."

### [0:30–1:20] Three scores + the schema-weighted queue
*On screen: the three scores, the per-schema heat map, the study queue.*

"Here are the three scores, and they deliberately measure three different things. **Memory** is just recall — that's Anki's FSRS spaced-repetition engine, and I use it only for the small memorizable layer, flaw and trap definitions, because on the LSAT there's very little to actually memorize. **Performance** is the one that matters: can you get a *new, unseen* item right using this schema? That's the memory-to-transfer bridge, and I measure the gap between the two on purpose. **Readiness** projects a 120-to-180 score with a range. And notice the study queue — it interleaves schemas and question types instead of blocking them, because interleaving is what forces the 'which pattern is this?' discrimination the real exam demands."

### [1:20–2:05] AI that always cites a source, and degrades safely
*On screen: AI Tutor on a problem, then "What to study next".*

"Now the AI — and the rule I held to is that every AI output traces back to a named source. Watch: I open the tutor on this problem and ask why the runner-up is wrong. The answer is grounded in *this item's* own stimulus and rationale, and it names its source right there — nothing shown unless it carries one. That's retrieval practice of the *reasoning*, not a fact lookup. Over here, 'what to study next' turns my weakest high-value schemas into a plan with reasons. And critically, the AI is off by default and everything degrades safely — with AI switched off, all three scores still compute straight from the review log."

### [2:05–2:50] The eval gate — my differentiator
*On screen: terminal — `PYTHONPATH=out/pylib out/pyenv/bin/python -m speedrun.eval.grounding_eval`.*

"Before any AI-touched content reaches a student, this eval runs as a gate. On a held-out set, my grounded approach hits **50% accuracy with a 50% wrong-answer rate**, and it has to clear a **0.4 cutoff** or the build fails. And here's the side-by-side: grounded scores **0.305** on F1 versus **0.23** for keyword search and **0.24** for a vector search on the exact same set. The edge is *what* it grounds in — an authoritative named source, the schema taxonomy — which is exactly why the AI beats plain search. That's my accuracy, wrong-rate, and baseline comparison, all on one screen, fully offline and reproducible."

### [2:50–3:35] Analytics depth — error analysis and metacognition
*On screen: mistake graph, concept map, Focus / study by subject.*

"Back on the dashboard, this is where the learning science gets concrete. The **mistake graph** surfaces the *habitual trap types* I keep falling for — which is far more diagnostic than just 'which question did I miss.' The concept map shows schema mastery at a glance, and 'focus by subject' lets me drill my weakest areas directly. It's error analysis turned into targeted practice, and it's also why readiness stays honest — it won't report a number until there are enough transfer attempts and enough coverage. No guess dressed up in a nice font."

### [3:35–4:40] Mobile + two-way sync — the recording
*On screen: iOS simulator home, then Study, then Sync, then desktop Sync.*

"On the phone, the same three scores show up *with their ranges* and follow the same give-up rule — if there isn't enough evidence, it says 'no score yet' instead of faking one. I'll study the exam deck and grade a card right here — that records a real review through the *same shared Rust scheduler*, not a reimplementation. Reviews are stored on-device, so this works offline, then syncs when the connection's back. I'll sync now… switch to the desktop… hit Sync… and there's the review I just did on the phone, showing up on the desktop — counted once, no duplication, and it works in both directions."

### [4:40–5:00] Close
*On screen: dashboard.*

"So: license-clean original content, scores that separate memory from transfer and refuse to guess, AI that always cites a source and is gated by an eval that beats keyword and vector baselines, and real two-way sync across desktop and phone. It's a study app built on how people actually learn to transfer — not just to remember. Thanks for watching."

---

*Honesty notes for recording: the generation eval only passes with an API key configured (offline it deliberately refuses), so enable AI in setup step 2 if you want it green on camera. The phone→desktop round-trip is proven at the mechanism level — the live capture in the [3:35] beat is your on-camera proof.*
