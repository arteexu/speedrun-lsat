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
                Section {
                    Button("Study (opens deck on device)") {
                        // Hook to AnkiBackend review loop when UI ships
                    }
                    .buttonStyle(.borderedProminent)
                }
            }
            .navigationTitle("Speedrun LSAT")
        }
        .onAppear {
            engineBuild = AnkiBackend.buildHash()
            loadPlaceholderState()
        }
    }

    private func loadPlaceholderState() {
        // Offline placeholders until collection sync; mirrors speedrun/config.json keys.
        config = SpeedrunConfig.default
        cardsToday = 0
        streakDays = 0
        memoryLabel = "No score yet"
        performanceLabel = "No score yet"
        readinessLabel = "No score yet"
        weakest = [
            "flaw.causal.correlation_causation",
            "flaw.conditional.mistaken_reversal",
            "qt.necessary_assumption",
        ]
    }
}

#Preview {
    ContentView()
}
