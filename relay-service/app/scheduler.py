from __future__ import annotations

import asyncio
import heapq
import itertools


class Scheduler:
    """任务调度器：并发上限 + 优先级（urgent 插队，其余 FIFO）。"""

    def __init__(self, max_concurrent: int, run_fn, on_error=None):
        self.max_concurrent = max_concurrent
        self.run_fn = run_fn  # async (task_id: int)
        self.on_error = on_error  # (task_id, exc)
        self._heap: list[tuple[int, int, int]] = []
        self._seq = itertools.count()
        self._cond = asyncio.Condition()
        self._active = 0
        self._stop = False
        self._worker: asyncio.Task | None = None

    async def start(self) -> None:
        self._worker = asyncio.get_running_loop().create_task(self._loop())

    async def stop(self) -> None:
        self._stop = True
        async with self._cond:
            self._cond.notify_all()
        if self._worker:
            self._worker.cancel()
            try:
                await self._worker
            except asyncio.CancelledError:
                pass

    async def submit(self, task_id: int, priority: str = "normal") -> None:
        prio = 0 if priority == "urgent" else 1
        async with self._cond:
            heapq.heappush(self._heap, (prio, next(self._seq), task_id))
            self._cond.notify()

    @property
    def pending(self) -> int:
        return len(self._heap)

    @property
    def active(self) -> int:
        return self._active

    async def _loop(self) -> None:
        while not self._stop:
            async with self._cond:
                while (not self._heap or self._active >= self.max_concurrent) and not self._stop:
                    await self._cond.wait()
                if self._stop and not self._heap:
                    break
                _, _, task_id = heapq.heappop(self._heap)
                self._active += 1
            try:
                await self.run_fn(task_id)
            except Exception as e:
                if self.on_error:
                    try:
                        self.on_error(task_id, e)
                    except Exception:
                        pass
            finally:
                async with self._cond:
                    self._active -= 1
                    self._cond.notify()
