from __future__ import annotations

import unittest
from unittest import mock


class PlatformHelpersTests(unittest.TestCase):
    def test_user_suffix_uses_getuid_on_posix(self) -> None:
        with mock.patch.object(__import__("runtime.platform", fromlist=["os"]).os, "getuid", create=True, return_value=12345):
            from runtime.platform import user_suffix
            self.assertEqual(user_suffix(), "12345")

    def test_user_suffix_falls_back_to_username_on_win32(self) -> None:
        import runtime.platform as platform
        with mock.patch.object(platform, "os", spec=platform.os) as fake_os:
            delattr(fake_os, "getuid")
            fake_os.environ.get.side_effect = ["testuser", "testuser"]
            self.assertEqual(platform.user_suffix(), "testuser")

    def test_resolve_spawn_arg_resolves_bare_command(self) -> None:
        import runtime.platform as platform
        with mock.patch("runtime.platform.shutil.which", return_value="C:\\Tools\\npm.cmd"):
            self.assertEqual(
                platform.resolve_spawn_arg(["npm", "install"]),
                ["C:\\Tools\\npm.cmd", "install"],
            )

    def test_resolve_spawn_arg_preserves_argv_when_not_found(self) -> None:
        import runtime.platform as platform
        with mock.patch("runtime.platform.shutil.which", return_value=None):
            self.assertEqual(platform.resolve_spawn_arg(["npm", "install"]), ["npm", "install"])
            self.assertEqual(platform.resolve_spawn_arg([]), [])

    def test_terminate_and_kill_use_killpg_on_posix(self) -> None:
        import runtime.platform as platform
        process = mock.Mock()
        process.pid = 42
        fake_signal = mock.Mock(SIGTERM=15, SIGKILL=9)
        with mock.patch.object(platform, "os", create=True) as fake_os, \
                mock.patch.object(platform, "signal", fake_signal):
            fake_os.getpgid.return_value = 99
            fake_os.killpg = mock.Mock()
            platform.terminate_process(process)
            fake_os.killpg.assert_called_once_with(99, 15)
            platform.kill_process(process)
            fake_os.killpg.assert_called_with(99, 9)
            self.assertFalse(process.terminate.called)
            self.assertFalse(process.kill.called)

    def test_terminate_and_kill_fall_back_to_process_controls(self) -> None:
        import runtime.platform as platform
        process = mock.Mock()
        with mock.patch.object(platform, "os", spec=platform.os) as fake_os:
            delattr(fake_os, "killpg")
            platform.terminate_process(process)
            process.terminate.assert_called_once_with()
            platform.kill_process(process)
            process.kill.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
