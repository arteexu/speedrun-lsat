// Copyright: Speedrun LSAT contributors
// License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

//! C/FFI bridge that runs Anki's Rust backend on iOS.
//!
//! It deliberately mirrors `pylib/rsbridge` (the Python bridge): open a backend
//! from a serialized `BackendInit`, then dispatch every call through a single
//! command entrypoint that takes `(service, method, protobuf_bytes)` and
//! returns `protobuf_bytes`. Because both the desktop (via rsbridge) and iOS
//! (via this crate) speak the same protobuf surface to the *same*
//! `anki::backend::Backend`, the engine — including the schema-weighted queue —
//! is genuinely shared rather than reimplemented.
//!
//! Memory ownership contract for callers (Swift):
//! - `anki_backend_open` returns an opaque handle; free it with
//!   `anki_backend_free` exactly once.
//! - `anki_backend_run_command` returns an `AnkiBytes` buffer owned by Rust;
//!   free it with `anki_bytes_free` exactly once. `is_error` distinguishes a
//!   normal response from a protobuf-encoded `BackendError`.

use std::ptr;

use anki::backend::init_backend;
use anki::backend::Backend;

/// A byte buffer handed back to the caller. `is_error` is true when the bytes
/// are a protobuf-encoded `anki.backend.BackendError` rather than a normal
/// response.
#[repr(C)]
pub struct AnkiBytes {
    pub ptr: *mut u8,
    pub len: usize,
    pub is_error: bool,
}

fn into_anki_bytes(bytes: Vec<u8>, is_error: bool) -> AnkiBytes {
    let boxed = bytes.into_boxed_slice();
    let len = boxed.len();
    let ptr = Box::into_raw(boxed) as *mut u8;
    AnkiBytes { ptr, len, is_error }
}

/// Open a backend from a serialized `anki.backend.BackendInit` message.
/// Returns null on failure. Free the result with `anki_backend_free`.
///
/// # Safety
/// `init_ptr` must point to `init_len` readable bytes (or be null with len 0).
#[no_mangle]
pub unsafe extern "C" fn anki_backend_open(init_ptr: *const u8, init_len: usize) -> *mut Backend {
    let init: &[u8] = if init_ptr.is_null() {
        &[]
    } else {
        std::slice::from_raw_parts(init_ptr, init_len)
    };
    match init_backend(init) {
        Ok(backend) => Box::into_raw(Box::new(backend)),
        Err(_) => ptr::null_mut(),
    }
}

/// Run one protobuf command against the backend. Mirrors `rsbridge`'s
/// `command`.
///
/// # Safety
/// `backend` must be a valid pointer from `anki_backend_open`; `input_ptr` must
/// point to `input_len` readable bytes (or be null with len 0). The returned
/// buffer must be freed with `anki_bytes_free`.
#[no_mangle]
pub unsafe extern "C" fn anki_backend_run_command(
    backend: *mut Backend,
    service: u32,
    method: u32,
    input_ptr: *const u8,
    input_len: usize,
) -> AnkiBytes {
    if backend.is_null() {
        return into_anki_bytes(b"null backend handle".to_vec(), true);
    }
    let backend = &*backend;
    let input: &[u8] = if input_ptr.is_null() {
        &[]
    } else {
        std::slice::from_raw_parts(input_ptr, input_len)
    };
    match backend.run_service_method(service, method, input) {
        Ok(out) => into_anki_bytes(out, false),
        Err(err) => into_anki_bytes(err, true),
    }
}

/// Free a buffer returned by `anki_backend_run_command` / `anki_buildhash`.
///
/// # Safety
/// Must be called at most once per returned `AnkiBytes`.
#[no_mangle]
pub unsafe extern "C" fn anki_bytes_free(bytes: AnkiBytes) {
    if !bytes.ptr.is_null() {
        let slice = std::slice::from_raw_parts_mut(bytes.ptr, bytes.len);
        drop(Box::from_raw(slice as *mut [u8]));
    }
}

/// Free a backend handle returned by `anki_backend_open`.
///
/// # Safety
/// Must be called at most once per handle.
#[no_mangle]
pub unsafe extern "C" fn anki_backend_free(backend: *mut Backend) {
    if !backend.is_null() {
        drop(Box::from_raw(backend));
    }
}

/// Return the Anki build hash as bytes (handy for a Swift-side smoke test).
/// Free with `anki_bytes_free`.
#[no_mangle]
pub extern "C" fn anki_buildhash() -> AnkiBytes {
    into_anki_bytes(anki::version::buildhash().as_bytes().to_vec(), false)
}

#[cfg(test)]
mod test {
    use std::time::SystemTime;
    use std::time::UNIX_EPOCH;

    use prost::Message;

    use super::*;

    // Service/method indices as generated for the backend dispatch (mirrors the
    // values baked into pylib/anki/_backend_generated.py). Kept in one place so a
    // future proto change that shifts them is easy to update.
    const SVC_COLLECTION: u32 = 3;
    const M_OPEN_COLLECTION: u32 = 0;
    const SVC_SCHEDULER: u32 = 13;
    const M_BUILD_SCHEMA_WEIGHTED_QUEUE: u32 = 39;

    fn tmp_path(ext: &str) -> String {
        let nanos = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .unwrap()
            .as_nanos();
        let mut p = std::env::temp_dir();
        p.push(format!("anki_ffi_{}_{}.{}", std::process::id(), nanos, ext));
        p.to_string_lossy().into_owned()
    }

    #[test]
    fn open_collection_and_run_queue_over_ffi() {
        // 1. Open a backend from a BackendInit message, just like rsbridge.
        let init = anki_proto::backend::BackendInit {
            preferred_langs: vec!["en".into()],
            server: false,
            ..Default::default()
        };
        let init_bytes = init.encode_to_vec();
        let backend = unsafe { anki_backend_open(init_bytes.as_ptr(), init_bytes.len()) };
        assert!(!backend.is_null(), "backend should open");

        // 2. Open a fresh collection through the FFI command entrypoint.
        let col_path = tmp_path("anki2");
        let media_dir = tmp_path("media");
        std::fs::create_dir_all(&media_dir).unwrap();
        let media_db = tmp_path("mdb");
        let open_req = anki_proto::collection::OpenCollectionRequest {
            collection_path: col_path.clone(),
            media_folder_path: media_dir,
            media_db_path: media_db,
        };
        let ob = open_req.encode_to_vec();
        let res = unsafe {
            anki_backend_run_command(
                backend,
                SVC_COLLECTION,
                M_OPEN_COLLECTION,
                ob.as_ptr(),
                ob.len(),
            )
        };
        assert!(!res.is_error, "open_collection should succeed over FFI");
        unsafe { anki_bytes_free(res) };

        // 3. Call our schema-weighted queue RPC across the FFI and decode it.
        let q = anki_proto::scheduler::SchemaWeightedQueueRequest {
            search: "deck:Default".into(),
            ..Default::default()
        };
        let qb = q.encode_to_vec();
        let res = unsafe {
            anki_backend_run_command(
                backend,
                SVC_SCHEDULER,
                M_BUILD_SCHEMA_WEIGHTED_QUEUE,
                qb.as_ptr(),
                qb.len(),
            )
        };
        assert!(!res.is_error, "schema-weighted queue should run over FFI");
        let out = unsafe { std::slice::from_raw_parts(res.ptr, res.len) };
        let resp = anki_proto::scheduler::SchemaWeightedQueueResponse::decode(out).unwrap();
        assert_eq!(resp.cards.len(), 0, "empty collection yields no cards");
        unsafe { anki_bytes_free(res) };

        // 4. An invalid service index returns an error buffer, not a crash.
        let bad = unsafe { anki_backend_run_command(backend, 9999, 0, ptr::null(), 0) };
        assert!(bad.is_error);
        unsafe { anki_bytes_free(bad) };

        unsafe { anki_backend_free(backend) };
        let _ = std::fs::remove_file(&col_path);
    }

    #[test]
    fn buildhash_roundtrips() {
        let b = anki_buildhash();
        assert!(!b.is_error);
        assert!(b.len > 0);
        unsafe { anki_bytes_free(b) };
    }
}
