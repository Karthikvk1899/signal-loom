"""Versioned evaluation contract. No network, database, clock or random state."""
import hashlib
import json
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, model_validator

Name = Annotated[str, Field(pattern=r"^[a-z][a-z0-9_-]{0,63}$")]
Subject = Annotated[str, Field(min_length=1, max_length=256)]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class Flag(StrictModel):
    key: Name
    enabled: bool = True
    rollout: int = Field(ge=0, le=10000)
    salt: str = Field(min_length=1, max_length=64, pattern=r"^[a-zA-Z0-9_-]+$")
    allow: list[Subject] = Field(default_factory=list, max_length=100)
    deny: list[Subject] = Field(default_factory=list, max_length=100)


class Bundle(StrictModel):
    schema_version: int = Field(default=1, ge=1, le=1)
    flags: list[Flag] = Field(max_length=100)

    @model_validator(mode="after")
    def unique_keys(self):
        keys = [f.key for f in self.flags]
        if len(keys) != len(set(keys)):
            raise ValueError("duplicate flag keys")
        return self


def canonical(data: dict) -> bytes:
    return json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()


def bucket(environment: str, flag: Flag, subject: str) -> int:
    # JSON array framing prevents concatenation ambiguity. First 64 hash bits, big endian.
    raw = canonical({"environment": environment, "flag": flag.key, "salt": flag.salt, "subject": subject})
    return int.from_bytes(hashlib.sha256(raw).digest()[:8], "big") % 10000


def evaluate(bundle: Bundle, environment: str, key: str, subject: str) -> dict:
    for flag in bundle.flags:
        if flag.key != key:
            continue
        if not flag.enabled:
            return {"value": False, "reason": "disabled"}
        if subject in flag.deny:
            return {"value": False, "reason": "deny"}
        if subject in flag.allow:
            return {"value": True, "reason": "allow"}
        slot = bucket(environment, flag, subject)
        return {"value": slot < flag.rollout, "reason": "rollout", "bucket": slot}
    return {"value": False, "reason": "missing"}
