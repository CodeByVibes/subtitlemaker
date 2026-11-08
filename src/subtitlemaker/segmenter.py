"""Turn Whisper segments into formatted subtitle cues.

Pure logic: no printing, no file access, no model.
"""

import re
from collections.abc import Iterable, Sequence

from ._types import Cue, SegmentLike, Token
from .config import SubtitleStyle


def clean_text(text: str) -> str:
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


_SENTENCE_END = (".", "!", "?")
_CLAUSE_END = (",", ";", ":")
_DASHES = ("–", "—", "-")


def _speaker_changes(words: Sequence[str]) -> set[int]:
    """
    Indexes of words that start a new speaker's line: a dash glued to the
    word ("–Ja!") right after a sentence end. The sentence end keeps a minus
    sign ("it was -20 degrees") from counting.
    """

    return {
        i
        for i in range(1, len(words))
        if words[i].startswith(_DASHES)
        and len(words[i]) > 1
        and words[i - 1].endswith(_SENTENCE_END)
    }


# Words that belong with the word after them: ending line 1 on one splits an
# article from its noun, a preposition from its object or a conjunction from
# its clause ("the system or / you make"). Only articles, prepositions and
# conjunctions, never pronouns or verbs, and only for languages checked on
# real subtitles. Others get no penalty.
_BINDING_WORDS = {
    "en": frozenset(
        "a an the and or but nor of to in on at for with from by into onto "
        "about than if because whether".split()
    ),
    "sv": frozenset(
        "en ett och eller men att i på av till för med från om som än utan "
        "vid mot hos eftersom".split()
    ),
}

# Penalty, in characters of imbalance, for a bad last word on line 1.
_BINDING_PENALTY = 12


def _splits_a_name(last: str, first: str) -> bool:
    """True for two capitalised words in a row ("Andrea / Russell")."""

    return (
        last[:1].isupper()
        and first[:1].isupper()
        and last != "I"
        and not last.endswith(_SENTENCE_END + _CLAUSE_END)
    )


def split_into_lines(
    text: str, style: SubtitleStyle, language: str | None = None
) -> list[str]:
    """
    Split subtitle into a maximum of `style.max_lines` lines.

    Attempts to:
    - keep lines below `style.max_line_length`
    - give each speaker their own line when a dialogue dash starts a new
      speaker ("–Ja? –Vill du veta?"), even if the text fits on one line
    - balance line lengths
    - prefer a sentence end, then a clause boundary, at the end of line 1
    - not end line 1 on an article, preposition or conjunction (for a
      `language` with a word list) or in the middle of a name
    """

    binding = _BINDING_WORDS.get(language or "", frozenset())

    words = text.split()

    if not words:
        return []

    speakers = _speaker_changes(words) if style.max_lines >= 2 else set()

    # Fits on one line
    if len(text) <= style.max_line_length and not speakers:
        return [text]

    # Find the best two-line split
    best_split: tuple[str, str] | None = None
    best_score = float("inf")

    for i in range(1, len(words)):
        left = " ".join(words[:i])
        right = " ".join(words[i:])

        if len(left) > style.max_line_length:
            continue

        if len(right) > style.max_line_length:
            continue

        # Prefer balanced lines
        score = float(abs(len(left) - len(right)))

        # A new speaker goes on a new line, whatever the balance.
        if i in speakers:
            score -= 1000

        # Prefer a sentence end, then a clause boundary, at the end of line 1
        elif left.endswith(_SENTENCE_END):
            score -= 25

        elif left.endswith(_CLAUSE_END):
            score -= 15

        if words[i - 1].lower() in binding or _splits_a_name(words[i - 1], words[i]):
            score += _BINDING_PENALTY

        if score < best_score:
            best_score = score
            best_split = (left, right)

    if best_split:
        return list(best_split)

    # A single word longer than the line cannot be split at a space. Cut it
    # in half (or leave it whole with one line) rather than return an empty
    # line, which would end the cue early in SRT and invalidate a WebVTT file.
    if len(words) == 1:

        if style.max_lines < 2:
            return [text]

        half = (len(text) + 1) // 2

        return [text[:half], text[half:]]

    # Fallback: split approximately in half.
    midpoint = len(words) // 2

    return [
        " ".join(words[:midpoint]),
        " ".join(words[midpoint:]),
    ]


# A cue is never shown for less than this, whatever the neighbours are doing.
_MIN_VISIBLE = 0.1


def _fits(text: str, style: SubtitleStyle) -> bool:
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


def _join(tokens: Sequence[Token]) -> str:
    return clean_text("".join(token[0] for token in tokens))


def _best_break(tokens: Sequence[Token]) -> int:
    """
    Where to end the cue when `tokens` plus one more word no longer fit.

    Prefers the end of a sentence, then a clause (comma, semicolon, colon)
    in the second half of the text. Returns the number of tokens to keep;
    `len(tokens)` means no good break was found.
    """

    sentence: int | None = None
    clause: int | None = None
    total = len(_join(tokens))

    for i in range(1, len(tokens)):

        word = tokens[i - 1][0].strip()

        if word.endswith(_SENTENCE_END):
            sentence = i

        elif word.endswith(_CLAUSE_END) and len(_join(tokens[:i])) * 2 >= total:
            clause = i

    if sentence is not None:
        return sentence

    return clause if clause is not None else len(tokens)


def _speakers(tokens: Sequence[Token]) -> int:
    """How many speakers the joined tokens hold, counting dialogue dashes."""

    return len(_speaker_changes(_join(tokens).split())) + 1


def _speaker_start(tokens: Sequence[Token], speaker: int) -> int:
    """
    Index of the token where speaker number `speaker` (2 or 3) starts.

    The text is checked as joined, because Whisper may give the dash as a
    token of its own ("–" then "Det"): a bare dash just before is included.
    """

    cut = next(k for k in range(1, len(tokens) + 1) if _speakers(tokens[:k]) >= speaker) - 1

    while cut > 0 and tokens[cut - 1][0].strip() in _DASHES:
        cut -= 1

    return cut


def _speaker_cut(tokens: Sequence[Token], style: SubtitleStyle) -> int | None:
    """
    Where to end a run so that it holds at most two speakers, each on a line
    of their own. None if `tokens` can stay together.

    Two lines can show two speakers, a third cannot. Two speakers only share
    a cue if each one's words fit on one line; otherwise the line break would
    have to fall inside one speaker's sentence.
    """

    words = _join(tokens).split()
    changes = sorted(_speaker_changes(words))

    if not changes:
        return None

    if len(changes) > 1:
        return _speaker_start(tokens, 3)

    first = changes[0]

    if style.max_lines < 2 or (
        len(" ".join(words[:first])) <= style.max_line_length
        and len(" ".join(words[first:])) <= style.max_line_length
    ):
        return None

    return _speaker_start(tokens, 2)


def _speech_time(first: Token, next_token: Token) -> float:
    """Seconds from `first` starting to `next_token` starting; inf without timing."""

    if first[1] is None or next_token[1] is None:
        return float("inf")

    return next_token[1] - first[1]


def _pause(previous: Token, token: Token) -> float:
    """Seconds of silence between two tokens; 0 if either has no timing."""

    if previous[2] is None or token[1] is None:
        return 0.0

    return token[1] - previous[2]


def _chunk(tokens: Sequence[Token], style: SubtitleStyle) -> list[list[Token]]:
    """
    Split tokens (of one segment, or a stream of several) into runs that each fit one cue.

    A token is `(text, start, end)` where the text carries its own leading
    space and the times may be None. A run only grows while it can still be
    laid out in valid lines, so every chunk (except a single over-long word)
    splits cleanly in `split_into_lines`.

    A run also ends at a long silence: Whisper sometimes puts words that are
    many seconds apart into one segment, and one cue would then show the
    later words long before they are spoken.

    And a run holds at most two speakers (see `_speaker_cut`), each with a
    line of their own.
    """

    chunks: list[list[Token]] = []
    current: list[Token] = []

    for token in tokens:

        if current and _pause(current[-1], token) >= style.max_pause:
            chunks.append(current)
            current = [token]
            continue

        cut = _speaker_cut(current + [token], style) if current else None

        # Not if the cue before the cut would be too short to read: three
        # quick speakers in one cue beat a cue that flashes past.
        if cut and _speech_time(current[0], (current + [token])[cut]) < style.min_duration:
            cut = None

        if cut:
            chunks.append(current[:cut])
            current = current[cut:]

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


def _segment_tokens(segment: SegmentLike, text: str) -> list[Token]:
    """
    The words of a segment as `(text, start, end)` tokens.

    Uses Whisper's word timestamps when it provided them and they agree with
    the segment text. Otherwise the tokens carry no timing and the caller
    spreads the segment's duration over them.
    """

    words = getattr(segment, "words", None) or []

    tokens = [
        (word.word, word.start, word.end)
        for word in words
        if word.word.strip()
    ]

    usable = (
        tokens
        and all(start is not None and end is not None for _, start, end in tokens)
        and "".join(word for word, _, _ in tokens).split() == text.split()
    )

    if usable:
        return tokens

    return [(" " + word, None, None) for word in text.split()]


def _seconds(value: float | None) -> float:
    """A token time that is known to be present (checked by the caller)."""

    assert value is not None

    return float(value)


def _timed_cues(tokens: Sequence[Token], style: SubtitleStyle) -> list[Cue]:
    """Cues for a run of tokens that all have word timing."""

    return [
        {
            "start": _seconds(chunk[0][1]),
            "end": max(_seconds(chunk[-1][2]), _seconds(chunk[0][1])),
            "text": _join(chunk),
        }
        for chunk in _chunk(tokens, style)
    ]


def _untimed_cues(
    segment: SegmentLike, tokens: Sequence[Token], style: SubtitleStyle
) -> list[Cue]:
    """Cues for a segment without word timing: its duration shared out by text length."""

    chunks = _chunk(tokens, style)

    start = float(segment.start)
    end = float(segment.end)

    total_chars = sum(len(_join(chunk)) for chunk in chunks)

    cues: list[Cue] = []
    cursor = start

    for chunk in chunks:

        chunk_text = _join(chunk)
        chunk_end = cursor + (end - start) * len(chunk_text) / total_chars

        cues.append({"start": cursor, "end": chunk_end, "text": chunk_text})

        cursor = chunk_end

    return cues


def _speech_cues(segments: Iterable[SegmentLike], style: SubtitleStyle) -> list[Cue]:
    """
    Cues with their speech timing and no padding.

    The words of consecutive segments with word timing are chunked as one
    stream: Whisper's segment boundaries often fall mid-sentence (a segment
    can end one word before the sentence does), so they are not used as cue
    breaks. Pauses, line limits and punctuation decide where cues end. A
    segment without word timing is chunked on its own and ends the stream.
    """

    cues: list[Cue] = []
    stream: list[Token] = []

    for segment in segments:

        text = clean_text(segment.text)

        if not text:
            continue

        tokens = _segment_tokens(segment, text)

        if tokens[0][1] is None:
            cues.extend(_timed_cues(stream, style))
            stream = []

            cues.extend(_untimed_cues(segment, tokens, style))
            continue

        # Keep the last word of one segment and the first of the next apart.
        word, start, end = tokens[0]

        if stream and not word[:1].isspace():
            tokens[0] = (" " + word, start, end)

        stream.extend(tokens)

    cues.extend(_timed_cues(stream, style))

    return cues


def _apply_timing(cues: Sequence[Cue], style: SubtitleStyle) -> list[Cue]:
    """
    Make cue timing readable without moving speech around.

    In order, for every cue:
      1. It starts when its speech starts, unless the previous cue is still
         up (only possible when source segments overlap).
      2. It stays up `linger` after its speech ends, at least `min_duration`
         and long enough to read at `max_cps`, but never longer than
         `max_duration`.
      3. It must end `min_gap` before the next cue's speech starts. This wins
         over rule 2: padding never delays or overlaps the next cue, so a
         very short gap can leave a cue under `min_duration`.
      4. If that leaves a gap shorter than `close_gap` before the next cue,
         it stays up until `min_gap` before the next cue instead, so the
         text does not flicker off and on (still capped by `max_duration`).
    """

    timed: list[Cue] = []
    previous_end: float | None = None

    for i, cue in enumerate(cues):

        start = cue["start"]

        if previous_end is not None:
            start = max(start, previous_end + style.min_gap)

        plain = cue["text"].replace("\n", " ")

        wanted = max(
            cue["end"] + style.linger,
            start + style.min_duration,
            start + len(plain) / style.max_cps,
        )

        cap = start + style.max_duration
        end = min(wanted, cap)

        if i + 1 < len(cues):
            next_start = cues[i + 1]["start"]
            latest = next_start - style.min_gap

            end = min(end, latest)

            if next_start - end < style.close_gap:
                end = max(end, min(latest, cap))

        end = max(end, start + _MIN_VISIBLE)

        timed.append({"start": start, "end": end, "text": cue["text"]})

        previous_end = end

    return timed


# Sentence and clause marks in the scripts Whisper commonly writes.
_PUNCTUATION = frozenset(".,!?;:…。，、！？؟،।")

# Languages normally written without them.
_UNPUNCTUATED_LANGUAGES = frozenset({"th", "lo", "km", "my", "bo"})

# Too little text to tell (about a minute of speech).
_MIN_WORDS_TO_JUDGE = 150


def lacks_punctuation(segments: Sequence[SegmentLike], language: str | None) -> bool:
    """
    True if a transcript has (almost) no punctuation: under one mark per 50 words.

    Whisper can carry on in an unpunctuated style for minutes once it starts
    in one, typically when a recording begins mid-sentence. Normal speech
    has a mark every few words.
    """

    if language in _UNPUNCTUATED_LANGUAGES:
        return False

    text = " ".join(segment.text for segment in segments)
    words = len(text.split())

    if words < _MIN_WORDS_TO_JUDGE:
        return False

    return sum(ch in _PUNCTUATION for ch in text) * 50 < words


def build_subtitles(
    segments: Iterable[SegmentLike], style: SubtitleStyle, language: str | None = None
) -> list[Cue]:
    """
    Convert Whisper segments into formatted subtitles.

    `language` is the language of the subtitle text (a code such as "en"),
    or None when unknown or mixed. It only affects where lines are broken.
    """

    cues: list[Cue] = []

    for cue in _speech_cues(segments, style):

        lines = split_into_lines(cue["text"], style, language)

        if not lines:
            continue

        cue["text"] = "\n".join(lines)
        cues.append(cue)

    return _apply_timing(cues, style)
