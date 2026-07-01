import XCTest
@testable import AnkiKit

/// Proves the phone loads the exam deck and runs a review pass on the *shared*
/// Rust engine: open the bundled deck, then build the schema-weighted queue via
/// the same scheduler RPC the desktop uses, and step through the ordered cards.
final class SpeedrunEngineTests: XCTestCase {
    func testOpensExamDeckAndBuildsSchemaWeightedQueue() throws {
        let engine = try SpeedrunEngine()
        let queue = engine.schemaWeightedQueue(limit: 100)

        XCTAssertGreaterThanOrEqual(
            queue.count, 40,
            "the bundled exam deck should yield its schema-tagged cards"
        )
        // Every queued card is a unit of mastery (carries a schema).
        XCTAssertTrue(queue.allSatisfy { !$0.schema.isEmpty })
        // Rust ordering guarantee: priorities are non-increasing.
        let priorities = queue.map { $0.priority }
        XCTAssertEqual(priorities, priorities.sorted(by: >))
    }

    func testReviewPassStepsThroughEngineOrderedCards() throws {
        let engine = try SpeedrunEngine()
        let queue = engine.schemaWeightedQueue(limit: 100)
        XCTAssertFalse(queue.isEmpty)

        // A minimal review session: walk the engine-ordered queue and collect the
        // distinct schemas we would drill. This is driven entirely by the shared
        // engine's ordering, not any Swift-side sorting.
        var reviewed = 0
        var schemas = Set<String>()
        for card in queue {
            XCTAssertGreaterThan(card.cardId, 0)
            schemas.insert(card.schema)
            reviewed += 1
            if reviewed >= 10 { break }
        }
        XCTAssertGreaterThanOrEqual(reviewed, 10)
        XCTAssertGreaterThanOrEqual(schemas.count, 2, "review interleaves schemas")
    }

    func testBundledDeckIsPresent() {
        XCTAssertNotNil(
            Bundle.module.url(forResource: "collection", withExtension: "anki2"),
            "exam deck must be bundled for offline review"
        )
    }
}
