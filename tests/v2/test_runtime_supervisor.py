import asyncio
import unittest

from simple_trade.v2.application.runtime_supervisor import RuntimeSupervisor


class RuntimeSupervisorTests(unittest.IsolatedAsyncioTestCase):
    async def test_failure_is_recorded_and_reported(self) -> None:
        failures: list[tuple[str, bool, str]] = []
        supervisor = RuntimeSupervisor(
            lambda name, error, critical: failures.append(
                (name, critical, str(error))
            )
        )

        async def fail() -> None:
            raise RuntimeError("boom")

        with self.assertLogs(level="ERROR"):
            task = supervisor.create_task("failure", fail(), critical=True)
            await asyncio.gather(task, return_exceptions=True)
            await asyncio.sleep(0)

        snapshot = supervisor.snapshots()[0]
        self.assertTrue(snapshot.failed)
        self.assertTrue(snapshot.critical)
        self.assertIn("boom", snapshot.error or "")
        self.assertEqual(failures, [("failure", True, "boom")])

    async def test_stop_cancels_managed_tasks(self) -> None:
        supervisor = RuntimeSupervisor()

        async def wait_forever() -> None:
            await asyncio.Event().wait()

        supervisor.create_task("long-running", wait_forever())
        await asyncio.sleep(0)
        await supervisor.stop(timeout=1)

        snapshot = supervisor.snapshots()[0]
        self.assertTrue(snapshot.done)
        self.assertTrue(snapshot.cancelled)


if __name__ == "__main__":
    unittest.main()
