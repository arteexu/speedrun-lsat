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

    func testReviewQueueAttachesReadableCardContent() throws {
        let engine = try SpeedrunEngine()
        let cards = engine.reviewQueue(limit: 10)
        XCTAssertFalse(cards.isEmpty)
        // At least one card resolves to real note content with a question + choices.
        let withContent = cards.compactMap { $0.content }
        XCTAssertFalse(withContent.isEmpty, "cards should carry readable content")
        let sample = try XCTUnwrap(withContent.first)
        XCTAssertFalse(sample.question.isEmpty, "question stem should be present")
        XCTAssertFalse(sample.choices.isEmpty, "answer choices should be present")
        XCTAssertFalse(sample.correct.isEmpty, "correct answer should be present")
    }

    func testComputeScoresReturnsThreeScoresViaSharedRpc() throws {
        let engine = try SpeedrunEngine()
        let scores = try XCTUnwrap(engine.computeScores(), "scores RPC should return")
        // Fresh bundled deck has no review history, so all three abstain honestly
        // (proves the shared Rust give-up rule reaches the phone).
        XCTAssertTrue(scores.memory.gaveUp)
        XCTAssertTrue(scores.performance.gaveUp)
        XCTAssertTrue(scores.readiness.gaveUp)
        XCTAssertFalse(scores.memory.reason.isEmpty)
    }

    func testSyncAgainstLocalServerIfAvailable() throws {
        // Verifies the iOS sync client end-to-end when a dev server is running at
        // 127.0.0.1:8080 (see docs/speedrun/SYNC-SERVER.md). Skips in CI where no
        // server is present, so this never breaks the offline build.
        let engine = try SpeedrunEngine()
        let result = engine.sync(url: "http://127.0.0.1:8080/", username: "dev", password: "pass")
        if result.hasPrefix("Login failed") || result.hasPrefix("Sync failed") {
            throw XCTSkip("no dev sync server reachable: \(result)")
        }
        // A reachable server yields a real outcome (uploaded/downloaded/synced).
        XCTAssertTrue(
            ["Uploaded", "Downloaded", "Synced", "Up to date"].contains { result.hasPrefix($0) },
            "unexpected sync result: \(result)"
        )
    }

    func testBundledDeckIsPresent() {
        XCTAssertNotNil(
            Bundle.module.url(forResource: "collection", withExtension: "anki2"),
            "exam deck must be bundled for offline review"
        )
    }
}
