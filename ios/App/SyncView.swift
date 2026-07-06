// Copyright: Speedrun LSAT contributors
// License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html
//
// Two-way sync against a self-hosted server (see docs/speedrun/SYNC-SERVER.md).
// Uses the same BackendSyncService RPCs as the desktop, on the shared engine.

import AnkiKit
import SwiftUI

struct SyncView: View {
    @AppStorage("sync.url") private var url = "http://127.0.0.1:8083/"
    @AppStorage("sync.user") private var username = "dev"
    // Persisted so post-review auto-sync (SpeedrunSession) has credentials. This
    // is a self-hosted dev tool; UserDefaults is not a secure secret store, so a
    // production build should move this to the Keychain.
    @AppStorage("sync.pass") private var password = "pass"
    @State private var status = "Not synced yet"
    @State private var busy = false
    @State private var confirmDownload = false

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

                Button(role: .destructive) {
                    confirmDownload = true
                } label: {
                    Label("Download from server (replace phone)", systemImage: "arrow.down.circle")
                }
                .disabled(busy)
                .confirmationDialog(
                    "Replace this phone's collection with the server's?",
                    isPresented: $confirmDownload,
                    titleVisibility: .visible
                ) {
                    Button("Download & replace", role: .destructive) { runDownload() }
                    Button("Cancel", role: .cancel) {}
                } message: {
                    Text("Use this once to seed the phone from a desktop that has already uploaded. Local unsynced phone reviews are discarded.")
                }
            } footer: {
                Text("Reviews you do offline upload on the next sync; desktop reviews download here. No reviews are lost or double-counted. First time on a fresh phone, use “Download from server” to pull the desktop's collection.")
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

    private func runDownload() {
        guard let engine = SpeedrunSession.shared.engine else {
            status = "Engine unavailable"
            return
        }
        busy = true
        status = "Downloading from server…"
        let (u, user, pass) = (url, username, password)
        DispatchQueue.global().async {
            let result = engine.downloadFromServer(url: u, username: user, password: pass)
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
