# Copyright: Speedrun LSAT contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

"""AI safety helpers: prompt-injection sanitization + source enforcement.

- ``sanitize_source_text`` strips instruction-like lines from untrusted source
  material before it is placed in a prompt, so a poisoned source file cannot
  redirect the model (defense-in-depth; the prompt also frames source text as
  data only).
- ``has_named_source`` / ``require_source`` enforce the traceability rule: no AI
  output is shown unless it carries a real, named source.
"""
from __future__ import annotations

import re

from speedrun.ai.client import LLMResponse

# Lines that look like attempts to override instructions are dropped from source.
_INJECTION = re.compile(
    r"""(?ix)
    ^\s*(
        ignore\s+(all\s+)?previous |
        disregard\s+(all\s+)?(the\s+)?above |
        system\s*: |
        assistant\s*: |
        you\s+are\s+now |
        new\s+instructions? |
        override\s+ |
        forget\s+(everything|the\s+above)
    )
    """
)

MAX_SOURCE_CHARS = 20_000


def sanitize_source_text(text: str, *, max_chars: int = MAX_SOURCE_CHARS) -> str:
    """Remove instruction-like lines and cap length. Content lines are kept."""
    kept = [ln for ln in text.splitlines() if not _INJECTION.search(ln)]
    cleaned = "\n".join(kept).strip()
    return cleaned[:max_chars]


def has_named_source(resp: LLMResponse) -> bool:
    """True when the response is usable AND carries a real, named source.

    This is the single traceability predicate: it requires ``resp.ok`` (non-empty
    text, not a stub/error marker) AND an explicitly non-blank ``source``. The
    blank-source check is defense-in-depth so the rule reads correctly at the call
    site even if ``ok`` is ever loosened."""
    return resp.ok and bool(resp.source.strip())


def require_source(resp: LLMResponse) -> LLMResponse:
    """Return the response if it has a named source, else raise. Use where a
    missing source must be a hard error rather than a silent offline fallback."""
    if not has_named_source(resp):
        raise ValueError(
            f"AI output rejected: no usable named source (source={resp.source!r})"
        )
    return resp
