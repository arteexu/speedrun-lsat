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

    private init() {
        engine = try? SpeedrunEngine(persistent: true)
    }
}
