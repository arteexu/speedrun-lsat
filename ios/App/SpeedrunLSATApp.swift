// Copyright: Speedrun LSAT contributors
// License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

import SwiftUI

@main
struct SpeedrunLSATApp: App {
    var body: some Scene {
        WindowGroup {
            // Test/demo hook: launch straight into the review session with
            // SIMCTL_CHILD_SPEEDRUN_START_REVIEW=1.
            if ProcessInfo.processInfo.environment["SPEEDRUN_START_REVIEW"] == "1" {
                NavigationStack { ReviewView() }
            } else {
                ContentView()
            }
        }
    }
}
