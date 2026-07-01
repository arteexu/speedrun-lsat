// Copyright: Speedrun LSAT contributors
// License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

import AnkiFFI
import Foundation

/// Swift wrapper around Anki's Rust backend, running on-device via the C FFI.
///
/// This is the iOS counterpart to `pylib/anki/_backend.py`: open a backend, then
/// dispatch every call through `runCommand(service:method:input:)` using
/// protobuf-encoded bytes. Build the protobuf messages with SwiftProtobuf from
/// `proto/anki/*.proto` (the same definitions the desktop uses).
public final class AnkiBackend {
    private let handle: OpaquePointer

    /// Open a backend from an already-encoded `anki.backend.BackendInit` message.
    /// Use SwiftProtobuf to build `initBytes`.
    public init?(initBytes: Data) {
        let handle: OpaquePointer? = initBytes.withUnsafeBytes { raw in
            anki_backend_open(raw.bindMemory(to: UInt8.self).baseAddress, raw.count)
        }
        guard let handle else { return nil }
        self.handle = handle
    }

    deinit {
        anki_backend_free(handle)
    }

    /// Run one protobuf command. Returns the response bytes and whether the
    /// backend reported an error (in which case `data` is an encoded
    /// `anki.backend.BackendError`).
    public func runCommand(service: UInt32, method: UInt32, input: Data) -> (data: Data, isError: Bool) {
        let result: AnkiBytes = input.withUnsafeBytes { raw in
            anki_backend_run_command(
                handle,
                service,
                method,
                raw.bindMemory(to: UInt8.self).baseAddress,
                raw.count
            )
        }
        defer { anki_bytes_free(result) }
        let data = Data(bytes: result.ptr, count: result.len)
        return (data, result.is_error)
    }

    /// The Anki engine build hash. Needs no open collection, so it is a good
    /// smoke test that the shared Rust engine loaded and runs on the device.
    public static func buildHash() -> String {
        let bytes = anki_buildhash()
        defer { anki_bytes_free(bytes) }
        return String(data: Data(bytes: bytes.ptr, count: bytes.len), encoding: .utf8) ?? ""
    }
}
