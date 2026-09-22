"""Structure-aware chunking for tool results.

Two ideas:
  1. Unwrap envelopes first. MCP results are `{"result": "<escaped payload>"}`;
     Read output is line-number prefixed. Chunk the payload, map offsets back.
  2. Pick a separator instead of a fixed width. Walk a priority ladder of real
     boundaries, take the highest one that actually splits the text, and recurse
     into pieces that are still too big. Fixed width is the last resort only.

Invariant: ''.join(chunks) == payload, where `payload, kind = unwrap(text)`.
Chunks are slices of payload, never rewritten (see the `assert` in chunk()).

Separator ladder, highest priority first:
  1.  JSON element commas (depth-1, only when the text really parses as JSON)
  2.  grep file grouping (`path:line:` runs)
  3.  `---` / `===` / `***` / `___` horizontal rules
  4.  `### Result N of M` headings
  5.  `diff --git` file boundaries
  6.  `commit <sha>` boundaries
  7.  markdown H1/H2 headings
  8.  markdown H3-H6 headings
  9.  banner lines (`####...`, `////...`, `****...`)
  10. `@@ ... @@` diff hunks
  11. function/class/type definitions
  12. trailing-colon headings (`Label:`)
  13. timestamp-prefixed lines
  14. blank-line paragraph breaks
  15. fixed width (last resort, no real boundary found)

Selection rule: take the highest-priority separator that splits the text into
at least 2 pieces where no single piece exceeds 75% of the total length;
pieces still over `target * 2` recurse through the same ladder, up to 4 levels
deep.
"""
import re, json

# ---- separator ladder: (name, regex matched at a line start unless noted) ----
LADDER = [
    ("hr",        re.compile(r'^(?:-{3,}|={3,}|\*{3,}|_{3,})\s*$', re.M)),
    ("result_n",  re.compile(r'^#{1,6}\s*Result\s+\d+\s+of\s+\d+', re.M | re.I)),
    ("diff_file", re.compile(r'^diff --git ', re.M)),
    ("commit",    re.compile(r'^commit [0-9a-f]{7,40}$', re.M)),
    ("md_h12",    re.compile(r'^#{1,2} \S', re.M)),
    ("md_h36",    re.compile(r'^#{3,6} \S', re.M)),
    ("banner",    re.compile(r'^[#/*]{4,}.*$', re.M)),
    ("hunk",      re.compile(r'^@@ .* @@', re.M)),
    ("topdef",    re.compile(r'^(?:def |class |func |function |type |interface |'
                             r'export (?:default )?(?:function|class|const)|'
                             r'(?:public|private|protected)\s+\w)', re.M)),
    ("kv_head",   re.compile(r'^\w[\w .\-/]{0,60}:\s*$', re.M)),
    ("ts_line",   re.compile(r'^(?:\[?\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}|\d{2}:\d{2}:\d{2})', re.M)),
    ("blankrun",  re.compile(r'\n\s*\n', re.M)),
]

def _cuts(text, rx, at_match_start=True):
    """Offsets where a new piece begins."""
    out = []
    for m in rx.finditer(text):
        p = m.start() if at_match_start else m.end()
        if 0 < p < len(text):
            out.append(p)
    return out

def _json_elem_cuts(text):
    """Depth-1 comma offsets of the first multi-element array/object.
    Only for text that actually is JSON - depth counting on prose finds junk."""
    t = text.strip()
    if not (t.startswith('[') or t.startswith('{')):
        return []
    try:
        json.loads(t)
    except Exception:
        return []
    for opener in ('[', '{'):
        s = text.find(opener)
        while s != -1:
            depth = instr = esc = 0; cuts = []
            instr = False
            for i in range(s, len(text)):
                c = text[i]
                if esc: esc = False; continue
                if c == '\\' and instr: esc = True; continue
                if c == '"': instr = not instr; continue
                if instr: continue
                if c in '[{': depth += 1
                elif c in ']}':
                    depth -= 1
                    if depth == 0: break
                elif c == ',' and depth == 1: cuts.append(i + 1)
            if len(cuts) >= 2: return cuts
            s = text.find(opener, s + 1)
    return []

def _grep_cuts(text):
    lines = text.split('\n')
    rx = re.compile(r'^([^\s:]+):\d+:')
    ms = [rx.match(l) for l in lines]
    if sum(1 for m in ms if m) < len(lines) * 0.6 or len(lines) < 6: return []
    out, pos, key = [], 0, None
    for l, m in zip(lines, ms):
        k = m.group(1) if m else key
        if pos > 0 and k != key: out.append(pos)
        key = k; pos += len(l) + 1
    return out

def _mask_prefix(text):
    """Blank out `123\t` line-number prefixes, keeping every offset identical."""
    return READ_PREFIX.sub(lambda m: ' ' * len(m.group(0)), text)

def _best_cuts(text, target):
    """Highest-priority separator that actually splits this text into useful pieces."""
    probe = _mask_prefix(text)
    cands = [("json", _json_elem_cuts(text)), ("grep", _grep_cuts(probe))]
    cands += [(n, _cuts(probe, rx, at_match_start=(n != "blankrun"))) for n, rx in LADDER]
    n = len(text)
    for name, cuts in cands:
        if len(cuts) < 1: continue
        bounds = [0] + sorted(set(cuts)) + [n]
        pieces = [b - a for a, b in zip(bounds, bounds[1:])]
        # useful = splits into at least 2 pieces and no piece hogs most of the text
        if len(pieces) >= 2 and max(pieces) <= n * 0.75:
            return name, sorted(set(cuts))
    return None, []

def _split(text, base, target, depth=0):
    """Recursively cut `text` (starting at absolute offset `base`) into <=target pieces."""
    if len(text) <= target * 1.5 or depth > 4:
        return [base, base + len(text)]
    name, cuts = _best_cuts(text, target)
    if not cuts:                                   # last resort: fixed width
        k = max(1, round(len(text) / target)); step = len(text) // k
        return [base + step * i for i in range(k)] + [base + len(text)]
    # accept a cut whenever the running piece has reached target
    keep, last = [], 0
    for c in cuts:
        if c - last >= target: keep.append(c); last = c
    bounds = [0] + keep + [len(text)]
    out = []
    for a, b in zip(bounds, bounds[1:]):
        if b - a > target * 2:
            out += _split(text[a:b], base + a, target, depth + 1)[:-1]
        else:
            out.append(base + a)
    out.append(base + len(text))
    return sorted(set(out))

# ---------- envelope unwrapping ----------
READ_PREFIX = re.compile(r'^\s*\d+\t', re.M)

def unwrap(text):
    """(payload, kind). Payload is what we chunk; chunks are re-expressed on the payload."""
    t = text.strip()
    if t.startswith('{') and t.endswith('}'):
        try:
            obj = json.loads(t)
        except Exception:
            return text, 'raw'
        if isinstance(obj, dict) and len(obj) <= 4:
            strs = {k: v for k, v in obj.items() if isinstance(v, str)}
            if strs:
                k = max(strs, key=lambda k: len(strs[k]))
                v = strs[k]
                # dominant field, measured against the decoded fields (escapes inflate `t`)
                if len(v) > 200 and len(v) >= sum(map(len, strs.values())) * 0.5:
                    return v, f'mcp:{k}'
    if len(READ_PREFIX.findall(text)) > text.count('\n') * 0.7 and text.count('\n') > 5:
        return text, 'read'
    return text, 'raw'

MCP_PREFIX = 'mcp:'

def rewrap(text, kind, payload):
    """The inverse of unwrap(): put a (possibly rewritten) payload back inside
    the envelope `text` came in.

    chunk() returns slices of `payload`, and for an `mcp:<key>` envelope the
    payload is the *inner* string, not `text`. A caller that joins the chunks
    back together and ships that as the whole tool result silently throws away
    the outer JSON object, its other keys and all of its escaping - the model
    is then handed something that no longer parses as what it asked for, and
    the discarded envelope was never stored as a chunk, so nothing can bring
    it back. Every caller that rewrites a tool result must route the joined
    payload through here.

    'raw' and 'read' envelopes are identities: unwrap() returned `text` itself
    as the payload, so the rewritten payload is already the whole thing.

    Raises ValueError when the envelope cannot be rebuilt (text no longer
    parses, or `kind` does not describe it). Callers fail open on that - they
    must not fall back to shipping the bare payload.
    """
    if not isinstance(kind, str) or not kind.startswith(MCP_PREFIX):
        return payload
    key = kind[len(MCP_PREFIX):]
    try:
        obj = json.loads(text.strip())
    except Exception:
        raise ValueError('envelope no longer parses as JSON') from None
    if not isinstance(obj, dict) or not isinstance(obj.get(key), str):
        raise ValueError('envelope does not carry the unwrapped key')
    obj[key] = payload
    return json.dumps(obj, ensure_ascii=False)

def chunk(text, max_chunks=16, min_chars=300):
    payload, kind = unwrap(text)
    target = max(min_chars, len(payload) // max_chunks)
    bounds = _split(payload, 0, target)
    pieces = [payload[a:b] for a, b in zip(bounds, bounds[1:])]
    # merge runs of tiny pieces forward
    merged, buf = [], ''
    for p in pieces:
        buf += p
        if len(buf) >= min_chars: merged.append(buf); buf = ''
    if buf:
        if merged: merged[-1] += buf
        else: merged.append(buf)
    while len(merged) > max_chunks:
        merged = [''.join(merged[i:i+2]) for i in range(0, len(merged), 2)]
    assert ''.join(merged) == payload, 'content loss'
    # Drop whitespace-only pieces from the *visible* chunk list, but fold their
    # text into a neighbour rather than discarding it outright -- a fixed-width
    # fallback cut can land entirely inside a long run of whitespace (e.g. a
    # markdown table's column padding), producing a piece that strips to empty
    # while still holding real payload characters. Filtering those out with
    # `if c.strip()` alone silently breaks ''.join(chunks) == payload.
    final = []
    for c in merged:
        if not c.strip() and final:
            final[-1] += c
        else:
            final.append(c)
    while len(final) > 1 and not final[0].strip():
        final[1] = final[0] + final[1]
        final.pop(0)
    assert ''.join(final) == payload, 'content loss'
    return final, kind
