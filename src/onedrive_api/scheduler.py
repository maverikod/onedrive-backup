"""The backup scheduler thread: it reads the schedule, decides and starts backup runs as child processes (10.20.5)."""

from __future__ import annotations

import atexit
import logging
import os
import subprocess
import sys
import threading
import time
from datetime import UTC, datetime
from pathlib import Path
from functools import partial
from typing import Any, Callable

from .run_records import append_complete, load_runs, reconcile, runs_path, trim
from .schedule_cron import iso_utc, jitter_delay
from .schedule_store import ScheduleStore
from .scheduler_decide import Action, decide, next_state, slots
from . import scheduler_support as support

__all__ = ["Action", "Scheduler", "decide", "jitter_delay", "next_state", "slots", "start_scheduler"]

LOG = logging.getLogger("onedrive_backup")
TICK_SECONDS = 30.0
CHILD_POLL_SECONDS = 5.0
SHUTDOWN_WAIT_SECONDS = 8
BACKUP_ARGV = [sys.executable, "-m", "onedrive_api.backup_run"]
STATES = {"not_leader", "scaffold", "storage_unavailable", "paused", "idle"}
CODE_STATUS = {0: "ok", 1: "errors", 2: "refused"}
INSTANCE: Scheduler | None = None


def spawn(argv: list[str], env: dict[str, str]) -> Any:
    """Start the backup run as a child process of the service.

    Args:
        argv: The command line.
        env: The environment.

    Returns:
        The child process.
    """
    return subprocess.Popen(argv, env=env, stdin=subprocess.DEVNULL)


class Scheduler:
    """The scheduler core: one tick reads, decides and acts; the thread only repeats ticks.

    Attributes:
        data_dir: The service data directory.
        clock: The clock.
        runner: Starts the backup child.
        lock_probe: True when the backup lock is held.
        storage_guard: The storage guard G2.
        scaffold: True in scaffold mode.
        manage_leader: True when the scheduler takes the leader lock itself.
        store: The schedule store.
        runs: The run record file.
        leader: True while this process holds the leader lock.
        started: The instant the scheduler was created.
        child: The running backup child, or None.
        launch: The slot, start and trigger of the child, or None.
        last_tick: The instant of the last tick, or None.
        last_action: The last decision.
        state_name: The state shown by the status command.
        message: The text of the state.
        source: The source of the effective schedule.
        valid: True when the stored file is valid.
        state: The baseline state, or None before the first tick.
        next_wait_seconds: How long the thread sleeps before the next tick.
        thread: The scheduler thread, or None.
        wake: Wakes the thread before its sleep ends.
        stop_event: Set when the thread must end.
        _reconciled: True after the first tick closed the interrupted runs.
        _leader_fd: The descriptor that holds the leader lock, or None.
        _dropped: The slots already logged as dropped.
    """

    def __init__(
        self,
        data_dir: str | Path,
        *,
        clock: Callable[[], datetime] | None = None,
        runner: Callable[[list[str], dict[str, str]], Any] | None = None,
        lock_probe: Callable[[], bool] | None = None,
        storage_ok: Callable[[], bool] | None = None,
        scaffold: bool | None = None,
        manage_leader: bool = False,
    ) -> None:
        """Build the scheduler; nothing is read or started.

        Args:
            data_dir: The service data directory.
            clock: The clock; the system clock when omitted.
            runner: Starts the backup child; spawn() when omitted.
            lock_probe: True when the backup lock is held; a non-blocking flock probe when omitted.
            storage_ok: The storage guard G2; the st_dev rule when omitted.
            scaffold: Scaffold mode; ONEDRIVE_SCAFFOLD_MODE when omitted.
            manage_leader: Take the leader lock on schedule/scheduler.lock.
        """
        self.data_dir = Path(data_dir)
        self.clock = clock or (lambda: datetime.now(UTC))
        self.runner = runner or spawn
        self.lock_probe = lock_probe or partial(support.probe_lock, self.data_dir)
        self.storage_guard = storage_ok or partial(support.storage_guard, self.data_dir)
        self.scaffold = os.environ.get("ONEDRIVE_SCAFFOLD_MODE") == "1" if scaffold is None else scaffold
        self.manage_leader = manage_leader
        self.leader = True
        self.store = ScheduleStore(self.data_dir / "schedule", self.storage_guard)
        self.runs = runs_path(self.data_dir)
        self.started = self.clock()
        self.state: dict[str, Any] | None = None
        self.child: Any = None
        self.launch: dict[str, Any] | None = None
        self.last_tick: datetime | None = None
        self.last_action = Action("NOTHING", reason="starting")
        self.state_name = "starting"
        self.message = "the scheduler is starting"
        self.source = "default"
        self.valid = True
        self.next_wait_seconds = TICK_SECONDS
        self.thread: threading.Thread | None = None
        self.wake = threading.Event()
        self.stop_event = threading.Event()
        self._reconciled = False
        self._leader_fd: int | None = None
        self._dropped: set[str] = set()

    def _take_leader(self) -> bool:
        """Take the leader lock for the life of the process.

        Returns:
            True when this process is the leader.
        """
        self._leader_fd = support.take_leader(self.data_dir)
        return self._leader_fd is not None

    def _observe(self, parsed: dict[str, Any], now: datetime) -> dict[str, Any]:
        """Apply the baseline rule to the revision of the effective schedule and keep the state.

        Args:
            parsed: The effective schedule.
            now: The instant of the tick.

        Returns:
            The state.
        """
        if self.state is None:
            stored = support.load_state(self.data_dir)
            if stored is None:
                stored = {"schedule_revision": parsed["revision"], "baseline_utc": iso_utc(self.started)}
                support.save_state(self.data_dir, stored)
            self.state = dict(stored, thread_started_utc=iso_utc(self.started))
        updated = next_state(self.state, parsed["revision"], now)
        if updated["schedule_revision"] != self.state["schedule_revision"]:
            support.save_state(self.data_dir, updated)
            LOG.info("scheduler: schedule revision %s in force", parsed["revision"][:12])
            if parsed["revision"] not in support.changes_tail(self.data_dir):
                self.store.log_change("file", self.state["schedule_revision"], parsed["revision"], parsed)
        self.state = updated
        return updated

    def _live(self) -> list[dict[str, Any]]:
        """Describe the child of this scheduler as a running record while it lives.

        Returns:
            A list with one record, or empty.
        """
        if self.child is None or self.launch is None:
            return []
        return [{"run_id": "scheduler-child", "started_at": self.launch["started"], "finished_at": None, "exit_code": None,
                 "status": "running", "trigger": self.launch["trigger"], "slot_utc": self.launch["slot"],
                 "pid": getattr(self.child, "pid", None), "dry_run": False}]

    def _poll_child(self, now: datetime) -> None:
        """Collect the exit of the child and make sure its slot has a record.

        Args:
            now: The instant of the tick.

        Returns:
            None.
        """
        if self.child is None or self.launch is None:
            return
        code = self.child.poll()
        if code is None:
            return
        info = self.launch
        status = CODE_STATUS.get(code, "interrupted")
        LOG.info("scheduler: run finished exit=%s status=%s", code, status)
        records = load_runs(self.runs)
        known = [x for x in records if x["slot_utc"] == info["slot"] and str(x["started_at"]) >= info["started"]]
        if not known:
            append_complete(self.runs, status, info["trigger"], info["slot"], now, code)
        self.child = None
        self.launch = None

    def _execute(self, action: Action, now: datetime) -> None:
        """Carry out START, SKIP_BUSY and the log of a dropped slot.

        Args:
            action: The decision.
            now: The instant of the tick.

        Returns:
            None.
        """
        slot = iso_utc(action.slot_utc) if action.slot_utc else None
        if action.kind == "START" and slot and action.trigger:
            env = dict(os.environ)
            env["ONEDRIVE_RUN_TRIGGER"] = action.trigger
            env["ONEDRIVE_RUN_SLOT"] = slot
            try:
                self.child = self.runner(list(BACKUP_ARGV), env)
            except Exception as exc:  # noqa: BLE001 - a failed launch is recorded, never fatal
                LOG.error("scheduler: the backup could not be started: %s", exc)
                append_complete(self.runs, "launch_failed", action.trigger, slot, now)
                return
            self.launch = {"slot": slot, "started": iso_utc(now), "trigger": action.trigger}
            LOG.info("scheduler: starting backup run slot=%s trigger=%s", slot, action.trigger)
        elif action.kind == "SKIP_BUSY":
            LOG.warning("scheduler: slot skipped, a backup is still running (slot %s)", slot)
            append_complete(self.runs, "skipped_busy", "schedule", slot, now)
        elif action.reason == "dropped" and slot and slot not in self._dropped:
            self._dropped.add(slot)
            LOG.warning("scheduler: missed slot dropped (slot %s)", slot)

    def _remember(self, action: Action, read: dict[str, Any], busy: bool) -> None:
        """Derive the state shown by the status command.

        Args:
            action: The decision.
            read: The result of the store read.
            busy: The lock probe.

        Returns:
            None.
        """
        reason = action.reason or ""
        if busy:
            name = "running"
        elif reason in STATES:
            name = reason
        elif not read["valid"]:
            name = "file_invalid"
        else:
            name = "waiting"
        self.state_name = name
        self.message = {"waiting": "waiting for the next planned start", "running": "a backup is running"}.get(name, name)
        self.source, self.valid, self.last_action = read["source"], read["valid"], action

    def _tick(self) -> Action:
        """Run one tick: probe, reconcile, read, decide, act.

        Returns:
            The decision.
        """
        now = self.clock()
        self.last_tick = now
        busy = bool(self.lock_probe())
        guard = bool(self.storage_guard())
        if self.manage_leader and self._leader_fd is None and guard:
            self.leader = self._take_leader()
        if not self._reconciled and guard:
            self._reconciled = True
            if not busy and reconcile(self.runs, now):
                LOG.warning("scheduler: interrupted runs closed at start")
            trim(self.runs)
        read = self.store.read(create_missing=guard and not self.scaffold)
        state = self._observe(read["parsed"], now)
        self._poll_child(now)
        runs = load_runs(self.runs) + self._live()
        action = decide(now, read["parsed"], runs, state, busy, leader=self.leader, scaffold=self.scaffold, storage_ok=guard)
        self._execute(action, now)
        self._remember(action, read, busy)
        wait = TICK_SECONDS
        if self.child is not None:
            wait = CHILD_POLL_SECONDS
        elif action.kind == "WAIT" and action.until is not None:
            wait = min(TICK_SECONDS, max(1.0, (action.until - now).total_seconds()))
        self.next_wait_seconds = wait
        return action

    def tick(self) -> Action:
        """Run one tick; an exception is logged and never escapes.

        Returns:
            The decision, or NOTHING with the reason error.
        """
        try:
            return self._tick()
        except Exception:  # noqa: BLE001 - the thread must survive any failure of one tick
            LOG.exception("scheduler: tick failed")
            self.next_wait_seconds = TICK_SECONDS
            return Action("NOTHING", reason="error")

    def snapshot(self) -> dict[str, Any]:
        """Describe the scheduler for the status command.

        Returns:
            state, thread_alive, started_at, last_tick_at, leader and message.
        """
        return {
            "state": self.state_name, "thread_alive": bool(self.thread and self.thread.is_alive()),
            "started_at": iso_utc(self.started), "last_tick_at": iso_utc(self.last_tick) if self.last_tick else None,
            "leader": self.leader, "message": self.message,
        }

    def run_forever(self) -> None:
        """Tick until stopped, sleeping next_wait_seconds or until woken.

        Returns:
            None.
        """
        while not self.stop_event.is_set():
            self.tick()
            self.wake.wait(self.next_wait_seconds)
            self.wake.clear()

    def start(self) -> None:
        """Start the daemon thread backup-scheduler.

        Returns:
            None.
        """
        self.thread = threading.Thread(target=self.run_forever, name="backup-scheduler", daemon=True)
        self.thread.start()

    def shutdown(self, sleep: Callable[[float], None] = time.sleep) -> None:
        """Stop the thread and end the child: SIGTERM, up to eight seconds of waiting, then SIGKILL.

        Args:
            sleep: The sleep function, replaceable for tests.

        Returns:
            None.
        """
        self.stop_event.set()
        self.wake.set()
        if self.child is None:
            return
        self.child.terminate()
        for _ in range(SHUTDOWN_WAIT_SECONDS):
            if self.child.poll() is not None:
                return
            sleep(1.0)
        if self.child.poll() is None:
            LOG.warning("scheduler: the backup did not stop within %d s, killed", SHUTDOWN_WAIT_SECONDS)
            self.child.kill()


def start_scheduler(data_dir: str | Path) -> Scheduler:
    """Create the process-wide scheduler, prepare its store and start its thread.

    Args:
        data_dir: The service data directory.

    Returns:
        The scheduler; a second call returns the first.
    """
    global INSTANCE
    if INSTANCE is not None:
        return INSTANCE
    scheduler = Scheduler(data_dir, manage_leader=True)
    if not scheduler.scaffold:
        scheduler.store.bootstrap()
    scheduler.start()
    atexit.register(scheduler.shutdown)
    INSTANCE = scheduler
    return scheduler
