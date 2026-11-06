"""Media file inspection."""

import av


def get_duration(filename):
    """Get media duration using PyAV."""

    container = av.open(filename)

    try:

        if container.duration is not None:
            return container.duration / av.time_base

        # Fallback
        for stream in container.streams:

            if (
                stream.duration is not None
                and stream.time_base is not None
            ):
                return float(
                    stream.duration
                    * stream.time_base
                )

        return 0.0

    finally:
        container.close()
