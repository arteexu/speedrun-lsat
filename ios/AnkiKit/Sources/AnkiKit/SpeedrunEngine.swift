// Copyright: Speedrun LSAT contributors
// License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

import AnkiFFI
import Foundation

/// One card as ordered by the shared Rust schema-weighted queue.
public struct ScoredCard: Equatable {
    public let cardId: Int64
    public let noteId: Int64
    public let schema: String
    public let priority: Double
}

/// The readable problem behind a card, pulled from the note's fields.
public struct CardContent: Equatable {
    public let stimulus: String
    public let question: String
    public let choices: String       // "(A) ...\n(B) ..." plain text
    public let correct: String       // the correct choice letter, e.g. "A"
    public let runnerUp: String      // the trap runner-up letter
    public let whyRunnerUpWrong: String
}

/// A queued card plus its readable content, ready to render in a review UI.
public struct ReviewCard: Equatable {
    public let cardId: Int64
    public let schema: String
    public let priority: Double
    public let content: CardContent?
}

/// One of the three honest scores, mirroring the Rust ScoreValue.
public struct ScoreValue: Equatable {
    public let gaveUp: Bool
    public let point: Double
    public let low: Double
    public let high: Double
    public let n: Int
    public let reason: String
}

/// The three scores as returned by the shared ComputeSpeedrunScores RPC.
public struct ThreeScores: Equatable {
    public let memory: ScoreValue
    public let performance: ScoreValue
    public let readiness: ScoreValue
}

/// High-level review engine for the phone, built on `AnkiBackend`.
///
/// It opens the bundled Speedrun exam deck and orders it with the *same*
/// schema-weighted queue the desktop uses (scheduler service `13`, method `39`),
/// proving the engine is shared rather than reimplemented. Opening a collection
/// mutates it (WAL), so the bundled read-only deck is first copied into a
/// writable working directory.
public final class SpeedrunEngine {
    // Backend dispatch indices (mirror pylib/anki/_backend_generated.py and
    // rslib-ffi's constants).
    private static let svcCollection: UInt32 = 3
    private static let mOpenCollection: UInt32 = 0
    private static let svcScheduler: UInt32 = 13
    private static let mBuildSchemaWeightedQueue: UInt32 = 39
    private static let mComputeSpeedrunScores: UInt32 = 40
    private static let svcNotes: UInt32 = 25
    private static let mGetNote: UInt32 = 6

    // Note field order for the Speedrun seed notetype (see import_seed_deck.py FIELDS).
    private static let fStimulus = 5
    private static let fQuestion = 6
    private static let fChoices = 7
    private static let fCorrect = 8
    private static let fRunnerUp = 9
    private static let fWhyRunnerUpWrong = 10

    private let backend: AnkiBackend
    private let ephemeral: Bool
    public let workDir: URL
    public let collectionPath: URL

    public enum EngineError: Error {
        case backendOpenFailed
        case deckResourceMissing
        case commandFailed(String)
    }

    /// Designated init. Opens the collection at `collectionURL`, copying `copyFrom`
    /// into place first if it does not exist. When `ephemeral`, the working
    /// directory is deleted on deinit (tests); otherwise it persists (the app, so
    /// reviews survive and can sync).
    public init(collectionURL: URL, copyFrom: URL?, ephemeral: Bool) throws {
        var initWriter = Proto.Writer()
        initWriter.string(1, "en") // BackendInit.preferred_langs
        guard let backend = AnkiBackend(initBytes: initWriter.data) else {
            throw EngineError.backendOpenFailed
        }
        self.backend = backend
        self.ephemeral = ephemeral

        let dir = collectionURL.deletingLastPathComponent()
        try FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
        if !FileManager.default.fileExists(atPath: collectionURL.path), let copyFrom {
            try FileManager.default.copyItem(at: copyFrom, to: collectionURL)
        }
        workDir = dir
        collectionPath = collectionURL

        let mediaDir = dir.appendingPathComponent("media", isDirectory: true)
        try FileManager.default.createDirectory(at: mediaDir, withIntermediateDirectories: true)

        var open = Proto.Writer()
        open.string(1, collectionURL.path)      // OpenCollectionRequest.collection_path
        open.string(2, mediaDir.path)           // media_folder_path
        open.string(3, dir.appendingPathComponent("media.db").path) // media_db_path
        let res = backend.runCommand(
            service: Self.svcCollection, method: Self.mOpenCollection, input: open.data
        )
        if res.isError {
            throw EngineError.commandFailed("open_collection")
        }
    }

    /// Ephemeral engine over a copy of `collectionSource` (used by tests).
    public convenience init(collectionSource: URL) throws {
        let work = FileManager.default.temporaryDirectory
            .appendingPathComponent("speedrun-\(UUID().uuidString)", isDirectory: true)
        try self.init(
            collectionURL: work.appendingPathComponent("collection.anki2"),
            copyFrom: collectionSource,
            ephemeral: true,
        )
    }

    /// Convenience: ephemeral engine over the bundled exam deck (tests/scores demo).
    public convenience init() throws {
        try self.init(collectionSource: Self.bundledDeckURL())
    }

    /// The app's persistent engine: a writable collection in Documents, seeded
    /// once from the bundled deck. Survives launches and is what sync operates on.
    public convenience init(persistent: Bool) throws {
        let docs = FileManager.default.urls(for: .documentDirectory, in: .userDomainMask)[0]
        let col = docs.appendingPathComponent("speedrun/collection.anki2")
        try self.init(collectionURL: col, copyFrom: Self.bundledDeckURL(), ephemeral: !persistent)
    }

    private static func bundledDeckURL() throws -> URL {
        guard let url = Bundle.module.url(forResource: "collection", withExtension: "anki2") else {
            throw EngineError.deckResourceMissing
        }
        return url
    }

    /// Build the schema-weighted review queue on the shared engine.
    public func schemaWeightedQueue(limit: UInt32 = 100) -> [ScoredCard] {
        var req = Proto.Writer()
        req.string(1, "deck:\"LSAT Speedrun\"")  // search
        req.uint32(2, limit)                       // limit
        req.string(3, "sr:schema:")               // schema_tag_prefix
        req.double(7, 1.0)                          // time_pressure_factor
        req.double(8, 1.0)                          // default_weight
        req.double(9, 1.0)                          // default_weakness

        let res = backend.runCommand(
            service: Self.svcScheduler,
            method: Self.mBuildSchemaWeightedQueue,
            input: req.data
        )
        if res.isError { return [] }
        return Self.decodeScoredCards(res.data)
    }

    /// The readable problem behind a card, via the notes service `get_note`.
    public func noteContent(noteId: Int64) -> CardContent? {
        var req = Proto.Writer()
        req.int64(1, noteId) // NoteId.nid
        let res = backend.runCommand(service: Self.svcNotes, method: Self.mGetNote, input: req.data)
        if res.isError { return nil }
        let fields = Self.decodeNoteFields(res.data)
        guard !fields.isEmpty else { return nil }
        func at(_ i: Int) -> String { i < fields.count ? fields[i] : "" }
        return CardContent(
            stimulus: at(Self.fStimulus),
            question: at(Self.fQuestion),
            choices: at(Self.fChoices),
            correct: at(Self.fCorrect),
            runnerUp: at(Self.fRunnerUp),
            whyRunnerUpWrong: at(Self.fWhyRunnerUpWrong)
        )
    }

    /// The schema-weighted queue with each card's readable content attached.
    /// Fetched while the backend is open so the whole review session is ready.
    public func reviewQueue(limit: UInt32 = 100) -> [ReviewCard] {
        schemaWeightedQueue(limit: limit).map { sc in
            ReviewCard(
                cardId: sc.cardId,
                schema: sc.schema,
                priority: sc.priority,
                content: noteContent(noteId: sc.noteId)
            )
        }
    }

    /// Compute the three honest scores via the shared Rust RPC (service 13,
    /// method 40). Thresholds/weights default in Rust when omitted (0).
    public func computeScores(schemaWeight: [String: Double] = [:]) -> ThreeScores? {
        var req = Proto.Writer()
        req.string(1, "sr:schema:")               // schema_tag_prefix
        req.mapStringDouble(2, schemaWeight)       // schema_weight
        let res = backend.runCommand(
            service: Self.svcScheduler,
            method: Self.mComputeSpeedrunScores,
            input: req.data
        )
        if res.isError { return nil }
        return Self.decodeThreeScores(res.data)
    }

    deinit {
        if ephemeral {
            try? FileManager.default.removeItem(at: workDir)
        }
    }

    // MARK: - decoding

    /// Decode `SchemaWeightedQueueResponse { repeated ScoredCard cards = 1; }`.
    static func decodeScoredCards(_ data: Data) -> [ScoredCard] {
        var reader = Proto.Reader(data)
        var cards: [ScoredCard] = []
        while !reader.atEnd {
            let key = reader.varint()
            let field = Int(key >> 3)
            let wire = Int(key & 0x7)
            if field == 1, wire == 2 {
                cards.append(decodeScoredCard(reader.lengthDelimited()))
            } else {
                reader.skip(wire: wire)
            }
        }
        return cards
    }

    /// Decode one `ScoredCard { card_id=1, note_id=2, schema=3, schema_weight=4,
    /// weakness=5, priority=6 }`.
    private static func decodeScoredCard(_ slice: ArraySlice<UInt8>) -> ScoredCard {
        var reader = Proto.Reader(slice)
        var cardId: Int64 = 0
        var noteId: Int64 = 0
        var schema = ""
        var priority = 0.0
        while !reader.atEnd {
            let key = reader.varint()
            let field = Int(key >> 3)
            let wire = Int(key & 0x7)
            switch (field, wire) {
            case (1, 0): cardId = Int64(bitPattern: reader.varint())
            case (2, 0): noteId = Int64(bitPattern: reader.varint())
            case (3, 2):
                let bytes = reader.lengthDelimited()
                schema = String(bytes: bytes, encoding: .utf8) ?? ""
            case (6, 1): priority = reader.double()
            default: reader.skip(wire: wire)
            }
        }
        return ScoredCard(cardId: cardId, noteId: noteId, schema: schema, priority: priority)
    }

    /// Decode `SpeedrunScoresResponse { memory=1, performance=2, readiness=3 }`.
    static func decodeThreeScores(_ data: Data) -> ThreeScores? {
        var reader = Proto.Reader(data)
        var mem: ScoreValue?
        var perf: ScoreValue?
        var ready: ScoreValue?
        while !reader.atEnd {
            let key = reader.varint()
            let field = Int(key >> 3)
            let wire = Int(key & 0x7)
            if wire == 2, (1...3).contains(field) {
                let sv = decodeScoreValue(reader.lengthDelimited())
                switch field {
                case 1: mem = sv
                case 2: perf = sv
                default: ready = sv
                }
            } else {
                reader.skip(wire: wire)
            }
        }
        guard let mem, let perf, let ready else { return nil }
        return ThreeScores(memory: mem, performance: perf, readiness: ready)
    }

    /// Decode `ScoreValue { gave_up=1, point=2, low=3, high=4, n=5, reason=6 }`.
    private static func decodeScoreValue(_ slice: ArraySlice<UInt8>) -> ScoreValue {
        var reader = Proto.Reader(slice)
        var gaveUp = false
        var point = 0.0, low = 0.0, high = 0.0
        var n = 0
        var reason = ""
        while !reader.atEnd {
            let key = reader.varint()
            let field = Int(key >> 3)
            let wire = Int(key & 0x7)
            switch (field, wire) {
            case (1, 0): gaveUp = reader.varint() != 0
            case (2, 1): point = reader.double()
            case (3, 1): low = reader.double()
            case (4, 1): high = reader.double()
            case (5, 0): n = Int(Int64(bitPattern: reader.varint()))
            case (6, 2):
                let bytes = reader.lengthDelimited()
                reason = String(bytes: bytes, encoding: .utf8) ?? ""
            default: reader.skip(wire: wire)
            }
        }
        return ScoreValue(gaveUp: gaveUp, point: point, low: low, high: high, n: n, reason: reason)
    }

    /// Decode `Note { repeated string fields = 7 }` into the fields array (in order).
    static func decodeNoteFields(_ data: Data) -> [String] {
        var reader = Proto.Reader(data)
        var fields: [String] = []
        while !reader.atEnd {
            let key = reader.varint()
            let field = Int(key >> 3)
            let wire = Int(key & 0x7)
            if field == 7, wire == 2 {
                let bytes = reader.lengthDelimited()
                fields.append(String(bytes: bytes, encoding: .utf8) ?? "")
            } else {
                reader.skip(wire: wire)
            }
        }
        return fields
    }
}
