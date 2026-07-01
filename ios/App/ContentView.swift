// Copyright: Speedrun LSAT contributors
// License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html
//
// Sample SwiftUI screen for the Speedrun LSAT companion. Add this file to an
// iOS App target that depends on the local AnkiKit package. The build-hash
// readout proves the shared Rust engine loads and runs on the device; the review
// loop and three-score dashboard are layered on top using SwiftProtobuf messages
// through AnkiBackend.runCommand(...).

import AnkiKit
import SwiftUI

struct ContentView: View {
    @State private var engineBuild = "loading…"

    var body: some View {
        VStack(spacing: 16) {
            Text("Speedrun LSAT").font(.largeTitle).bold()
            Text("Shared Anki engine (Rust) running on device")
                .font(.subheadline).foregroundStyle(.secondary)
            GroupBox("Engine") {
                LabeledContent("build hash", value: engineBuild)
            }
            Spacer()
        }
        .padding()
        .onAppear { engineBuild = AnkiBackend.buildHash() }
    }
}

#Preview {
    ContentView()
}
