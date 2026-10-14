import os, unittest
from unittest import mock
from dsr.app import passwordless


class QuickSignInRule(unittest.TestCase):
    def check(self, env):
        with mock.patch.dict(os.environ, env, clear=False):
            for k in ("DSR_PASSWORDLESS", "HOST"):
                if k not in env: os.environ.pop(k, None)
            return passwordless()

    def test_on_by_default_on_this_computer_only(self):
        self.assertTrue(self.check({}))
        self.assertTrue(self.check({"HOST": "127.0.0.1"}))
        self.assertTrue(self.check({"HOST": "localhost"}))

    def test_off_when_reachable_from_the_network(self):
        self.assertFalse(self.check({"HOST": "0.0.0.0"}))
        self.assertFalse(self.check({"HOST": "192.168.1.20"}))

    def test_explicit_override_wins(self):
        self.assertTrue(self.check({"HOST": "0.0.0.0", "DSR_PASSWORDLESS": "1"}))
        self.assertFalse(self.check({"DSR_PASSWORDLESS": "0"}))


if __name__ == "__main__": unittest.main()
