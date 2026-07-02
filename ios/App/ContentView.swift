// Copyright: Speedrun LSAT contributors
// License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html
//
// SwiftUI companion with daily goal, three-score placeholders, weakest schemas,
// and study CTA. Full review UI ships later; scores read from shared config format.

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
    @State private var memoryLabel = "—"
    @State private var performanceLabel = "—"
    @State private var readinessLabel = "—"
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
                    LabeledContent("Memory", value: memoryLabel)
                    LabeledContent("Performance", value: performanceLabel)
                    LabeledContent("Readiness", value: readinessLabel)
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
        if let s = engine.computeScores() {
            memoryLabel = Self.fmtProb(s.memory)
            performanceLabel = Self.fmtProb(s.performance)
            readinessLabel = Self.fmtScale(s.readiness)
        }
        weakest = engine.schemaWeightedQueue(limit: 3).map { $0.schema }
    }

    private static func fmtProb(_ s: ScoreValue) -> String {
        s.gaveUp
            ? "No score yet"
            : String(format: "%.0f%% (likely %.0f–%.0f%%)", s.point * 100, s.low * 100, s.high * 100)
    }

    private static func fmtScale(_ s: ScoreValue) -> String {
        s.gaveUp
            ? "No score yet"
            : String(format: "%.0f (range %.0f–%.0f)", s.point, s.low, s.high)
    }
}

#Preview {
    ContentView()
}
