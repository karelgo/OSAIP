"""Job step logs (ADR-0007 §6).

S3 has no append, so a step's log is a sequence of immutable chunk objects
(`.../step-<n>/chunk-<k>.log`). The worker buffers text and flushes chunks; the log
endpoint tails them by byte offset. `JobStep.log_size` tracks the total bytes written
so a reader knows where the tail is.

Both `StepLogWriter.flush` and `read_step_log` do blocking boto3 I/O — callers in an
async context route them through `osaip_engine.aio.run_engine`.
"""

from typing import Any

from osaip_engine.storage import Storage

FLUSH_BYTES = 4096  # flush a chunk once this many bytes have buffered (~1 chunk/second)


def step_log_prefix(project_key: str, job_id: Any, ordinal: int) -> str:
    return f"projects/{project_key}/artifacts/jobs/{job_id}/step-{ordinal}"


def _chunk_index(key: str) -> int:
    return int(key.rsplit("chunk-", 1)[1].split(".log", 1)[0])


class StepLogWriter:
    """Buffers step log text and flushes immutable chunk objects. `write` is a pure
    in-memory append; `flush` performs the (blocking) S3 write and returns the running
    total byte count (== JobStep.log_size). The worker calls `write(...)` then
    `run_engine(writer.flush)` at phase boundaries or when `should_flush()` is true."""

    def __init__(self, storage: Storage, log_prefix: str) -> None:
        self._storage = storage
        self._prefix = log_prefix
        self._buffer: list[str] = []
        self._buffered_bytes = 0
        self._chunk = 0
        self.total_bytes = 0

    def write(self, text: str) -> None:
        if not text:
            return
        self._buffer.append(text)
        self._buffered_bytes += len(text.encode("utf-8"))

    def should_flush(self) -> bool:
        return self._buffered_bytes >= FLUSH_BYTES

    def flush(self) -> int:
        """Persist buffered text as the next immutable chunk. Blocking (boto3)."""
        if not self._buffered_bytes:
            return self.total_bytes
        data = "".join(self._buffer).encode("utf-8")
        self._storage.put_bytes(data, f"{self._prefix}/chunk-{self._chunk}.log")
        self._chunk += 1
        self.total_bytes += len(data)
        self._buffer.clear()
        self._buffered_bytes = 0
        return self.total_bytes


def read_step_log(storage: Storage, log_prefix: str, *, after: int = 0) -> dict[str, Any]:
    """Concatenate the step's chunk objects and return the slice at/after byte offset
    `after`, plus the new tail offset. `after` is a byte count into the logical
    concatenation (chunks ordered by index), letting the run drawer poll incrementally.
    Blocking (boto3)."""
    keys = sorted(
        (key for key, _ in storage.list_keys(f"{log_prefix}/") if key.endswith(".log")),
        key=_chunk_index,
    )
    parts: list[bytes] = []
    offset = 0  # cumulative bytes across chunks processed so far
    for key in keys:
        chunk_start = offset
        if after <= chunk_start:
            # Whole chunk is new.
            data = storage.get_range(key, 0)
            parts.append(data)
            offset = chunk_start + len(data)
        else:
            # `after` is inside or past this chunk — fetch only the still-unseen suffix.
            suffix = storage.get_range(key, after - chunk_start)
            if suffix:
                parts.append(suffix)
                offset = after + len(suffix)  # == chunk_start + chunk_size
            else:
                # `after` is at/beyond this chunk's end; read it to learn its size.
                offset = chunk_start + len(storage.get_range(key, 0))
    return {"content": b"".join(parts).decode("utf-8", errors="replace"), "next_offset": offset}
