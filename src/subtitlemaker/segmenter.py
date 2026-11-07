"""Turn Whisper segments into formatted subtitle cues.

Pure logic: no printing, no file access, no model.
"""

import re


def clean_text(text):
    """Clean up Whisper text."""

    text = text.strip()

    # Collapse multiple whitespace characters
    text = re.sub(r"\s+", " ", text)

    # Remove spaces before punctuation
    text = re.sub(r"\s+([,.!?;:])", r"\1", text)

    # Clean brackets
    text = re.sub(r"([(\[])\s+", r"\1", text)
    text = re.sub(r"\s+([)\]])", r"\1", text)

    return text.strip()


def split_into_lines(text, style):
    """
    Split subtitle into a maximum of `style.max_lines` lines.

    Attempts to:
    - keep lines below `style.max_line_length`
    - balance line lengths
    - prefer punctuation boundaries
    """

    words = text.split()

    if not words:
        return []

    # Fits on one line
    if len(text) <= style.max_line_length:
        return [text]

    # Find the best two-line split
    best_split = None
    best_score = float("inf")

    for i in range(1, len(words)):
        left = " ".join(words[:i])
        right = " ".join(words[i:])

        if len(left) > style.max_line_length:
            continue

        if len(right) > style.max_line_length:
            continue

        # Prefer balanced lines
        score = abs(len(left) - len(right))

        # Prefer punctuation at the end of line 1
        if left.endswith((".", ",", "!", "?", ";", ":")):
            score -= 15

        if score < best_score:
            best_score = score
            best_split = (left, right)

    if best_split:
        return list(best_split)

    # Fallback: split approximately in half.
    midpoint = len(words) // 2

    return [
        " ".join(words[:midpoint]),
        " ".join(words[midpoint:]),
    ]


# A cue is never shown for less than this, whatever the neighbours are doing.
_MIN_VISIBLE = 0.1


def _fits(text, style):
    """True if `text` can be laid out within the line and length limits."""

    if len(text) <= style.max_line_length:
        return True

    if style.max_lines < 2:
        return False

    words = text.split()

    return any(
        len(" ".join(words[:i])) <= style.max_line_length
        and len(" ".join(words[i:])) <= style.max_line_length
        for i in range(1, len(words))
    )


def _join(tokens):
    return clean_text("".join(token[0] for token in tokens))


def _best_break(tokens):
    """
    Where to end the cue when `tokens` plus one more word no longer fit.

    Prefers the end of a sentence, then a clause (comma, semicolon, colon)
    in the second half of the text. Returns the number of tokens to keep;
    `len(tokens)` means no good break was found.
    """

    sentence = clause = None
    total = len(_join(tokens))

    for i in range(1, len(tokens)):

        word = tokens[i - 1][0].strip()

        if word.endswith((".", "!", "?")):
            sentence = i

        elif word.endswith((",", ";", ":")) and len(_join(tokens[:i])) * 2 >= total:
            clause = i

    if sentence is not None:
        return sentence

    return clause if clause is not None else len(tokens)


def _chunk(tokens, style):
    """
    Split a segment's tokens into runs that each fit one cue.

    A token is `(text, start, end)` where the text carries its own leading
    space and the times may be None. A run only grows while it can still be
    laid out in valid lines, so every chunk (except a single over-long word)
    splits cleanly in `split_into_lines`.
    """

    chunks = []
    current = []

    for token in tokens:

        if not current or _fits(_join(current + [token]), style):
            current.append(token)
            continue

        cut = _best_break(current)

        # The leftover plus the new word must still fit; if not, break here.
        if not _fits(_join(current[cut:] + [token]), style):
            cut = len(current)

        chunks.append(current[:cut])
        current = current[cut:] + [token]

    if current:
        chunks.append(current)

    return chunks


def _segment_tokens(segment, text):
    """The words of a segment as tokens, without timing."""

    return [(" " + word, None, None) for word in text.split()]


def _segment_cues(segment, style):
    """Cues for one Whisper segment, with their speech timing and no padding."""

    text = clean_text(segment.text)

    if not text:
        return []

    start = float(segment.start)
    end = float(segment.end)

    chunks = _chunk(_segment_tokens(segment, text), style)

    # No word timing: share the segment's duration out by text length.
    total_chars = sum(len(_join(chunk)) for chunk in chunks)

    cues = []
    cursor = start

    for chunk in chunks:

        chunk_text = _join(chunk)
        chunk_end = cursor + (end - start) * len(chunk_text) / total_chars

        cues.append({"start": cursor, "end": chunk_end, "text": chunk_text})

        cursor = chunk_end

    return cues


def _apply_timing(cues, style):
    """
    Make cue timing readable without moving speech around.

    In order, for every cue:
      1. It starts when its speech starts, unless the previous cue is still
         up (only possible when source segments overlap).
      2. It is held at least `min_duration` and long enough to read at
         `max_cps`, but never longer than `max_duration`.
      3. It must end `min_gap` before the next cue's speech starts. This wins
         over rule 2: readability padding never delays or overlaps the next
         cue, so a very short gap can leave a cue under `min_duration`.
    """

    timed = []
    previous_end = None

    for i, cue in enumerate(cues):

        start = cue["start"]

        if previous_end is not None:
            start = max(start, previous_end + style.min_gap)

        plain = cue["text"].replace("\n", " ")

        wanted = max(
            cue["end"],
            start + style.min_duration,
            start + len(plain) / style.max_cps,
        )

        end = min(wanted, start + style.max_duration)

        if i + 1 < len(cues):
            end = min(end, cues[i + 1]["start"] - style.min_gap)

        end = max(end, start + _MIN_VISIBLE)

        timed.append({"start": start, "end": end, "text": cue["text"]})

        previous_end = end

    return timed


def build_subtitles(segments, style):
    """Convert Whisper segments into formatted subtitles."""

    cues = []

    for segment in segments:

        for cue in _segment_cues(segment, style):

            lines = split_into_lines(cue["text"], style)

            if not lines:
                continue

            cue["text"] = "\n".join(lines)
            cues.append(cue)

    return _apply_timing(cues, style)
