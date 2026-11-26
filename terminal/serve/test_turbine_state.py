"""Targeted lifecycle checks on the same serialized command interface as the gateway."""
from concurrent.futures import ThreadPoolExecutor
import queue
import threading
import unittest

from serve.turbine_state import CheckpointError, Checkpoints


class Engine:
    def __init__(self):
        self.gen = 1
        self.lines = queue.Queue()
        self.slot_cv = threading.Condition()
        self.ctl = threading.Lock()
        self.slot_busy = [False, False]
        self.slot_claims = set()
        self.slot_held = [[], []]
        self.slot_prompt = [[], []]
        self.commands = []

    def alive(self):
        return True

    def pick_slot(self, ids):
        return self.slot_busy.index(False) if False in self.slot_busy else None

    def _exclusive_control(self):
        return self.ctl

    def _send_for(self, born, command):
        assert born == self.gen and self.ctl.locked()
        self.commands.append(command)
        verb = command.split()[0]
        self.lines.put({"BGEN": "BADM 0 0", "STATE_SAVE": "SAVED 1 3 256",
                        "STATE_RESTORE": "RESTORED 3", "STATE_DROP": "DROPPED"}[verb])


class StateLifecycle(unittest.TestCase):
    def setUp(self):
        self.engine = Engine()
        self.state = Checkpoints(self.engine, "inkling")
        self.ids = [11, 12, 13]
        self.owner = "operator"
        self.identity = ("inkling", object(), object())

    def create(self):
        return self.state.create(self.ids, self.owner, self.identity)["id"]

    def test_concurrent_create_expiration_during_restore_and_next_parent(self):
        def try_create(_):
            try:
                return self.create()
            except CheckpointError as error:
                self.assertEqual(error.status, 409)
        with ThreadPoolExecutor(2) as pool:
            parents = [value for value in pool.map(try_create, range(2)) if value]
        self.assertEqual(len(parents), 1)
        key = parents[0]
        p = self.state.acquire(key, self.owner, self.identity, self.ids + [23])
        self.assertEqual(self.state.delete(key, self.owner), 202)
        with self.assertRaises(CheckpointError) as e:
            self.state.acquire(key, self.owner, self.identity, self.ids)
        self.assertEqual(e.exception.status, 404)
        with self.engine.ctl:
            self.state.restore(p, 1, self.ids + [23])
        self.assertFalse(any(c.startswith("STATE_DROP") for c in self.engine.commands))
        self.state.finish(p, None)
        self.assertEqual(self.engine.commands[-1], "STATE_DROP 1")
        key2 = self.create()
        self.assertNotEqual(key, key2)
        with self.state.lock:
            p2 = self.state.parent
            p2.timer.cancel()
            self.state.expire(p2)
        self.assertIsNone(self.state.parent)

    def test_identity_prefix_owner_restart(self):
        key = self.create()
        for owner, identity, ids, status in (
                ("other", self.identity, self.ids, 404),
                (self.owner, ("qwen",), self.ids, 409),
                (self.owner, self.identity, [11, 12, 14], 409)):
            with self.assertRaises(CheckpointError) as e:
                self.state.acquire(key, owner, identity, ids)
            self.assertEqual(e.exception.status, status)
        self.engine.gen += 1
        with self.assertRaises(CheckpointError) as e:
            self.state.acquire(key, self.owner, self.identity, self.ids)
        self.assertEqual(e.exception.status, 404)
        self.state.parent.timer.cancel()

    def test_delete_retries_when_ordinary_admission_owns_the_wire(self):
        key = self.create()
        p = self.state.parent
        def busy():
            raise ValueError("control still busy")
        self.engine._exclusive_control = busy
        self.assertEqual(self.state.delete(key, self.owner), 202)
        p.timer.cancel()
        self.engine._exclusive_control = lambda: self.engine.ctl
        self.state.expire(p)
        self.assertIsNone(self.state.parent)
        self.assertEqual(self.engine.commands[-1], "STATE_DROP 1")

    def test_disconnected_slot_holds_lease_until_backend_releases(self):
        key = self.create()
        p = self.state.acquire(key, self.owner, self.identity, self.ids)
        self.engine.slot_busy[1] = True
        self.state.finish(p, (1, 1))
        self.assertEqual(self.state.delete(key, self.owner), 202)
        dropped = threading.Event()
        send = self.engine._send_for
        def notify(born, command):
            send(born, command)
            if command.startswith("STATE_DROP "):
                dropped.set()
        self.engine._send_for = notify
        with self.engine.slot_cv:
            self.engine.slot_busy[1] = False
            self.engine.slot_cv.notify_all()
        self.assertTrue(dropped.wait(2))
        with self.state.lock:
            self.assertIsNone(self.state.parent)
