// Copyright: Speedrun LSAT contributors
// License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html
//
// A real review session on the phone: it opens the bundled exam deck and steps
// through the schema-weighted queue produced by the shared Rust engine (the same
// ordering the desktop uses). Full FSRS grading lives in the engine; here we
// drive a schema-interleaved review pass over the engine-ordered cards.

import AnkiKit
import SwiftUI

struct ReviewView: View {
    @State private var queue: [ReviewCard] = []
    @State private var index = 0
    @State private var reviewed = 0
    @State private var recorded = 0
    @State private var revealed = false
    @State private var loadError: String?
    // When the current card was first shown, used to record the answer latency
    // (Anki stores `milliseconds_taken` on every review).
    @State private var shownAt = Date()

    var body: some View {
        VStack(spacing: 0) {
            if let loadError {
                ContentUnavailableView(
                    "Couldn't load the exam deck",
                    systemImage: "exclamationmark.triangle",
                    description: Text(loadError)
                )
            } else if queue.isEmpty {
                ProgressView("Loading exam deck on the shared engine…")
            } else {
                let card = queue[index]
                ScrollView {
                    VStack(alignment: .leading, spacing: 16) {
                        Text("Card \(index + 1) of \(queue.count)  ·  \(prettySchema(card.schema))")
                            .font(.caption)
                            .foregroundStyle(.secondary)

                        if let c = card.content {
                            Text(c.stimulus)
                                .font(.body)
                            Text(c.question)
                                .font(.callout).bold()
                            Text(c.choices)
                                .font(.body)
                                .frame(maxWidth: .infinity, alignment: .leading)
                                .padding()
                                .background(.quaternary, in: RoundedRectangle(cornerRadius: 12))
                        } else {
                            Text("Schema under test: \(prettySchema(card.schema))")
                                .font(.title3).bold()
                            Text("(Card text unavailable for this note.)")
                                .font(.caption).foregroundStyle(.secondary)
                        }
                    }
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .padding()
                }

                // Pinned bottom area: the answer appears here on reveal so it is
                // always visible, never buried below the choices.
                VStack(spacing: 10) {
                    if revealed, let c = card.content {
                        VStack(alignment: .leading, spacing: 6) {
                            Text("Correct answer: \(c.correct)")
                                .font(.headline)
                                .foregroundStyle(.green)
                            if !c.whyRunnerUpWrong.isEmpty {
                                Text("Why the runner-up (\(c.runnerUp)) is wrong")
                                    .font(.subheadline).bold()
                                Text(c.whyRunnerUpWrong)
                                    .font(.callout)
                                    .foregroundStyle(.secondary)
                            }
                        }
                        .frame(maxWidth: .infinity, alignment: .leading)
                        .padding()
                        .background(.green.opacity(0.14), in: RoundedRectangle(cornerRadius: 12))
                    }

                    if revealed {
                        // The four standard grades. Each records a real review on
                        // the shared Rust scheduler (Again=0…Easy=3 on the wire),
                        // then advances to the next engine-ordered card.
                        HStack(spacing: 8) {
                            Button("Again", role: .destructive) { grade(.again) }
                                .buttonStyle(.bordered)
                            Button("Hard") { grade(.hard) }
                                .buttonStyle(.bordered)
                            Button("Good") { grade(.good) }
                                .buttonStyle(.borderedProminent)
                            Button("Easy") { grade(.easy) }
                                .buttonStyle(.bordered)
                        }
                    } else {
                        Button("Reveal answer") { revealed = true }
                            .buttonStyle(.borderedProminent)
                    }
                    Text("Reviewed \(reviewed) this session · \(recorded) recorded")
                        .font(.footnote)
                        .foregroundStyle(.secondary)
                }
                .padding()
            }
        }
        .navigationTitle("Review")
        .onAppear(perform: load)
        .onDisappear {
            // Best-effort: push the reviews we just recorded to a configured
            // server. No-op if none were recorded or no server is set up.
            if recorded > 0 { SpeedrunSession.shared.autoSyncAfterReviews() }
        }
    }

    private func load() {
        guard queue.isEmpty, loadError == nil else { return }
        // Use the shared persistent engine so review and scores see one collection.
        guard let engine = SpeedrunSession.shared.engine else {
            loadError = "engine unavailable"
            return
        }
        queue = engine.reviewQueue(limit: 100)
        shownAt = Date()
        // Demo/test hook: start with the answer revealed.
        if ProcessInfo.processInfo.environment["SPEEDRUN_REVEAL"] == "1" {
            revealed = true
        }
    }

    /// Record the grade on the shared engine, then advance. The engine writes a
    /// revlog entry and reschedules the card (same scheduler the desktop uses),
    /// so the dashboard scores update and there is real data to sync.
    private func grade(_ rating: Rating) {
        guard index < queue.count else { advance(); return }
        // Answer latency: how long the card was on screen (capped to 10 min).
        let elapsed = min(max(Date().timeIntervalSince(shownAt), 0), 600)
        let millis = UInt32(elapsed * 1000)
        if let engine = SpeedrunSession.shared.engine,
           engine.answerCard(cardId: queue[index].cardId, rating: rating, millisecondsTaken: millis) {
            recorded += 1
        }
        advance()
    }

    private func advance() {
        reviewed += 1
        revealed = false
        // Advance through the engine-ordered queue; when it's exhausted, ask the
        // engine for a freshly re-scored batch rather than looping a local index.
        if index + 1 >= queue.count {
            if let engine = SpeedrunSession.shared.engine {
                queue = engine.reviewQueue(limit: 100)
            }
            index = 0
        } else {
            index += 1
        }
        shownAt = Date()
    }

    private func prettySchema(_ id: String) -> String {
        id.split(separator: ".").last.map(String.init)?
            .replacingOccurrences(of: "_", with: " ")
            .capitalized ?? id
    }
}

#Preview {
    NavigationStack { ReviewView() }
}
