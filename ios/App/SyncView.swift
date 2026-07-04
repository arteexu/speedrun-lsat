// Copyright: Speedrun LSAT contributors
// License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html
//
// Two-way sync against a self-hosted server (see docs/speedrun/SYNC-SERVER.md).
// Uses the same BackendSyncService RPCs as the desktop, on the shared engine.

import AnkiKit
import SwiftUI

struct SyncView: View {
    @AppStorage("sync.url") private var url = "http://127.0.0.1:8080/"
    @AppStorage("sync.user") private var username = "dev"
    // Persisted so post-review auto-sync (SpeedrunSession) has credentials. This
    // is a self-hosted dev tool; UserDefaults is not a secure secret store, so a
    // production build should move this to the Keychain.
    @AppStorage("sync.pass") private var password = "pass"
    @State private var status = "Not synced yet"
    @State private var busy = false

    var body: some View {
        Form {
            Section("Server") {
                TextField("Server URL", text: $url)
                    .textInputAutocapitalization(.never)
                    .autocorrectionDisabled()
                TextField("Username", text: $username)
                    .textInputAutocapitalization(.never)
                    .autocorrectionDisabled()
                SecureField("Password", text: $password)
            }
            Section {
                Button {
                    runSync()
                } label: {
                    HStack {
                        Label("Sync now", systemImage: "arrow.triangle.2.circlepath")
                        if busy { Spacer(); ProgressView() }
                    }
                }
                .disabled(busy)
            } footer: {
                Text("Reviews you do offline upload on the next sync; desktop reviews download here. No reviews are lost or double-counted.")
            }
            Section("Status") {
                Text(status).foregroundStyle(.secondary)
            }
        }
        .navigationTitle("Sync")
    }

    private func runSync() {
        guard let engine = SpeedrunSession.shared.engine else {
            status = "Engine unavailable"
            return
        }
        busy = true
        status = "Syncing…"
        let (u, user, pass) = (url, username, password)
        DispatchQueue.global().async {
            let result = engine.sync(url: u, username: user, password: pass)
            DispatchQueue.main.async {
                status = result
                busy = false
            }
        }
    }
}

#Preview {
    NavigationStack { SyncView() }
}
