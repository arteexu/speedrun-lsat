// Copyright: Speedrun LSAT contributors
// License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html
//
// C interface for Anki's Rust backend (Speedrun LSAT iOS bridge).
// Mirrors pylib/rsbridge: open a backend, then dispatch every call through a
// single command entrypoint taking (service, method, protobuf bytes).

#ifndef ANKI_FFI_H
#define ANKI_FFI_H

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

// Opaque handle to an anki::backend::Backend.
typedef struct Backend Backend;

// A byte buffer owned by Rust. Free with anki_bytes_free exactly once.
// is_error == true means `ptr`/`len` hold a protobuf-encoded BackendError.
typedef struct {
  uint8_t *ptr;
  size_t len;
  bool is_error;
} AnkiBytes;

// Open a backend from a serialized anki.backend.BackendInit message.
// Returns NULL on failure. Free with anki_backend_free.
Backend *anki_backend_open(const uint8_t *init_ptr, size_t init_len);

// Run one protobuf command. `input_ptr` may be NULL when `input_len` is 0.
// The returned buffer must be freed with anki_bytes_free.
AnkiBytes anki_backend_run_command(Backend *backend, uint32_t service,
                                   uint32_t method, const uint8_t *input_ptr,
                                   size_t input_len);

// Free a buffer returned by anki_backend_run_command / anki_buildhash.
void anki_bytes_free(AnkiBytes bytes);

// Free a backend handle returned by anki_backend_open.
void anki_backend_free(Backend *backend);

// Return the Anki build hash as bytes (smoke test helper).
AnkiBytes anki_buildhash(void);

#ifdef __cplusplus
}
#endif

#endif  // ANKI_FFI_H
