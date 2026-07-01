import XCTest
@testable import AnkiKit

final class AnkiBackendTests: XCTestCase {
    func testBuildHashNonEmpty() {
        let hash = AnkiBackend.buildHash()
        XCTAssertFalse(hash.isEmpty, "Anki engine build hash should be non-empty")
    }
}
