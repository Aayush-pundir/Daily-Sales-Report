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


class PasswordHashing(unittest.TestCase):
    def test_roundtrip_and_wrong_password(self):
        from dsr import db
        h = db.hash_pw("correct horse")
        self.assertTrue(db.check_pw("correct horse", h)); self.assertFalse(db.check_pw("wrong", h))

    def test_works_without_scrypt(self):
        """macOS's system Python 3.9 has no hashlib.scrypt."""
        import hashlib
        from dsr import db
        with mock.patch.object(hashlib, "scrypt", create=True, side_effect=AttributeError("no scrypt")):
            del hashlib.scrypt
            h = db.hash_pw("pw-12345")
            self.assertTrue(db.check_pw("pw-12345", h))

    def test_old_scrypt_hashes_still_verify(self):
        import hashlib
        from dsr import db
        if not hasattr(hashlib, "scrypt"): self.skipTest("this Python has no scrypt")
        salt = b"0123456789abcdef"
        old = salt.hex() + "$" + hashlib.scrypt(b"legacy-pw", salt=salt, n=2 ** 14, r=8, p=1).hex()
        self.assertTrue(db.check_pw("legacy-pw", old))
