// Copyright: Speedrun LSAT contributors
// License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html
//
// One shared engine over a persistent collection in Documents, so the whole app
// (dashboard scores + review + sync) uses a single SQLite connection - avoiding
// the file-lock conflicts two separate engines on the same collection would hit.

import AnkiKit
import Foundation

final class SpeedrunSession {
    static let shared = SpeedrunSession()
    let engine: SpeedrunEngine?

    // Serialize sync so overlapping review sessions never run two syncs at once
    // on the shared collection.
    private let syncQueue = DispatchQueue(label: "com.speedrunlsat.autosync")

    private init() {
        engine = try? SpeedrunEngine(persistent: true)
    }

    /// Best-effort, non-blocking sync after on-device reviews. Reuses the same
    /// `BackendSyncService` path as `SyncView` (via `SpeedrunEngine.sync`). It is
    /// a no-op unless the user has configured a server (URL + username + password
    /// persisted by `SyncView`), and it never blocks or crashes the review flow —
    /// failures (offline / no server / bad creds) are swallowed here; the manual
    /// Sync screen surfaces real status.
    func autoSyncAfterReviews() {
        guard let engine else { return }
        let defaults = UserDefaults.standard
        let url = defaults.string(forKey: "sync.url") ?? ""
        let user = defaults.string(forKey: "sync.user") ?? ""
        let pass = defaults.string(forKey: "sync.pass") ?? ""
        guard !url.isEmpty, !user.isEmpty, !pass.isEmpty else { return }
        syncQueue.async {
            _ = engine.sync(url: url, username: user, password: pass)
        }
    }
}
