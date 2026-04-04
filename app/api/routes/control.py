"""
Service control endpoints.

Exposes lifecycle management so an external orchestrator or AI agent can:
  GET  /api/control/info     — query runtime metadata (PID, version, uptime)
  POST /api/control/restart  — trigger a graceful in-place process restart

Restart mechanism
-----------------
The restart handler schedules an asyncio background task that sleeps 750 ms
(long enough for the HTTP response to be flushed) then calls os.execv() to
replace the current process image with a fresh one using the same interpreter
and argv.  This means the server must have been started via:

    python -m app.cli serve
or
    python app/cli.py serve

so that sys.argv contains the correct re-launch arguments.

The external consumer should poll GET /health until status == "ok" to confirm
the restart completed.
"""
import asyncio
import os
import sys
import time
import datetime

from fastapi import APIRouter, BackgroundTasks

router = APIRouter(prefix="/control", tags=["control"])

# Capture startup state at import time
_START_TIME = time.time()
_START_EXECUTABLE = sys.executable
_START_ARGV = sys.argv[:]

VERSION = "0.1.0"


@router.get("/info")
def service_info():
    """
    Return runtime metadata about this RAGnificent instance.

    Useful for an external agent to confirm which instance it is talking to,
    check the current PID for health monitoring, or verify the version before
    issuing a restart.
    """
    uptime = int(time.time() - _START_TIME)
    started_at = datetime.datetime.utcfromtimestamp(_START_TIME).isoformat() + "Z"

    return {
        "service": "ragnificent",
        "version": VERSION,
        "pid": os.getpid(),
        "uptime_seconds": uptime,
        "started_at": started_at,
        "executable": _START_EXECUTABLE,
    }


@router.post("/restart")
async def restart_service(background_tasks: BackgroundTasks):
    """
    Trigger a graceful in-place restart of the RAGnificent process.

    The response is returned immediately; the actual restart happens ~750 ms
    later once the response has been flushed.  After calling this endpoint,
    the consumer should poll GET /health until it gets a 200 with status "ok"
    to confirm the new process is ready.

    Returns:
        JSON object with status "restarting" and the PID being replaced.
    """
    pid = os.getpid()

    async def _do_restart():
        await asyncio.sleep(0.75)
        # Replace the current process image; inherits same interpreter + args
        os.execv(_START_EXECUTABLE, [_START_EXECUTABLE] + _START_ARGV)

    background_tasks.add_task(_do_restart)

    return {
        "status": "restarting",
        "message": "Process will restart in ~750 ms. Poll GET /health until status == 'ok'.",
        "pid": pid,
    }
