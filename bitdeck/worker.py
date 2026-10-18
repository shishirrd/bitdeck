"""One JSON request in, one JSON reply out. No image imports until stdin arrives."""
import json
import sys

MAX_REQUEST = 128 * 1024


def main():
    try:
        raw = sys.stdin.buffer.readline(MAX_REQUEST + 1)
        if len(raw) > MAX_REQUEST:
            raise ValueError("Job request is too large.")
        job = json.loads(raw)
        from .core import run_job
        result = run_job(job)
    except Exception as error:
        # No document contents or raw exceptions in the persistent UI/logging.
        from .core import JobError
        message = str(error) if isinstance(error, JobError) else "Could not process this image. Check format, limits, and folder access."
        result = {"ok": False, "error": message}
    sys.stdout.write(json.dumps(result, separators=(",", ":")) + "\n")
    sys.stdout.flush()
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
