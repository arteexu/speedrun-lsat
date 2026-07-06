// Copyright: Speedrun LSAT contributors
// License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html
//
// SwiftUI companion with daily goal, the three honest scores (each with its
// likely range, a how-sure indicator, and the engine's reason/next-step text),
// weakest schemas, and a study CTA. Scores come from the shared Rust RPC.

import AnkiKit
import SwiftUI

struct SpeedrunConfig: Codable {
    var dailyStudyGoalCards: Int
    var dailyStudyGoalMinutes: Int?
    var interleavingEnabled: Bool
    var sectionFilter: String?

    enum CodingKeys: String, CodingKey {
        case dailyStudyGoalCards = "daily_study_goal_cards"
        case dailyStudyGoalMinutes = "daily_study_goal_minutes"
        case interleavingEnabled = "interleaving_enabled"
        case sectionFilter = "section_filter"
    }

    static let `default` = SpeedrunConfig(
        dailyStudyGoalCards: 20,
        dailyStudyGoalMinutes: nil,
        interleavingEnabled: true,
        sectionFilter: nil
    )
}

struct ContentView: View {
    @State private var engineBuild = "loading…"
    @State private var config = SpeedrunConfig.default
    @State private var cardsToday = 0
    @State private var streakDays = 0
    @State private var scores: ThreeScores?
    @State private var weakest: [String] = []

    var body: some View {
        NavigationStack {
            List {
                Section("Engine") {
                    LabeledContent("build hash", value: engineBuild)
                }
                Section("Daily goal") {
                    ProgressView(
                        value: Double(cardsToday),
                        total: Double(max(1, config.dailyStudyGoalCards))
                    )
                    LabeledContent("cards today", value: "\(cardsToday)/\(config.dailyStudyGoalCards)")
                    LabeledContent("streak", value: "\(streakDays) day(s)")
                }
                Section("Three scores") {
                    if let scores {
                        ScoreRow(title: "Memory", score: scores.memory, kind: .probability, evidenceNoun: "reviews")
                        ScoreRow(title: "Performance", score: scores.performance, kind: .probability, evidenceNoun: "attempts")
                        ScoreRow(title: "Readiness", score: scores.readiness, kind: .lsatScale, evidenceNoun: "attempts")
                    } else {
                        Text("Open the deck and review to compute scores.")
                            .foregroundStyle(.secondary)
                    }
                }
                Section("Weakest schemas") {
                    if weakest.isEmpty {
                        Text("Review on desktop to populate weakness map.")
                            .foregroundStyle(.secondary)
                    } else {
                        ForEach(weakest, id: \.self) { schema in
                            Text(schema)
                        }
                    }
                }
                Section("Exam deck") {
                    LabeledContent("cards in deck", value: deckCount >= 0 ? "\(deckCount)" : "…")
                    NavigationLink {
                        ReviewView()
                    } label: {
                        Label("Study the exam deck", systemImage: "play.circle.fill")
                    }
                    NavigationLink {
                        SyncView()
                    } label: {
                        Label("Sync with desktop", systemImage: "arrow.triangle.2.circlepath")
                    }
                }
            }
            .navigationTitle("Speedrun LSAT")
        }
        .onAppear {
            engineBuild = AnkiBackend.buildHash()
            config = SpeedrunConfig.default
            loadEngineState()
        }
    }

    @State private var deckCount = -1

    private func loadEngineState() {
        // Single shared engine (persistent collection) computes the real scores
        // via the shared Rust RPC. On a fresh deck (no reviews) all three abstain;
        // after a sync brings desktop reviews down, they become real numbers.
        guard let engine = SpeedrunSession.shared.engine else {
            deckCount = 0
            return
        }
        deckCount = engine.schemaWeightedQueue(limit: 500).count
        scores = engine.computeScores()
        weakest = engine.schemaWeightedQueue(limit: 3).map { $0.schema }
    }
}

/// One honest score, matching the desktop dashboard: point estimate, likely
/// range, a "how sure" indicator derived from the returned range, and the short
/// reason / next-step text the shared engine already returns (`ScoreValue.reason`).
/// The honesty rule (PRD §10/§13) forbids showing a bare number, so an abstaining
/// score renders only its reason.
private struct ScoreRow: View {
    enum Kind { case probability, lsatScale }

    let title: String
    let score: ScoreValue
    let kind: Kind
    let evidenceNoun: String

    var body: some View {
        VStack(alignment: .leading, spacing: 3) {
            HStack(alignment: .firstTextBaseline) {
                Text(title).font(.headline)
                Spacer()
                Text(valueText)
                    .font(.headline)
                    .monospacedDigit()
                    .foregroundStyle(score.gaveUp ? .secondary : .primary)
            }
            if !score.gaveUp {
                Text(rangeText)
                    .font(.subheadline)
                    .foregroundStyle(.secondary)
                    .monospacedDigit()
                HStack(spacing: 5) {
                    Image(systemName: "gauge")
                    Text("Confidence: \(confidenceLabel) · based on \(score.n) \(evidenceNoun)")
                }
                .font(.caption)
                .foregroundStyle(confidenceColor)
            }
            if !score.reason.isEmpty {
                Text(score.reason)
                    .font(.caption)
                    .foregroundStyle(.secondary)
                    .fixedSize(horizontal: false, vertical: true)
            }
        }
        .padding(.vertical, 2)
    }

    private var valueText: String {
        if score.gaveUp { return "No score yet" }
        switch kind {
        case .probability: return String(format: "%.0f%%", score.point * 100)
        case .lsatScale: return String(format: "%.0f", score.point)
        }
    }

    private var rangeText: String {
        switch kind {
        case .probability:
            return String(format: "likely %.0f–%.0f%%", score.low * 100, score.high * 100)
        case .lsatScale:
            return String(format: "likely range %.0f–%.0f", score.low, score.high)
        }
    }

    /// "How sure" tied to the width of the engine's own range (a wider band means
    /// less certainty) so the indicator can never contradict the number shown.
    private var confidenceLabel: String {
        switch confidenceTier {
        case 2: return "high"
        case 1: return "medium"
        default: return "low"
        }
    }

    private var confidenceColor: Color {
        switch confidenceTier {
        case 2: return .green
        case 1: return .orange
        default: return .red
        }
    }

    private var confidenceTier: Int {
        let width = score.high - score.low
        switch kind {
        case .probability:
            if width < 0.15 { return 2 }
            if width < 0.35 { return 1 }
            return 0
        case .lsatScale:
            if width < 8 { return 2 }
            if width < 18 { return 1 }
            return 0
        }
    }
}

#Preview {
    ContentView()
}
