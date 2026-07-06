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

/// A grade for a card, matching `anki.scheduler.CardAnswer.Rating` on the wire
/// (0-based: AGAIN=0, HARD=1, GOOD=2, EASY=3). The shared Rust engine converts
/// these to Anki's 1-based revlog `ease` (Again=1, Hard=2, Good=3, Easy=4), so
/// callers use the proto values here and never do scheduling math in Swift.
public enum Rating: UInt32 {
    case again = 0
    case hard = 1
    case good = 2
    case easy = 3
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
    private static let mAnswerCard: UInt32 = 4
    private static let mGetSchedulingStates: UInt32 = 23
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

    // MARK: - Grading (record a real review on the shared scheduler)

    /// The five scheduling states for a card as opaque protobuf blobs: the
    /// current state plus the state the card would move to for each rating. Held
    /// as raw bytes so they can be handed straight back to `answerCard` without
    /// any Swift-side state math — the shared Rust engine owns all scheduling.
    struct SchedulingStatesRaw: Equatable {
        let current: [UInt8]
        let again: [UInt8]
        let hard: [UInt8]
        let good: [UInt8]
        let easy: [UInt8]
    }

    /// Fetch a card's scheduling states from the shared scheduler via
    /// `SchedulerService.GetSchedulingStates` (service 13, method 23). Mirrors the
    /// desktop reviewer, which asks the engine for the next states before grading.
    func schedulingStates(cardId: Int64) -> SchedulingStatesRaw? {
        var req = Proto.Writer()
        req.int64(1, cardId) // cards.CardId.cid
        let res = backend.runCommand(
            service: Self.svcScheduler, method: Self.mGetSchedulingStates, input: req.data
        )
        if res.isError { return nil }
        return Self.decodeSchedulingStates(res.data)
    }

    /// Record a real review for a card through the shared scheduler via
    /// `SchedulerService.AnswerCard` (service 13, method 4). This writes a revlog
    /// entry and advances the card's scheduling state exactly as the desktop
    /// does, so the three scores (derived from the revlog + FSRS memory state)
    /// update and there is real data to sync.
    ///
    /// It first reads the card's current + per-rating states, then sends a
    /// `CardAnswer { card_id, current_state, new_state, rating, answered_at_millis,
    /// milliseconds_taken }`. `answeredAtMillis` defaults to now; `millisecondsTaken`
    /// is the measured time the card was shown (Anki records it as the answer
    /// latency). Returns whether the engine accepted the review.
    @discardableResult
    public func answerCard(
        cardId: Int64,
        rating: Rating,
        millisecondsTaken: UInt32,
        answeredAtMillis: Int64 = Int64(Date().timeIntervalSince1970 * 1000)
    ) -> Bool {
        guard let states = schedulingStates(cardId: cardId) else { return false }
        let newState: [UInt8]
        switch rating {
        case .again: newState = states.again
        case .hard: newState = states.hard
        case .good: newState = states.good
        case .easy: newState = states.easy
        }

        var req = Proto.Writer()
        req.int64(1, cardId)                  // CardAnswer.card_id
        req.message(2, Data(states.current))  // current_state (opaque passthrough)
        req.message(3, Data(newState))        // new_state (opaque passthrough)
        req.uint32(4, rating.rawValue)        // rating (AGAIN=0 is omitted by proto3)
        req.int64(5, answeredAtMillis)        // answered_at_millis
        req.uint32(6, millisecondsTaken)      // milliseconds_taken
        let res = backend.runCommand(
            service: Self.svcScheduler, method: Self.mAnswerCard, input: req.data
        )
        return !res.isError
    }

    // Sync (BackendSyncService = service 1). Same RPCs the desktop uses.
    private static let svcSync: UInt32 = 1
    private static let mSyncLogin: UInt32 = 3
    private static let mSyncCollection: UInt32 = 5
    private static let mFullUpload: UInt32 = 6

    /// Log in and return the reusable `SyncAuth { hkey, endpoint }` blob, or nil
    /// on bad credentials. Shared by the normal sync and the explicit-direction
    /// full-sync helpers below.
    private func authenticate(url: String, username: String, password: String) -> Data? {
        var login = Proto.Writer()
        login.string(1, username)  // SyncLoginRequest.username
        login.string(2, password)  // password
        login.string(3, url)       // endpoint
        let lr = backend.runCommand(service: Self.svcSync, method: Self.mSyncLogin, input: login.data)
        if lr.isError { return nil }
        let (hkey, endpoint) = Self.decodeAuth(lr.data)
        if hkey.isEmpty { return nil }
        var auth = Proto.Writer()
        auth.string(1, hkey)
        auth.string(2, endpoint.isEmpty ? url : endpoint)
        return auth.data
    }

    /// Two-way sync against a self-hosted server. Logs in, runs a collection
    /// sync, and performs a full up/down when the server requires it. Returns a
    /// short human-readable status. Reviews done offline upload on the next call.
    ///
    /// Note the `required == 2` (FULL_SYNC, direction ambiguous) case: it means
    /// the phone and server collections diverged and the protocol can't pick a
    /// winner automatically. We default to upload here to preserve phone reviews,
    /// but to seed the phone from a desktop that is the source of truth, use
    /// `downloadFromServer(...)` instead (the desktop shows an Upload/Download
    /// prompt in exactly this case).
    public func sync(url: String, username: String, password: String) -> String {
        guard let authData = authenticate(url: url, username: username, password: password) else {
            return "Login failed: bad credentials"
        }

        var colReq = Proto.Writer()
        colReq.message(1, authData)  // SyncCollectionRequest.auth
        // sync_media (field 2) omitted = false
        let cr = backend.runCommand(
            service: Self.svcSync, method: Self.mSyncCollection, input: colReq.data
        )
        if cr.isError { return "Sync failed" }

        // SyncCollectionResponse.required (field 3): 0 none,1 normal,2 full,3 down,4 up
        switch Self.decodeRequired(cr.data) {
        case 0: return "Up to date"
        case 1: return "Synced"
        case 2, 4: return fullSync(auth: authData, upload: true)
        case 3: return fullSync(auth: authData, upload: false)
        default: return "Synced"
        }
    }

    /// Force a full **download**: replace this phone's collection with the
    /// server's. Use once to seed the phone from a desktop that has already
    /// uploaded (server = source of truth). Discards local unsynced phone
    /// reviews by design — mirrors choosing "Download" in the desktop's full-sync
    /// prompt.
    public func downloadFromServer(url: String, username: String, password: String) -> String {
        guard let authData = authenticate(url: url, username: username, password: password) else {
            return "Login failed: bad credentials"
        }
        return fullSync(auth: authData, upload: false)
    }

    /// Force a full **upload**: replace the server's collection with this phone's.
    public func uploadToServer(url: String, username: String, password: String) -> String {
        guard let authData = authenticate(url: url, username: username, password: password) else {
            return "Login failed: bad credentials"
        }
        return fullSync(auth: authData, upload: true)
    }

    private func fullSync(auth: Data, upload: Bool) -> String {
        var req = Proto.Writer()
        req.message(1, auth)   // FullUploadOrDownloadRequest.auth
        req.bool(2, upload)    // upload
        let r = backend.runCommand(service: Self.svcSync, method: Self.mFullUpload, input: req.data)
        if r.isError { return upload ? "Full upload failed" : "Full download failed" }
        return upload ? "Uploaded (full)" : "Downloaded (full)"
    }

    /// Decode SyncAuth { hkey=1, endpoint=2 }.
    private static func decodeAuth(_ data: Data) -> (String, String) {
        var reader = Proto.Reader(data)
        var hkey = "", endpoint = ""
        while !reader.atEnd {
            let key = reader.varint()
            let (field, wire) = (Int(key >> 3), Int(key & 0x7))
            if field == 1, wire == 2 {
                hkey = String(bytes: reader.lengthDelimited(), encoding: .utf8) ?? ""
            } else if field == 2, wire == 2 {
                endpoint = String(bytes: reader.lengthDelimited(), encoding: .utf8) ?? ""
            } else {
                reader.skip(wire: wire)
            }
        }
        return (hkey, endpoint)
    }

    /// Decode SyncCollectionResponse.required (field 3, varint).
    private static func decodeRequired(_ data: Data) -> Int {
        var reader = Proto.Reader(data)
        var required = 1
        while !reader.atEnd {
            let key = reader.varint()
            let (field, wire) = (Int(key >> 3), Int(key & 0x7))
            if field == 3, wire == 0 {
                required = Int(reader.varint())
            } else {
                reader.skip(wire: wire)
            }
        }
        return required
    }

    deinit {
        if ephemeral {
            try? FileManager.default.removeItem(at: workDir)
        }
    }

    // MARK: - decoding

    /// Decode `SchedulingStates { current=1, again=2, hard=3, good=4, easy=5 }`,
    /// keeping each `SchedulingState` as its raw length-delimited bytes so it can
    /// be re-embedded verbatim into a `CardAnswer` (the states are opaque to us).
    static func decodeSchedulingStates(_ data: Data) -> SchedulingStatesRaw? {
        var reader = Proto.Reader(data)
        var current: [UInt8]?, again: [UInt8]?, hard: [UInt8]?, good: [UInt8]?, easy: [UInt8]?
        while !reader.atEnd {
            let key = reader.varint()
            let field = Int(key >> 3)
            let wire = Int(key & 0x7)
            if wire == 2 {
                let bytes = Array(reader.lengthDelimited())
                switch field {
                case 1: current = bytes
                case 2: again = bytes
                case 3: hard = bytes
                case 4: good = bytes
                case 5: easy = bytes
                default: break
                }
            } else {
                reader.skip(wire: wire)
            }
        }
        guard let current, let again, let hard, let good, let easy else { return nil }
        return SchedulingStatesRaw(current: current, again: again, hard: hard, good: good, easy: easy)
    }

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
