"""Night Survivors - make the short sound files in sounds/.

Run this on your own computer:  python make_sounds.py
main.py never imports wave, it only loads the finished files.

Only the standard library is used, so no extra package is needed to make sound.
Every file is one mono 16-bit wav at 22050 samples per second.
"""

import math
import random
import struct
import wave
from pathlib import Path

RATE = 22050  # samples per second
OUT = Path("sounds")
PEAK = 0.7    # the loudest point of a finished file, so all five sound even
SEED = 2026   # the same hiss every time this runs


def tone(frequency, seconds, decay=4.0, bend=1.0, loudness=1.0):
    """One sine note that fades out. `bend` multiplies the pitch by the end."""
    total = int(RATE * seconds)
    samples = []
    phase = 0.0
    for index in range(total):
        at = index / total
        phase += 2.0 * math.pi * frequency * (1.0 + (bend - 1.0) * at) / RATE
        samples.append(math.sin(phase) * loudness * (1.0 - at) ** decay)
    return samples


def noise(seconds, decay=4.0, loudness=1.0):
    """A short burst of hiss, for hits and bruises."""
    total = int(RATE * seconds)
    return [random.uniform(-1.0, 1.0) * loudness * (1.0 - index / total) ** decay
            for index in range(total)]


def rest(seconds):
    """Silence, so two notes do not run into each other."""
    return [0.0] * int(RATE * seconds)


def then(*tracks):
    """One after the other."""
    out = []
    for track in tracks:
        out += track
    return out


def together(*tracks):
    """On top of each other."""
    longest = max(len(track) for track in tracks)
    out = [0.0] * longest
    for track in tracks:
        for index, value in enumerate(track):
            out[index] += value
    return out


def build():
    """The five sounds of the game, as lists of samples."""
    return {
        # a quick bright blip: a spark, a blade or the ring touching something
        "hit": together(tone(1000.0, 0.07, decay=10.0, bend=0.55),
                        noise(0.02, decay=16.0, loudness=0.5)),
        # two high pings going up: a gem flew into the hero
        "gem": then(tone(1180.0, 0.05, decay=7.0), rest(0.012),
                    tone(1760.0, 0.09, decay=7.0)),
        # three notes going up: the cards are coming
        "levelup": then(tone(660.0, 0.09, decay=4.0), tone(880.0, 0.09, decay=4.0),
                        tone(1320.0, 0.24, decay=3.0)),
        # a low thump with hiss: the hero was hurt
        "hurt": together(tone(180.0, 0.22, decay=3.0, bend=0.6),
                         noise(0.12, decay=7.0, loudness=0.6)),
        # falling away: the clock ran out or the hero stopped
        "end": then(together(tone(520.0, 0.16, decay=4.0), tone(260.0, 0.16, decay=4.0)),
                    together(tone(390.0, 0.5, decay=2.0, bend=0.5),
                             tone(195.0, 0.5, decay=2.0, bend=0.5))),
    }


def save(name, samples):
    """Write one wav file, made as loud as PEAK at its loudest point."""
    loudest = max((abs(value) for value in samples), default=0.0)
    scale = PEAK / loudest if loudest > 0.0 else 0.0
    frames = bytearray()
    for value in samples:
        frames += struct.pack("<h", int(round(max(-1.0, min(1.0, value * scale)) * 32767)))
    path = OUT / (name + ".wav")
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(RATE)
        handle.writeframes(bytes(frames))
    return path


def main():
    random.seed(SEED)
    OUT.mkdir(exist_ok=True)
    made = [save(name, samples).name for name, samples in sorted(build().items())]
    print("wrote %d files to %s/: %s" % (len(made), OUT, ", ".join(made)))


if __name__ == "__main__":
    main()
