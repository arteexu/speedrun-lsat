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
    @State private var revealed = false
    @State private var loadError: String?

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
                        HStack(spacing: 12) {
                            Button("Again", role: .destructive) { advance() }
                                .buttonStyle(.bordered)
                            Button("Good") { advance() }
                                .buttonStyle(.borderedProminent)
                        }
                    } else {
                        Button("Reveal answer") { revealed = true }
                            .buttonStyle(.borderedProminent)
                    }
                    Text("Reviewed \(reviewed) this session")
                        .font(.footnote)
                        .foregroundStyle(.secondary)
                }
                .padding()
            }
        }
        .navigationTitle("Review")
        .onAppear(perform: load)
    }

    private func load() {
        guard queue.isEmpty, loadError == nil else { return }
        do {
            let engine = try SpeedrunEngine()
            queue = engine.reviewQueue(limit: 100)
            // Demo/test hook: start with the answer revealed.
            if ProcessInfo.processInfo.environment["SPEEDRUN_REVEAL"] == "1" {
                revealed = true
            }
        } catch {
            loadError = "\(error)"
        }
    }

    private func advance() {
        reviewed += 1
        revealed = false
        index = (index + 1) % max(1, queue.count)
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
