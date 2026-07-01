// Copyright: Speedrun LSAT contributors
// License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

import Foundation

/// A tiny, dependency-free protobuf writer/reader for the handful of flat
/// messages AnkiKit needs (open collection + schema-weighted queue). It speaks
/// the exact same wire format the desktop uses, so the request/response bytes are
/// interchangeable with `pylib`/`rslib`. For richer messages, swap in
/// SwiftProtobuf and generate from `proto/anki/*.proto`.
enum Proto {
    // MARK: Writer

    struct Writer {
        private(set) var data = Data()

        private mutating func varint(_ value: UInt64) {
            var v = value
            repeat {
                var byte = UInt8(v & 0x7F)
                v >>= 7
                if v != 0 { byte |= 0x80 }
                data.append(byte)
            } while v != 0
        }

        private mutating func tag(_ field: Int, _ wire: Int) {
            varint(UInt64(field << 3 | wire))
        }

        /// proto3 omits default (empty) strings.
        mutating func string(_ field: Int, _ value: String) {
            if value.isEmpty { return }
            let bytes = Data(value.utf8)
            tag(field, 2)
            varint(UInt64(bytes.count))
            data.append(bytes)
        }

        /// proto3 omits zero scalars.
        mutating func uint32(_ field: Int, _ value: UInt32) {
            if value == 0 { return }
            tag(field, 0)
            varint(UInt64(value))
        }

        mutating func double(_ field: Int, _ value: Double) {
            if value == 0 { return }
            tag(field, 1)
            var bits = value.bitPattern.littleEndian
            withUnsafeBytes(of: &bits) { data.append(contentsOf: $0) }
        }
    }

    // MARK: Reader

    struct Reader {
        private let bytes: [UInt8]
        private var index = 0

        init(_ data: Data) { bytes = [UInt8](data) }
        init(_ slice: ArraySlice<UInt8>) { bytes = Array(slice) }

        var atEnd: Bool { index >= bytes.count }

        mutating func varint() -> UInt64 {
            var result: UInt64 = 0
            var shift: UInt64 = 0
            while index < bytes.count {
                let byte = bytes[index]
                index += 1
                result |= UInt64(byte & 0x7F) << shift
                if byte & 0x80 == 0 { break }
                shift += 7
            }
            return result
        }

        mutating func double() -> Double {
            var bits: UInt64 = 0
            for k in 0..<8 where index + k < bytes.count {
                bits |= UInt64(bytes[index + k]) << (8 * k)
            }
            index += 8
            return Double(bitPattern: bits)
        }

        mutating func lengthDelimited() -> ArraySlice<UInt8> {
            let len = Int(varint())
            let end = min(index + len, bytes.count)
            let slice = bytes[index..<end]
            index = end
            return slice
        }

        /// Skip a field whose value we don't care about, by wire type.
        mutating func skip(wire: Int) {
            switch wire {
            case 0: _ = varint()
            case 1: index += 8
            case 2: _ = lengthDelimited()
            case 5: index += 4
            default: index = bytes.count
            }
        }
    }
}
