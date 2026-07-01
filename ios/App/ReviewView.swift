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
    @State private var queue: [ScoredCard] = []
    @State private var index = 0
    @State private var reviewed = 0
    @State private var revealed = false
    @State private var loadError: String?

    var body: some View {
        VStack(spacing: 24) {
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
                Text("Card \(index + 1) of \(queue.count)")
                    .font(.caption)
                    .foregroundStyle(.secondary)

                VStack(spacing: 8) {
                    Text("SCHEMA UNDER TEST")
                        .font(.caption2)
                        .foregroundStyle(.secondary)
                    Text(prettySchema(card.schema))
                        .font(.title2).bold()
                        .multilineTextAlignment(.center)
                    Text(String(format: "points at stake: %.3f", card.priority))
                        .font(.caption)
                        .foregroundStyle(.secondary)
                }
                .frame(maxWidth: .infinity)
                .padding()
                .background(.quaternary, in: RoundedRectangle(cornerRadius: 16))

                if revealed {
                    HStack(spacing: 12) {
                        Button("Again", role: .destructive) { advance() }
                            .buttonStyle(.bordered)
                        Button("Good") { advance() }
                            .buttonStyle(.borderedProminent)
                    }
                } else {
                    Button("Reveal") { revealed = true }
                        .buttonStyle(.borderedProminent)
                }

                Text("Reviewed \(reviewed) this session")
                    .font(.footnote)
                    .foregroundStyle(.secondary)
            }
        }
        .padding()
        .navigationTitle("Review")
        .onAppear(perform: load)
    }

    private func load() {
        guard queue.isEmpty, loadError == nil else { return }
        do {
            let engine = try SpeedrunEngine()
            queue = engine.schemaWeightedQueue(limit: 100)
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
