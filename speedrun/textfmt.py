# Copyright: Speedrun LSAT contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

"""Shared inline-Markdown → HTML formatting used across Speedrun surfaces.

The AI Tutor, the "what to study next" recommender, and the contrasting-pairs
drill all display short AI/model or deterministic-template text that may contain
lightweight Markdown -- ``**bold**`` and newlines. This module is the single,
safety-first place that converts it: HTML is escaped FIRST, then a tiny allowlist
(bold, line breaks) is applied, so model/user text can never inject live markup.

Qt-free and dependency-free so every surface (including ``speedrun.ai.*``) can
import it, and so the exact same rules apply server-side (:func:`format_inline_md`)
and client-side (the shared JS snippet :data:`INLINE_MD_JS`)."""

from __future__ import annotations

import html
import re

# ``.`` does NOT match newlines here (no DOTALL), so a bold span cannot cross a
# line break -- this keeps the Python converter byte-for-byte compatible with the
# JS regex in INLINE_MD_JS, which also lacks the /s flag.
_BOLD_RE = re.compile(r"\*\*(.+?)\*\*")


def format_inline_md(text: object) -> str:
    """Escape ``text`` as HTML, then render ``**bold**`` and newlines.

    Safety: escaping happens BEFORE the bold/newline substitutions, so any markup
    already in ``text`` is inert -- only the ``<strong>``/``<br>`` we add is live
    HTML. Returns an empty string for ``None``."""
    escaped = html.escape("" if text is None else str(text))
    bolded = _BOLD_RE.sub(r"<strong>\1</strong>", escaped)
    return bolded.replace("\n", "<br>")


# Client-side twin of ``format_inline_md``: defines global ``srEsc``/``srFmt`` so
# the JS surfaces (tutor chat, contrasting drill) share one bold/newline regex
# instead of duplicating it. Kept behavior-compatible with ``format_inline_md``.
INLINE_MD_JS = r"""
function srEsc(s){ const d=document.createElement('div'); d.textContent = s==null?'':s; return d.innerHTML; }
function srFmt(s){ return srEsc(s).replace(/\*\*(.+?)\*\*/g,'<strong>$1</strong>').replace(/\n/g,'<br>'); }
"""
