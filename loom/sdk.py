"""Thread-safe in-memory last-known-good SDK; pin a trusted public key out of band."""

import threading
import time

import httpx

from loom.domain import Bundle, evaluate
from loom.signing import verify


class Client:
    def __init__(
        self,
        url: str,
        token: str,
        public_key: str,
        environment: str,
        max_age: float = 60,
        clock=time.monotonic,
    ):
        if not 0 < max_age <= 3600:
            raise ValueError("max_age must be in (0, 3600]")
        self.url, self.token, self.public_key = url.rstrip("/"), token, public_key
        self.environment, self.max_age, self.clock = environment, max_age, clock
        self._lock = threading.RLock()
        self._refresh_lock = threading.Lock()
        self._bundle = None
        self._generation, self._etag, self._checked = -1, None, float("-inf")

    def accept(self, envelope: dict):
        payload = verify(self.public_key, envelope)
        if (
            payload.get("schema_version") != 1
            or payload["environment"] != self.environment
            or type(payload["generation"]) is not int
            or payload["generation"] < 1
        ):
            raise ValueError("snapshot scope/type mismatch")
        bundle = Bundle.model_validate(payload["bundle"])
        with self._lock:
            if payload["generation"] < self._generation:
                raise ValueError("snapshot generation regressed")
            if payload["generation"] == self._generation and bundle != self._bundle:
                raise ValueError("generation changed contents")
            self._bundle, self._generation = bundle, payload["generation"]
            self._checked = self.clock()

    def refresh(self) -> bool:
        # Serialize refreshes so a late 304 cannot renew freshness of a different generation.
        with self._refresh_lock:
            headers = {"Authorization": "Bearer " + self.token}
            if self._etag:
                headers["If-None-Match"] = self._etag
            try:
                response = httpx.get(
                    f"{self.url}/v1/environments/{self.environment.split('/')[-1]}/snapshot",
                    headers=headers,
                    timeout=5,
                    follow_redirects=False,
                )
                if response.status_code == 304:
                    with self._lock:
                        if self._bundle is None:
                            return False
                        self._checked = self.clock()
                    return True
                response.raise_for_status()
                self.accept(response.json())
                self._etag = response.headers.get("etag")
                return True
            except (httpx.HTTPError, ValueError, KeyError, TypeError):
                return False
            except Exception as exc:
                # Signature failures must retain the previous verified bundle, never trust new data.
                from cryptography.exceptions import InvalidSignature

                if isinstance(exc, InvalidSignature):
                    return False
                raise

    def evaluate(self, flag: str, subject: str, default: bool = False) -> dict:
        with self._lock:
            if self._bundle is None or self.clock() - self._checked >= self.max_age:
                return {"value": default, "reason": "stale", "generation": self._generation}
            return {**evaluate(self._bundle, self.environment, flag, subject), "generation": self._generation}
