"""Build targets supported by the current Omarchy ISO builder integration."""

from dataclasses import dataclass


@dataclass(frozen=True)
class Target:
    key: str
    label: str
    channel: str
    iso_ref: str
    source_commit: str = ""
    recipes_commit: str = ""


TARGETS = {
    "stable": Target("stable", "Current Stable", "stable", "quattro"),
    "rc": Target("rc", "Current Release Candidate", "rc", "rc"),
    "edge": Target("edge", "Current Development", "edge", "edge"),
    "v4.0.4": Target("v4.0.4", "Omarchy 4.0.4", "stable", "v4.0.4",
                     "c668141e9c42b13c80c9ca4ea108e11708c5e8a5",
                     "5fe236736607b1a9f6df3c3a4b364515f70eed53"),
    "v4.0.3": Target("v4.0.3", "Omarchy 4.0.3", "stable", "v4.0.3",
                     "0534987009061cbe2dacdde4ad564092ab698d12",
                     "abd760630196aa9a01f6b21b927e7cb7ee01b746"),
}


def get_target(key: str) -> Target:
    try:
        return TARGETS[key]
    except (KeyError, TypeError) as exc:
        raise ValueError(f"Unsupported Omarchy version: {key}") from exc
