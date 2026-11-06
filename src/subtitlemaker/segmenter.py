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


def adjust_timing(start, end, text, style):
    """
    Adjust subtitle duration according to reading speed.

    The subtitle is never made shorter than `style.min_duration`
    and never longer than `style.max_duration`.
    """

    duration = end - start

    # Required duration based on CPS
    required_duration = len(text) / style.max_cps

    duration = max(
        duration,
        required_duration,
        style.min_duration,
    )

    duration = min(
        duration,
        style.max_duration,
    )

    return start, start + duration


def build_subtitles(segments, style):
    """Convert Whisper segments into formatted subtitles."""

    subtitles = []
    previous_end = 0.0

    for segment in segments:

        text = clean_text(segment.text)

        if not text:
            continue

        start = float(segment.start)
        end = float(segment.end)

        # Maximum characters allowed in one subtitle cue
        max_chars = style.max_line_length * style.max_lines

        # Split long Whisper segments
        if len(text) <= max_chars:
            chunks = [text]

        else:
            words = text.split()
            chunks = []
            current = ""

            for word in words:

                candidate = f"{current} {word}".strip()

                if len(candidate) <= max_chars:
                    current = candidate

                else:
                    if current:
                        chunks.append(current)

                    current = word

            if current:
                chunks.append(current)

        # Distribute the original segment duration
        # proportionally between chunks.
        total_chars = sum(len(chunk) for chunk in chunks)

        current_start = start

        for chunk in chunks:

            proportion = len(chunk) / total_chars

            chunk_duration = (
                (end - start) * proportion
            )

            chunk_end = (
                current_start + chunk_duration
            )

            lines = split_into_lines(chunk, style)

            if not lines:
                continue

            display_text = "\n".join(lines)

            plain_text = display_text.replace(
                "\n",
                " ",
            )

            adjusted_start, adjusted_end = (
                adjust_timing(
                    current_start,
                    chunk_end,
                    plain_text,
                    style,
                )
            )

            # Prevent overlap
            adjusted_start = max(
                adjusted_start,
                previous_end + style.min_gap,
            )

            # Safety
            if adjusted_end <= adjusted_start:
                adjusted_end = (
                    adjusted_start + style.min_duration
                )

            subtitles.append(
                {
                    "start": adjusted_start,
                    "end": adjusted_end,
                    "text": display_text,
                }
            )

            previous_end = adjusted_end
            current_start = chunk_end

    return subtitles
