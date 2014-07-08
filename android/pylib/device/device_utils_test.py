# Copyright 2014 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""
Unit tests for the contents of device_utils.py (mostly DeviceUtils).
"""

# pylint: disable=C0321
# pylint: disable=W0212
# pylint: disable=W0613

import collections
import datetime
import logging
import os
import re
import signal
import sys
import unittest

from pylib import android_commands
from pylib import constants
from pylib.device import adb_wrapper
from pylib.device import device_errors
from pylib.device import device_utils
from pylib.device import intent

sys.path.append(os.path.join(
    constants.DIR_SOURCE_ROOT, 'third_party', 'android_testrunner'))
import run_command as atr_run_command

sys.path.append(os.path.join(
    constants.DIR_SOURCE_ROOT, 'third_party', 'pymock'))
import mock # pylint: disable=F0401


class DeviceUtilsTest(unittest.TestCase):

  def testInitWithStr(self):
    serial_as_str = str('0123456789abcdef')
    d = device_utils.DeviceUtils('0123456789abcdef')
    self.assertEqual(serial_as_str, d.old_interface.GetDevice())

  def testInitWithUnicode(self):
    serial_as_unicode = unicode('fedcba9876543210')
    d = device_utils.DeviceUtils(serial_as_unicode)
    self.assertEqual(serial_as_unicode, d.old_interface.GetDevice())

  def testInitWithAdbWrapper(self):
    serial = '123456789abcdef0'
    a = adb_wrapper.AdbWrapper(serial)
    d = device_utils.DeviceUtils(a)
    self.assertEqual(serial, d.old_interface.GetDevice())

  def testInitWithAndroidCommands(self):
    serial = '0fedcba987654321'
    a = android_commands.AndroidCommands(device=serial)
    d = device_utils.DeviceUtils(a)
    self.assertEqual(serial, d.old_interface.GetDevice())

  def testInitWithNone(self):
    d = device_utils.DeviceUtils(None)
    self.assertIsNone(d.old_interface.GetDevice())


# TODO(jbudorick) Split this into separate classes by DeviceUtils function.
class DeviceUtilsOldImplTest(unittest.TestCase):

  class AndroidCommandsCalls(object):

    def __init__(self, test_case, cmd_ret, comp):
      self._cmds = cmd_ret
      self._comp = comp
      self._test_case = test_case
      self._total_received = 0

    def __enter__(self):
      atr_run_command.RunCommand = mock.Mock()
      atr_run_command.RunCommand.side_effect = lambda c, **kw: self._ret(c)

    def _ret(self, actual_cmd):
      if sys.exc_info()[0] is None:
        on_failure_fmt = ('\n'
                          '  received command: %s\n'
                          '  expected command: %s')
        self._test_case.assertGreater(
            len(self._cmds), self._total_received,
            msg=on_failure_fmt % (actual_cmd, None))
        expected_cmd, ret = self._cmds[self._total_received]
        self._total_received += 1
        self._test_case.assertTrue(
            self._comp(expected_cmd, actual_cmd),
            msg=on_failure_fmt % (actual_cmd, expected_cmd))
        return ret
      return ''

    def __exit__(self, exc_type, _exc_val, exc_trace):
      if exc_type is None:
        on_failure = "adb commands don't match.\nExpected:%s\nActual:%s" % (
            ''.join('\n  %s' % c for c, _ in self._cmds),
            ''.join('\n  %s' % a[0]
                    for _, a, kw in atr_run_command.RunCommand.mock_calls))
        self._test_case.assertEqual(
          len(self._cmds), len(atr_run_command.RunCommand.mock_calls),
          msg=on_failure)
        for (expected_cmd, _r), (_n, actual_args, actual_kwargs) in zip(
            self._cmds, atr_run_command.RunCommand.mock_calls):
          self._test_case.assertEqual(1, len(actual_args), msg=on_failure)
          self._test_case.assertTrue(self._comp(expected_cmd, actual_args[0]),
                                     msg=on_failure)
          self._test_case.assertTrue('timeout_time' in actual_kwargs,
                                     msg=on_failure)
          self._test_case.assertTrue('retry_count' in actual_kwargs,
                                     msg=on_failure)

  def assertNoAdbCalls(self):
    return type(self).AndroidCommandsCalls(self, [], str.__eq__)

  def assertOldImplCalls(self, cmd, ret, comp=str.__eq__):
    return type(self).AndroidCommandsCalls(self, [(cmd, ret)], comp)

  def assertOldImplCallsSequence(self, cmd_ret, comp=str.__eq__):
    return type(self).AndroidCommandsCalls(self, cmd_ret, comp)

  def setUp(self):
    self.device = device_utils.DeviceUtils(
        '0123456789abcdef', default_timeout=1, default_retries=0)

  def testIsOnline_true(self):
    with self.assertOldImplCalls('adb -s 0123456789abcdef get-state',
                                 'device\r\n'):
      self.assertTrue(self.device.IsOnline())

  def testIsOnline_false(self):
    with self.assertOldImplCalls('adb -s 0123456789abcdef get-state', '\r\n'):
      self.assertFalse(self.device.IsOnline())

  def testHasRoot_true(self):
    with self.assertOldImplCalls("adb -s 0123456789abcdef shell 'ls /root'",
                                 'foo\r\n'):
      self.assertTrue(self.device.HasRoot())

  def testHasRoot_false(self):
    with self.assertOldImplCalls("adb -s 0123456789abcdef shell 'ls /root'",
                                 'Permission denied\r\n'):
      self.assertFalse(self.device.HasRoot())

  def testEnableRoot_succeeds(self):
    with self.assertOldImplCallsSequence([
        ('adb -s 0123456789abcdef shell getprop ro.build.type',
         'userdebug\r\n'),
        ('adb -s 0123456789abcdef root', 'restarting adbd as root\r\n'),
        ('adb -s 0123456789abcdef wait-for-device', ''),
        ('adb -s 0123456789abcdef wait-for-device', '')]):
      self.device.EnableRoot()

  def testEnableRoot_userBuild(self):
    with self.assertOldImplCallsSequence([
        ('adb -s 0123456789abcdef shell getprop ro.build.type', 'user\r\n')]):
      with self.assertRaises(device_errors.CommandFailedError):
        self.device.EnableRoot()

  def testEnableRoot_rootFails(self):
    with self.assertOldImplCallsSequence([
        ('adb -s 0123456789abcdef shell getprop ro.build.type',
         'userdebug\r\n'),
        ('adb -s 0123456789abcdef root', 'no\r\n'),
        ('adb -s 0123456789abcdef wait-for-device', '')]):
      with self.assertRaises(device_errors.CommandFailedError):
        self.device.EnableRoot()

  def testGetExternalStoragePath_succeeds(self):
    fakeStoragePath = '/fake/storage/path'
    with self.assertOldImplCalls(
        "adb -s 0123456789abcdef shell 'echo $EXTERNAL_STORAGE'",
        '%s\r\n' % fakeStoragePath):
      self.assertEquals(fakeStoragePath,
                        self.device.GetExternalStoragePath())

  def testGetExternalStoragePath_fails(self):
    with self.assertOldImplCalls(
        "adb -s 0123456789abcdef shell 'echo $EXTERNAL_STORAGE'", '\r\n'):
      with self.assertRaises(device_errors.CommandFailedError):
        self.device.GetExternalStoragePath()

  def testWaitUntilFullyBooted_succeedsNoWifi(self):
    with self.assertOldImplCallsSequence([
        # AndroidCommands.WaitForSystemBootCompleted
        ('adb -s 0123456789abcdef wait-for-device', ''),
        ('adb -s 0123456789abcdef shell getprop sys.boot_completed', '1\r\n'),
        # AndroidCommands.WaitForDevicePm
        ('adb -s 0123456789abcdef wait-for-device', ''),
        ('adb -s 0123456789abcdef shell pm path android',
         'package:this.is.a.test.package'),
        # AndroidCommands.WaitForSdCardReady
        ("adb -s 0123456789abcdef shell 'echo $EXTERNAL_STORAGE'",
         '/fake/storage/path'),
        ("adb -s 0123456789abcdef shell 'ls /fake/storage/path'",
         'nothing\r\n')
        ]):
      self.device.WaitUntilFullyBooted(wifi=False)

  def testWaitUntilFullyBooted_succeedsWithWifi(self):
    with self.assertOldImplCallsSequence([
        # AndroidCommands.WaitForSystemBootCompleted
        ('adb -s 0123456789abcdef wait-for-device', ''),
        ('adb -s 0123456789abcdef shell getprop sys.boot_completed', '1\r\n'),
        # AndroidCommands.WaitForDevicePm
        ('adb -s 0123456789abcdef wait-for-device', ''),
        ('adb -s 0123456789abcdef shell pm path android',
         'package:this.is.a.test.package'),
        # AndroidCommands.WaitForSdCardReady
        ("adb -s 0123456789abcdef shell 'echo $EXTERNAL_STORAGE'",
         '/fake/storage/path'),
        ("adb -s 0123456789abcdef shell 'ls /fake/storage/path'",
         'nothing\r\n'),
        # wait for wifi
        ("adb -s 0123456789abcdef shell 'dumpsys wifi'", 'Wi-Fi is enabled')]):
      self.device.WaitUntilFullyBooted(wifi=True)

  def testWaitUntilFullyBooted_bootFails(self):
    with mock.patch('time.sleep'):
      with self.assertOldImplCallsSequence([
          # AndroidCommands.WaitForSystemBootCompleted
          ('adb -s 0123456789abcdef wait-for-device', ''),
          ('adb -s 0123456789abcdef shell getprop sys.boot_completed',
           '0\r\n')]):
        with self.assertRaises(device_errors.CommandTimeoutError):
          self.device.WaitUntilFullyBooted(wifi=False)

  def testWaitUntilFullyBooted_devicePmFails(self):
    with mock.patch('time.sleep'):
      with self.assertOldImplCallsSequence([
          # AndroidCommands.WaitForSystemBootCompleted
          ('adb -s 0123456789abcdef wait-for-device', ''),
          ('adb -s 0123456789abcdef shell getprop sys.boot_completed',
           '1\r\n')]
          # AndroidCommands.WaitForDevicePm
        + 3 * ([('adb -s 0123456789abcdef wait-for-device', '')]
             + 24 * [('adb -s 0123456789abcdef shell pm path android', '\r\n')]
             + [("adb -s 0123456789abcdef shell 'stop'", '\r\n'),
                ("adb -s 0123456789abcdef shell 'start'", '\r\n')])):
        with self.assertRaises(device_errors.CommandTimeoutError):
          self.device.WaitUntilFullyBooted(wifi=False)

  def testWaitUntilFullyBooted_sdCardReadyFails_noPath(self):
    with mock.patch('time.sleep'):
      with self.assertOldImplCallsSequence([
          # AndroidCommands.WaitForSystemBootCompleted
          ('adb -s 0123456789abcdef wait-for-device', ''),
          ('adb -s 0123456789abcdef shell getprop sys.boot_completed',
           '1\r\n'),
          # AndroidCommands.WaitForDevicePm
          ('adb -s 0123456789abcdef wait-for-device', ''),
          ('adb -s 0123456789abcdef shell pm path android',
           'package:this.is.a.test.package'),
          ("adb -s 0123456789abcdef shell 'echo $EXTERNAL_STORAGE'", '\r\n')]):
        with self.assertRaises(device_errors.CommandFailedError):
          self.device.WaitUntilFullyBooted(wifi=False)

  def testWaitUntilFullyBooted_sdCardReadyFails_emptyPath(self):
    with mock.patch('time.sleep'):
      with self.assertOldImplCallsSequence([
          # AndroidCommands.WaitForSystemBootCompleted
          ('adb -s 0123456789abcdef wait-for-device', ''),
          ('adb -s 0123456789abcdef shell getprop sys.boot_completed',
           '1\r\n'),
          # AndroidCommands.WaitForDevicePm
          ('adb -s 0123456789abcdef wait-for-device', ''),
          ('adb -s 0123456789abcdef shell pm path android',
           'package:this.is.a.test.package'),
          ("adb -s 0123456789abcdef shell 'echo $EXTERNAL_STORAGE'",
           '/fake/storage/path\r\n'),
          ("adb -s 0123456789abcdef shell 'ls /fake/storage/path'", '')]):
        with self.assertRaises(device_errors.CommandTimeoutError):
          self.device.WaitUntilFullyBooted(wifi=False)

  def testReboot_nonBlocking(self):
    with mock.patch('time.sleep'):
      with self.assertOldImplCallsSequence([
            ('adb -s 0123456789abcdef reboot', ''),
            ('adb -s 0123456789abcdef get-state', 'unknown\r\n'),
            ('adb -s 0123456789abcdef wait-for-device', ''),
            ('adb -s 0123456789abcdef shell pm path android',
             'package:this.is.a.test.package'),
            ("adb -s 0123456789abcdef shell 'echo $EXTERNAL_STORAGE'",
             '/fake/storage/path\r\n'),
            ("adb -s 0123456789abcdef shell 'ls /fake/storage/path'",
             'nothing\r\n')]):
        self.device.Reboot(block=False)

  def testReboot_blocking(self):
    with mock.patch('time.sleep'):
      with self.assertOldImplCallsSequence([
            ('adb -s 0123456789abcdef reboot', ''),
            ('adb -s 0123456789abcdef get-state', 'unknown\r\n'),
            ('adb -s 0123456789abcdef wait-for-device', ''),
            ('adb -s 0123456789abcdef shell pm path android',
             'package:this.is.a.test.package'),
            ("adb -s 0123456789abcdef shell 'echo $EXTERNAL_STORAGE'",
             '/fake/storage/path\r\n'),
            ("adb -s 0123456789abcdef shell 'ls /fake/storage/path'",
             'nothing\r\n'),
            ('adb -s 0123456789abcdef wait-for-device', ''),
            ('adb -s 0123456789abcdef shell getprop sys.boot_completed',
             '1\r\n'),
            ('adb -s 0123456789abcdef wait-for-device', ''),
            ('adb -s 0123456789abcdef shell pm path android',
             'package:this.is.a.test.package'),
            ("adb -s 0123456789abcdef shell 'ls /fake/storage/path'",
             'nothing\r\n')]):
        self.device.Reboot(block=True)

  def testInstall_noPriorInstall(self):
    with mock.patch('os.path.isfile', return_value=True), (
         mock.patch('pylib.utils.apk_helper.GetPackageName',
                    return_value='this.is.a.test.package')):
      with self.assertOldImplCallsSequence([
          ("adb -s 0123456789abcdef shell 'pm path this.is.a.test.package'",
           ''),
          ("adb -s 0123456789abcdef install /fake/test/app.apk",
           'Success\r\n')]):
        self.device.Install('/fake/test/app.apk', retries=0)

  def testInstall_differentPriorInstall(self):
    def mockGetFilesChanged(host_path, device_path, ignore_filenames):
      return [(host_path, device_path)]

    # Pylint raises a false positive "operator not preceded by a space"
    # warning below.
    # pylint: disable=C0322
    with mock.patch('os.path.isfile', return_value=True), (
         mock.patch('os.path.exists', return_value=True)), (
         mock.patch('pylib.utils.apk_helper.GetPackageName',
                    return_value='this.is.a.test.package')), (
         mock.patch('pylib.constants.GetOutDirectory',
                    return_value='/fake/test/out')), (
         mock.patch('pylib.android_commands.AndroidCommands.GetFilesChanged',
                    side_effect=mockGetFilesChanged)):
    # pylint: enable=C0322
      with self.assertOldImplCallsSequence([
          ("adb -s 0123456789abcdef shell 'pm path this.is.a.test.package'",
           'package:/fake/data/app/this.is.a.test.package.apk\r\n'),
          # GetFilesChanged is mocked, so its adb calls are omitted.
          ('adb -s 0123456789abcdef uninstall this.is.a.test.package',
           'Success\r\n'),
          ('adb -s 0123456789abcdef install /fake/test/app.apk',
           'Success\r\n')]):
        self.device.Install('/fake/test/app.apk', retries=0)

  def testInstall_differentPriorInstall_reinstall(self):
    def mockGetFilesChanged(host_path, device_path, ignore_filenames):
      return [(host_path, device_path)]

    # Pylint raises a false positive "operator not preceded by a space"
    # warning below.
    # pylint: disable=C0322
    with mock.patch('os.path.isfile', return_value=True), (
         mock.patch('pylib.utils.apk_helper.GetPackageName',
                    return_value='this.is.a.test.package')), (
         mock.patch('pylib.constants.GetOutDirectory',
                    return_value='/fake/test/out')), (
         mock.patch('pylib.android_commands.AndroidCommands.GetFilesChanged',
                    side_effect=mockGetFilesChanged)):
    # pylint: enable=C0322
      with self.assertOldImplCallsSequence([
          ("adb -s 0123456789abcdef shell 'pm path this.is.a.test.package'",
           'package:/fake/data/app/this.is.a.test.package.apk\r\n'),
          # GetFilesChanged is mocked, so its adb calls are omitted.
          ('adb -s 0123456789abcdef install -r /fake/test/app.apk',
           'Success\r\n')]):
        self.device.Install('/fake/test/app.apk', reinstall=True, retries=0)

  def testInstall_identicalPriorInstall(self):
    def mockGetFilesChanged(host_path, device_path, ignore_filenames):
      return []

    with mock.patch('pylib.utils.apk_helper.GetPackageName',
                    return_value='this.is.a.test.package'), (
         mock.patch('pylib.android_commands.AndroidCommands.GetFilesChanged',
                    side_effect=mockGetFilesChanged)):
      with self.assertOldImplCallsSequence([
          ("adb -s 0123456789abcdef shell 'pm path this.is.a.test.package'",
           'package:/fake/data/app/this.is.a.test.package.apk\r\n')
          # GetFilesChanged is mocked, so its adb calls are omitted.
          ]):
        self.device.Install('/fake/test/app.apk', retries=0)

  def testInstall_fails(self):
    with mock.patch('os.path.isfile', return_value=True), (
         mock.patch('pylib.utils.apk_helper.GetPackageName',
                    return_value='this.is.a.test.package')):
      with self.assertOldImplCallsSequence([
          ("adb -s 0123456789abcdef shell 'pm path this.is.a.test.package'",
           ''),
          ("adb -s 0123456789abcdef install /fake/test/app.apk",
           'Failure\r\n')]):
        with self.assertRaises(device_errors.CommandFailedError):
          self.device.Install('/fake/test/app.apk', retries=0)

  def testRunShellCommand_commandAsList(self):
    with self.assertOldImplCalls(
        "adb -s 0123456789abcdef shell 'pm list packages'",
        'pacakge:android\r\n'):
      self.device.RunShellCommand(['pm', 'list', 'packages'])

  def testRunShellCommand_commandAsString(self):
    with self.assertOldImplCalls(
        "adb -s 0123456789abcdef shell 'dumpsys wifi'",
        'Wi-Fi is enabled\r\n'):
      self.device.RunShellCommand('dumpsys wifi')

  def testRunShellCommand_withSu(self):
    with self.assertOldImplCallsSequence([
        ("adb -s 0123456789abcdef shell 'ls /root'", 'Permission denied\r\n'),
        ("adb -s 0123456789abcdef shell 'su -c setprop service.adb.root 0'",
         '')]):
      self.device.RunShellCommand('setprop service.adb.root 0', as_root=True)

  def testRunShellCommand_withRoot(self):
    with self.assertOldImplCallsSequence([
        ("adb -s 0123456789abcdef shell 'ls /root'", 'hello\r\nworld\r\n'),
        ("adb -s 0123456789abcdef shell 'setprop service.adb.root 0'", '')]):
      self.device.RunShellCommand('setprop service.adb.root 0', as_root=True)

  def testRunShellCommand_checkReturn_success(self):
    with self.assertOldImplCalls(
        "adb -s 0123456789abcdef shell 'echo $ANDROID_DATA; echo %$?'",
        '/data\r\n%0\r\n'):
      self.device.RunShellCommand('echo $ANDROID_DATA', check_return=True)

  def testRunShellCommand_checkReturn_failure(self):
    with self.assertOldImplCalls(
        "adb -s 0123456789abcdef shell 'echo $ANDROID_DATA; echo %$?'",
        '\r\n%1\r\n'):
      with self.assertRaises(device_errors.CommandFailedError):
        self.device.RunShellCommand('echo $ANDROID_DATA', check_return=True)

  def testKillAll_noMatchingProcesses(self):
    with self.assertOldImplCalls(
        "adb -s 0123456789abcdef shell 'ps'",
        'USER   PID   PPID  VSIZE  RSS   WCHAN    PC       NAME\r\n'):
      with self.assertRaises(device_errors.CommandFailedError):
        self.device.KillAll('test_process')

  def testKillAll_nonblocking(self):
    with self.assertOldImplCallsSequence([
        ("adb -s 0123456789abcdef shell 'ps'",
         'USER   PID   PPID  VSIZE  RSS   WCHAN    PC       NAME\r\n'
         'u0_a1  1234  174   123456 54321 ffffffff 456789ab '
              'this.is.a.test.process\r\n'),
        ("adb -s 0123456789abcdef shell 'ps'",
         'USER   PID   PPID  VSIZE  RSS   WCHAN    PC       NAME\r\n'
         'u0_a1  1234  174   123456 54321 ffffffff 456789ab '
              'this.is.a.test.process\r\n'),
        ("adb -s 0123456789abcdef shell 'kill -9 1234'", '')]):
      self.device.KillAll('this.is.a.test.process', blocking=False)

  def testKillAll_blocking(self):
    with mock.patch('time.sleep'):
      with self.assertOldImplCallsSequence([
          ("adb -s 0123456789abcdef shell 'ps'",
           'USER   PID   PPID  VSIZE  RSS   WCHAN    PC       NAME\r\n'
           'u0_a1  1234  174   123456 54321 ffffffff 456789ab '
                'this.is.a.test.process\r\n'),
          ("adb -s 0123456789abcdef shell 'ps'",
           'USER   PID   PPID  VSIZE  RSS   WCHAN    PC       NAME\r\n'
           'u0_a1  1234  174   123456 54321 ffffffff 456789ab '
                'this.is.a.test.process\r\n'),
          ("adb -s 0123456789abcdef shell 'kill -9 1234'", ''),
          ("adb -s 0123456789abcdef shell 'ps'",
           'USER   PID   PPID  VSIZE  RSS   WCHAN    PC       NAME\r\n'
           'u0_a1  1234  174   123456 54321 ffffffff 456789ab '
                'this.is.a.test.process\r\n'),
          ("adb -s 0123456789abcdef shell 'ps'",
           'USER   PID   PPID  VSIZE  RSS   WCHAN    PC       NAME\r\n')]):
        self.device.KillAll('this.is.a.test.process', blocking=True)

  def testKillAll_root(self):
    with self.assertOldImplCallsSequence([
          ("adb -s 0123456789abcdef shell 'ps'",
           'USER   PID   PPID  VSIZE  RSS   WCHAN    PC       NAME\r\n'
           'u0_a1  1234  174   123456 54321 ffffffff 456789ab '
                'this.is.a.test.process\r\n'),
          ("adb -s 0123456789abcdef shell 'ps'",
           'USER   PID   PPID  VSIZE  RSS   WCHAN    PC       NAME\r\n'
           'u0_a1  1234  174   123456 54321 ffffffff 456789ab '
                'this.is.a.test.process\r\n'),
          ("adb -s 0123456789abcdef shell 'su -c kill -9 1234'", '')]):
      self.device.KillAll('this.is.a.test.process', as_root=True)

  def testKillAll_sigterm(self):
    with self.assertOldImplCallsSequence([
        ("adb -s 0123456789abcdef shell 'ps'",
         'USER   PID   PPID  VSIZE  RSS   WCHAN    PC       NAME\r\n'
         'u0_a1  1234  174   123456 54321 ffffffff 456789ab '
              'this.is.a.test.process\r\n'),
        ("adb -s 0123456789abcdef shell 'ps'",
         'USER   PID   PPID  VSIZE  RSS   WCHAN    PC       NAME\r\n'
         'u0_a1  1234  174   123456 54321 ffffffff 456789ab '
              'this.is.a.test.process\r\n'),
        ("adb -s 0123456789abcdef shell 'kill -15 1234'", '')]):
      self.device.KillAll('this.is.a.test.process', signum=signal.SIGTERM)

  def testStartActivity_actionOnly(self):
    test_intent = intent.Intent(action='android.intent.action.VIEW')
    with self.assertOldImplCalls(
        "adb -s 0123456789abcdef shell 'am start "
            "-a android.intent.action.VIEW'",
        'Starting: Intent { act=android.intent.action.VIEW }'):
      self.device.StartActivity(test_intent)

  def testStartActivity_success(self):
    test_intent = intent.Intent(action='android.intent.action.VIEW',
                                package='this.is.a.test.package',
                                activity='.Main')
    with self.assertOldImplCalls(
        "adb -s 0123456789abcdef shell 'am start "
            "-a android.intent.action.VIEW "
            "-n this.is.a.test.package/.Main'",
        'Starting: Intent { act=android.intent.action.VIEW }'):
      self.device.StartActivity(test_intent)

  def testStartActivity_failure(self):
    test_intent = intent.Intent(action='android.intent.action.VIEW',
                                package='this.is.a.test.package',
                                activity='.Main')
    with self.assertOldImplCalls(
        "adb -s 0123456789abcdef shell 'am start "
            "-a android.intent.action.VIEW "
            "-n this.is.a.test.package/.Main'",
        'Error: Failed to start test activity'):
      with self.assertRaises(device_errors.CommandFailedError):
        self.device.StartActivity(test_intent)

  def testStartActivity_blocking(self):
    test_intent = intent.Intent(action='android.intent.action.VIEW',
                                package='this.is.a.test.package',
                                activity='.Main')
    with self.assertOldImplCalls(
        "adb -s 0123456789abcdef shell 'am start "
            "-a android.intent.action.VIEW "
            "-W "
            "-n this.is.a.test.package/.Main'",
        'Starting: Intent { act=android.intent.action.VIEW }'):
      self.device.StartActivity(test_intent, blocking=True)

  def testStartActivity_withCategory(self):
    test_intent = intent.Intent(action='android.intent.action.VIEW',
                                package='this.is.a.test.package',
                                activity='.Main',
                                category='android.intent.category.HOME')
    with self.assertOldImplCalls(
        "adb -s 0123456789abcdef shell 'am start "
            "-a android.intent.action.VIEW "
            "-c android.intent.category.HOME "
            "-n this.is.a.test.package/.Main'",
        'Starting: Intent { act=android.intent.action.VIEW }'):
      self.device.StartActivity(test_intent)

  def testStartActivity_withMultipleCategories(self):
    # The new implementation will start the activity with all provided
    # categories. The old one only uses the first category.
    test_intent = intent.Intent(action='android.intent.action.VIEW',
                                package='this.is.a.test.package',
                                activity='.Main',
                                category=['android.intent.category.HOME',
                                          'android.intent.category.BROWSABLE'])
    with self.assertOldImplCalls(
        "adb -s 0123456789abcdef shell 'am start "
            "-a android.intent.action.VIEW "
            "-c android.intent.category.HOME "
            "-n this.is.a.test.package/.Main'",
        'Starting: Intent { act=android.intent.action.VIEW }'):
      self.device.StartActivity(test_intent)

  def testStartActivity_withData(self):
    test_intent = intent.Intent(action='android.intent.action.VIEW',
                                package='this.is.a.test.package',
                                activity='.Main',
                                data='http://www.google.com/')
    with self.assertOldImplCalls(
        "adb -s 0123456789abcdef shell 'am start "
            "-a android.intent.action.VIEW "
            "-n this.is.a.test.package/.Main "
            "-d \"http://www.google.com/\"'",
        'Starting: Intent { act=android.intent.action.VIEW }'):
      self.device.StartActivity(test_intent)

  def testStartActivity_withStringExtra(self):
    test_intent = intent.Intent(action='android.intent.action.VIEW',
                                package='this.is.a.test.package',
                                activity='.Main',
                                extras={'foo': 'test'})
    with self.assertOldImplCalls(
        "adb -s 0123456789abcdef shell 'am start "
            "-a android.intent.action.VIEW "
            "-n this.is.a.test.package/.Main "
            "--es foo test'",
        'Starting: Intent { act=android.intent.action.VIEW }'):
      self.device.StartActivity(test_intent)

  def testStartActivity_withBoolExtra(self):
    test_intent = intent.Intent(action='android.intent.action.VIEW',
                                package='this.is.a.test.package',
                                activity='.Main',
                                extras={'foo': True})
    with self.assertOldImplCalls(
        "adb -s 0123456789abcdef shell 'am start "
            "-a android.intent.action.VIEW "
            "-n this.is.a.test.package/.Main "
            "--ez foo True'",
        'Starting: Intent { act=android.intent.action.VIEW }'):
      self.device.StartActivity(test_intent)

  def testStartActivity_withIntExtra(self):
    test_intent = intent.Intent(action='android.intent.action.VIEW',
                                package='this.is.a.test.package',
                                activity='.Main',
                                extras={'foo': 123})
    with self.assertOldImplCalls(
        "adb -s 0123456789abcdef shell 'am start "
            "-a android.intent.action.VIEW "
            "-n this.is.a.test.package/.Main "
            "--ei foo 123'",
        'Starting: Intent { act=android.intent.action.VIEW }'):
      self.device.StartActivity(test_intent)

  def testStartActivity_withTraceFile(self):
    test_intent = intent.Intent(action='android.intent.action.VIEW',
                                package='this.is.a.test.package',
                                activity='.Main')
    with self.assertOldImplCalls(
        "adb -s 0123456789abcdef shell 'am start "
            "-a android.intent.action.VIEW "
            "-n this.is.a.test.package/.Main "
            "--start-profiler test_trace_file.out'",
        'Starting: Intent { act=android.intent.action.VIEW }'):
      self.device.StartActivity(test_intent,
                                trace_file_name='test_trace_file.out')

  def testStartActivity_withForceStop(self):
    test_intent = intent.Intent(action='android.intent.action.VIEW',
                                package='this.is.a.test.package',
                                activity='.Main')
    with self.assertOldImplCalls(
        "adb -s 0123456789abcdef shell 'am start "
            "-a android.intent.action.VIEW "
            "-S "
            "-n this.is.a.test.package/.Main'",
        'Starting: Intent { act=android.intent.action.VIEW }'):
      self.device.StartActivity(test_intent, force_stop=True)

  def testStartActivity_withFlags(self):
    test_intent = intent.Intent(action='android.intent.action.VIEW',
                                package='this.is.a.test.package',
                                activity='.Main',
                                flags='0x10000000')
    with self.assertOldImplCalls(
        "adb -s 0123456789abcdef shell 'am start "
            "-a android.intent.action.VIEW "
            "-n this.is.a.test.package/.Main "
            "-f 0x10000000'",
        'Starting: Intent { act=android.intent.action.VIEW }'):
      self.device.StartActivity(test_intent)

  def testBroadcastIntent_noExtras(self):
    test_intent = intent.Intent(action='test.package.with.an.INTENT')
    with self.assertOldImplCalls(
        "adb -s 0123456789abcdef shell 'am broadcast "
            "-a test.package.with.an.INTENT '",
        'Broadcasting: Intent { act=test.package.with.an.INTENT } '):
      self.device.BroadcastIntent(test_intent)

  def testBroadcastIntent_withExtra(self):
    test_intent = intent.Intent(action='test.package.with.an.INTENT',
                                extras={'foo': 'bar'})
    with self.assertOldImplCalls(
        "adb -s 0123456789abcdef shell 'am broadcast "
            "-a test.package.with.an.INTENT "
            "-e foo \"bar\"'",
        'Broadcasting: Intent { act=test.package.with.an.INTENT } '):
      self.device.BroadcastIntent(test_intent)

  def testBroadcastIntent_withExtra_noValue(self):
    test_intent = intent.Intent(action='test.package.with.an.INTENT',
                                extras={'foo': None})
    with self.assertOldImplCalls(
        "adb -s 0123456789abcdef shell 'am broadcast "
            "-a test.package.with.an.INTENT "
            "-e foo'",
        'Broadcasting: Intent { act=test.package.with.an.INTENT } '):
      self.device.BroadcastIntent(test_intent)

  def testGoHome(self):
    with self.assertOldImplCalls(
        "adb -s 0123456789abcdef shell 'am start "
            "-W "
            "-a android.intent.action.MAIN "
            "-c android.intent.category.HOME'",
        'Starting: Intent { act=android.intent.action.MAIN }\r\n'):
      self.device.GoHome()

  def testForceStop(self):
    with self.assertOldImplCalls(
        "adb -s 0123456789abcdef shell 'am force-stop this.is.a.test.package'",
        ''):
      self.device.ForceStop('this.is.a.test.package')

  def testClearApplicationState_packageExists(self):
    with self.assertOldImplCalls(
        "adb -s 0123456789abcdef shell 'pm path this.package.does.not.exist'",
        ''):
      self.device.ClearApplicationState('this.package.does.not.exist')

  def testClearApplicationState_packageDoesntExist(self):
    with self.assertOldImplCallsSequence([
        ("adb -s 0123456789abcdef shell 'pm path this.package.exists'",
         'package:/data/app/this.package.exists.apk'),
        ("adb -s 0123456789abcdef shell 'pm clear this.package.exists'",
         'Success\r\n')]):
      self.device.ClearApplicationState('this.package.exists')

  def testSendKeyEvent(self):
    with self.assertOldImplCalls(
        "adb -s 0123456789abcdef shell 'input keyevent 66'",
        ''):
      self.device.SendKeyEvent(66)

  def testPushChangedFiles_noHostPath(self):
    with mock.patch('os.path.exists', return_value=False):
      with self.assertRaises(device_errors.CommandFailedError):
        self.device.PushChangedFiles('/test/host/path', '/test/device/path')

  def testPushChangedFiles_file_noChange(self):
    self.device.old_interface._push_if_needed_cache = {}

    host_file_path = '/test/host/path'
    device_file_path = '/test/device/path'

    mock_file_info = {
      '/test/host/path': {
        'os.path.exists': True,
        'os.path.isdir': False,
        'os.path.getsize': 100,
      },
    }

    os_path_exists = mock.Mock()
    os_path_exists.side_effect = lambda f: mock_file_info[f]['os.path.exists']

    os_path_isdir = mock.Mock()
    os_path_isdir.side_effect = lambda f: mock_file_info[f]['os.path.isdir']

    os_path_getsize = mock.Mock()
    os_path_getsize.side_effect = lambda f: mock_file_info[f]['os.path.getsize']

    self.device.old_interface.GetFilesChanged = mock.Mock(return_value=[])

    with mock.patch('os.path.exists', new=os_path_exists), (
         mock.patch('os.path.isdir', new=os_path_isdir)), (
         mock.patch('os.path.getsize', new=os_path_getsize)):
      # GetFilesChanged is mocked, so its adb calls are omitted.
      with self.assertNoAdbCalls():
        self.device.PushChangedFiles(host_file_path, device_file_path)

  @staticmethod
  def createMockOSStatResult(
      st_mode=None, st_ino=None, st_dev=None, st_nlink=None, st_uid=None,
      st_gid=None, st_size=None, st_atime=None, st_mtime=None, st_ctime=None):
    MockOSStatResult = collections.namedtuple('MockOSStatResult', [
        'st_mode', 'st_ino', 'st_dev', 'st_nlink', 'st_uid', 'st_gid',
        'st_size', 'st_atime', 'st_mtime', 'st_ctime'])
    return MockOSStatResult(st_mode, st_ino, st_dev, st_nlink, st_uid, st_gid,
                            st_size, st_atime, st_mtime, st_ctime)

  def testPushChangedFiles_file_changed(self):
    self.device.old_interface._push_if_needed_cache = {}

    host_file_path = '/test/host/path'
    device_file_path = '/test/device/path'

    mock_file_info = {
      '/test/host/path': {
        'os.path.exists': True,
        'os.path.isdir': False,
        'os.path.getsize': 100,
        'os.stat': self.createMockOSStatResult(st_mtime=1000000000)
      },
    }

    os_path_exists = mock.Mock()
    os_path_exists.side_effect = lambda f: mock_file_info[f]['os.path.exists']

    os_path_isdir = mock.Mock()
    os_path_isdir.side_effect = lambda f: mock_file_info[f]['os.path.isdir']

    os_path_getsize = mock.Mock()
    os_path_getsize.side_effect = lambda f: mock_file_info[f]['os.path.getsize']

    os_stat = mock.Mock()
    os_stat.side_effect = lambda f: mock_file_info[f]['os.stat']

    self.device.old_interface.GetFilesChanged = mock.Mock(
        return_value=[('/test/host/path', '/test/device/path')])

    with mock.patch('os.path.exists', new=os_path_exists), (
         mock.patch('os.path.isdir', new=os_path_isdir)), (
         mock.patch('os.path.getsize', new=os_path_getsize)), (
         mock.patch('os.stat', new=os_stat)):
      with self.assertOldImplCalls('adb -s 0123456789abcdef push '
          '/test/host/path /test/device/path', '100 B/s (100 B in 1.000s)\r\n'):
        self.device.PushChangedFiles(host_file_path, device_file_path)

  def testPushChangedFiles_directory_nothingChanged(self):
    self.device.old_interface._push_if_needed_cache = {}

    host_file_path = '/test/host/path'
    device_file_path = '/test/device/path'

    mock_file_info = {
      '/test/host/path': {
        'os.path.exists': True,
        'os.path.isdir': True,
        'os.path.getsize': 256,
        'os.stat': self.createMockOSStatResult(st_mtime=1000000000)
      },
      '/test/host/path/file1': {
        'os.path.exists': True,
        'os.path.isdir': False,
        'os.path.getsize': 251,
        'os.stat': self.createMockOSStatResult(st_mtime=1000000001)
      },
      '/test/host/path/file2': {
        'os.path.exists': True,
        'os.path.isdir': False,
        'os.path.getsize': 252,
        'os.stat': self.createMockOSStatResult(st_mtime=1000000002)
      },
    }

    os_path_exists = mock.Mock()
    os_path_exists.side_effect = lambda f: mock_file_info[f]['os.path.exists']

    os_path_isdir = mock.Mock()
    os_path_isdir.side_effect = lambda f: mock_file_info[f]['os.path.isdir']

    os_path_getsize = mock.Mock()
    os_path_getsize.side_effect = lambda f: mock_file_info[f]['os.path.getsize']

    os_stat = mock.Mock()
    os_stat.side_effect = lambda f: mock_file_info[f]['os.stat']

    self.device.old_interface.GetFilesChanged = mock.Mock(return_value=[])

    with mock.patch('os.path.exists', new=os_path_exists), (
         mock.patch('os.path.isdir', new=os_path_isdir)), (
         mock.patch('os.path.getsize', new=os_path_getsize)), (
         mock.patch('os.stat', new=os_stat)):
      with self.assertOldImplCallsSequence([
          ("adb -s 0123456789abcdef shell 'mkdir -p \"/test/device/path\"'",
           '')]):
        self.device.PushChangedFiles(host_file_path, device_file_path)

  def testPushChangedFiles_directory_somethingChanged(self):
    self.device.old_interface._push_if_needed_cache = {}

    host_file_path = '/test/host/path'
    device_file_path = '/test/device/path'

    mock_file_info = {
      '/test/host/path': {
        'os.path.exists': True,
        'os.path.isdir': True,
        'os.path.getsize': 256,
        'os.stat': self.createMockOSStatResult(st_mtime=1000000000),
        'os.walk': [('/test/host/path', [], ['file1', 'file2'])]
      },
      '/test/host/path/file1': {
        'os.path.exists': True,
        'os.path.isdir': False,
        'os.path.getsize': 256,
        'os.stat': self.createMockOSStatResult(st_mtime=1000000001)
      },
      '/test/host/path/file2': {
        'os.path.exists': True,
        'os.path.isdir': False,
        'os.path.getsize': 256,
        'os.stat': self.createMockOSStatResult(st_mtime=1000000002)
      },
    }

    os_path_exists = mock.Mock()
    os_path_exists.side_effect = lambda f: mock_file_info[f]['os.path.exists']

    os_path_isdir = mock.Mock()
    os_path_isdir.side_effect = lambda f: mock_file_info[f]['os.path.isdir']

    os_path_getsize = mock.Mock()
    os_path_getsize.side_effect = lambda f: mock_file_info[f]['os.path.getsize']

    os_stat = mock.Mock()
    os_stat.side_effect = lambda f: mock_file_info[f]['os.stat']

    os_walk = mock.Mock()
    os_walk.side_effect = lambda f: mock_file_info[f]['os.walk']

    self.device.old_interface.GetFilesChanged = mock.Mock(
        return_value=[('/test/host/path/file1', '/test/device/path/file1')])

    with mock.patch('os.path.exists', new=os_path_exists), (
         mock.patch('os.path.isdir', new=os_path_isdir)), (
         mock.patch('os.path.getsize', new=os_path_getsize)), (
         mock.patch('os.stat', new=os_stat)), (
         mock.patch('os.walk', new=os_walk)):
      with self.assertOldImplCallsSequence([
          ("adb -s 0123456789abcdef shell 'mkdir -p \"/test/device/path\"'",
           ''),
          ('adb -s 0123456789abcdef push '
              '/test/host/path/file1 /test/device/path/file1',
           '256 B/s (256 B in 1.000s)\r\n')]):
        self.device.PushChangedFiles(host_file_path, device_file_path)

  def testPushChangedFiles_directory_everythingChanged(self):
    self.device.old_interface._push_if_needed_cache = {}

    host_file_path = '/test/host/path'
    device_file_path = '/test/device/path'

    mock_file_info = {
      '/test/host/path': {
        'os.path.exists': True,
        'os.path.isdir': True,
        'os.path.getsize': 256,
        'os.stat': self.createMockOSStatResult(st_mtime=1000000000)
      },
      '/test/host/path/file1': {
        'os.path.exists': True,
        'os.path.isdir': False,
        'os.path.getsize': 256,
        'os.stat': self.createMockOSStatResult(st_mtime=1000000001)
      },
      '/test/host/path/file2': {
        'os.path.exists': True,
        'os.path.isdir': False,
        'os.path.getsize': 256,
        'os.stat': self.createMockOSStatResult(st_mtime=1000000002)
      },
    }

    os_path_exists = mock.Mock()
    os_path_exists.side_effect = lambda f: mock_file_info[f]['os.path.exists']

    os_path_isdir = mock.Mock()
    os_path_isdir.side_effect = lambda f: mock_file_info[f]['os.path.isdir']

    os_path_getsize = mock.Mock()
    os_path_getsize.side_effect = lambda f: mock_file_info[f]['os.path.getsize']

    os_stat = mock.Mock()
    os_stat.side_effect = lambda f: mock_file_info[f]['os.stat']

    self.device.old_interface.GetFilesChanged = mock.Mock(
        return_value=[('/test/host/path/file1', '/test/device/path/file1'),
                      ('/test/host/path/file2', '/test/device/path/file2')])

    with mock.patch('os.path.exists', new=os_path_exists), (
         mock.patch('os.path.isdir', new=os_path_isdir)), (
         mock.patch('os.path.getsize', new=os_path_getsize)), (
         mock.patch('os.stat', new=os_stat)):
      with self.assertOldImplCallsSequence([
          ("adb -s 0123456789abcdef shell 'mkdir -p \"/test/device/path\"'",
           ''),
          ('adb -s 0123456789abcdef push /test/host/path /test/device/path',
           '768 B/s (768 B in 1.000s)\r\n')]):
        self.device.PushChangedFiles(host_file_path, device_file_path)

  def testFileExists_usingTest_fileExists(self):
    with self.assertOldImplCalls(
        "adb -s 0123456789abcdef shell "
            "'test -e \"/data/app/test.file.exists\"; echo $?'",
        '0\r\n'):
      self.assertTrue(self.device.FileExists('/data/app/test.file.exists'))

  def testFileExists_usingTest_fileDoesntExist(self):
    with self.assertOldImplCalls(
        "adb -s 0123456789abcdef shell "
            "'test -e \"/data/app/test.file.does.not.exist\"; echo $?'",
        '1\r\n'):
      self.assertFalse(self.device.FileExists(
          '/data/app/test.file.does.not.exist'))

  def testFileExists_usingLs_fileExists(self):
    with self.assertOldImplCallsSequence([
        ("adb -s 0123456789abcdef shell "
            "'test -e \"/data/app/test.file.exists\"; echo $?'",
         'test: not found\r\n'),
        ("adb -s 0123456789abcdef shell "
            "'ls \"/data/app/test.file.exists\" >/dev/null 2>&1; echo $?'",
         '0\r\n')]):
      self.assertTrue(self.device.FileExists('/data/app/test.file.exists'))

  def testFileExists_usingLs_fileDoesntExist(self):
    with self.assertOldImplCallsSequence([
        ("adb -s 0123456789abcdef shell "
            "'test -e \"/data/app/test.file.does.not.exist\"; echo $?'",
         'test: not found\r\n'),
        ("adb -s 0123456789abcdef shell "
            "'ls \"/data/app/test.file.does.not.exist\" "
            ">/dev/null 2>&1; echo $?'",
         '1\r\n')]):
      self.assertFalse(self.device.FileExists(
          '/data/app/test.file.does.not.exist'))

  def testPullFile_existsOnDevice(self):
    with mock.patch('os.path.exists', return_value=True):
      with self.assertOldImplCallsSequence([
          ('adb -s 0123456789abcdef shell '
              'ls /data/app/test.file.exists',
           '/data/app/test.file.exists'),
          ('adb -s 0123456789abcdef pull '
              '/data/app/test.file.exists /test/file/host/path',
           '100 B/s (100 bytes in 1.000s)\r\n')]):
        self.device.PullFile('/data/app/test.file.exists',
                             '/test/file/host/path')

  def testPullFile_doesntExistOnDevice(self):
    with mock.patch('os.path.exists', return_value=True):
      with self.assertOldImplCalls(
          'adb -s 0123456789abcdef shell '
              'ls /data/app/test.file.does.not.exist',
          '/data/app/test.file.does.not.exist: No such file or directory\r\n'):
        with self.assertRaises(device_errors.CommandFailedError):
          self.device.PullFile('/data/app/test.file.does.not.exist',
                               '/test/file/host/path')

  def testReadFile_exists(self):
    with self.assertOldImplCallsSequence([
        ("adb -s 0123456789abcdef shell "
            "'cat \"/read/this/test/file\" 2>/dev/null'",
         'this is a test file')]):
      self.assertEqual(['this is a test file'],
                       self.device.ReadFile('/read/this/test/file'))

  def testReadFile_doesNotExist(self):
    with self.assertOldImplCalls(
        "adb -s 0123456789abcdef shell "
            "'cat \"/this/file/does.not.exist\" 2>/dev/null'",
         ''):
      self.device.ReadFile('/this/file/does.not.exist')

  def testReadFile_asRoot_withRoot(self):
    self.device.old_interface._privileged_command_runner = (
        self.device.old_interface.RunShellCommand)
    self.device.old_interface._protected_file_access_method_initialized = True
    with self.assertOldImplCallsSequence([
        ("adb -s 0123456789abcdef shell "
            "'cat \"/this/file/must.be.read.by.root\" 2> /dev/null'",
         'this is a test file\nread by root')]):
      self.assertEqual(
          ['this is a test file', 'read by root'],
          self.device.ReadFile('/this/file/must.be.read.by.root',
                               as_root=True))

  def testReadFile_asRoot_withSu(self):
    self.device.old_interface._privileged_command_runner = (
        self.device.old_interface.RunShellCommandWithSU)
    self.device.old_interface._protected_file_access_method_initialized = True
    with self.assertOldImplCallsSequence([
        ("adb -s 0123456789abcdef shell "
            "'su -c cat \"/this/file/can.be.read.with.su\" 2> /dev/null'",
         'this is a test file\nread with su')]):
      self.assertEqual(
          ['this is a test file', 'read with su'],
          self.device.ReadFile('/this/file/can.be.read.with.su',
                               as_root=True))

  def testReadFile_asRoot_rejected(self):
    self.device.old_interface._privileged_command_runner = None
    self.device.old_interface._protected_file_access_method_initialized = True
    with self.assertRaises(device_errors.CommandFailedError):
      self.device.ReadFile('/this/file/cannot.be.read.by.user',
                           as_root=True)

  def testWriteFile_basic(self):
    mock_file = mock.MagicMock(spec=file)
    mock_file.name = '/tmp/file/to.be.pushed'
    mock_file.__enter__.return_value = mock_file
    with mock.patch('tempfile.NamedTemporaryFile',
                    return_value=mock_file):
      with self.assertOldImplCalls(
          'adb -s 0123456789abcdef push '
              '/tmp/file/to.be.pushed /test/file/written.to.device',
          '100 B/s (100 bytes in 1.000s)\r\n'):
        self.device.WriteFile('/test/file/written.to.device',
                              'new test file contents')
    mock_file.write.assert_called_once_with('new test file contents')

  def testWriteFile_asRoot_withRoot(self):
    self.device.old_interface._external_storage = '/fake/storage/path'
    self.device.old_interface._privileged_command_runner = (
        self.device.old_interface.RunShellCommand)
    self.device.old_interface._protected_file_access_method_initialized = True

    mock_file = mock.MagicMock(spec=file)
    mock_file.name = '/tmp/file/to.be.pushed'
    mock_file.__enter__.return_value = mock_file
    with mock.patch('tempfile.NamedTemporaryFile',
                    return_value=mock_file):
      with self.assertOldImplCallsSequence(
          cmd_ret=[
              # Create temporary contents file
              (r"adb -s 0123456789abcdef shell "
                  "'test -e \"/fake/storage/path/temp_file-\d+-\d+\"; "
                  "echo \$\?'",
               '1\r\n'),
              # Create temporary script file
              (r"adb -s 0123456789abcdef shell "
                  "'test -e \"/fake/storage/path/temp_file-\d+-\d+\.sh\"; "
                  "echo \$\?'",
               '1\r\n'),
              # Set contents file
              (r'adb -s 0123456789abcdef push /tmp/file/to\.be\.pushed '
                  '/fake/storage/path/temp_file-\d+\d+',
               '100 B/s (100 bytes in 1.000s)\r\n'),
              # Set script file
              (r'adb -s 0123456789abcdef push /tmp/file/to\.be\.pushed '
                  '/fake/storage/path/temp_file-\d+\d+',
               '100 B/s (100 bytes in 1.000s)\r\n'),
              # Call script
              (r"adb -s 0123456789abcdef shell "
                  "'sh /fake/storage/path/temp_file-\d+-\d+\.sh'", ''),
              # Remove device temporaries
              (r"adb -s 0123456789abcdef shell "
                  "'rm /fake/storage/path/temp_file-\d+-\d+\.sh'", ''),
              (r"adb -s 0123456789abcdef shell "
                  "'rm /fake/storage/path/temp_file-\d+-\d+'", '')],
          comp=re.match):
        self.device.WriteFile('/test/file/written.to.device',
                              'new test file contents', as_root=True)

  def testWriteFile_asRoot_withSu(self):
    self.device.old_interface._external_storage = '/fake/storage/path'
    self.device.old_interface._privileged_command_runner = (
        self.device.old_interface.RunShellCommandWithSU)
    self.device.old_interface._protected_file_access_method_initialized = True

    mock_file = mock.MagicMock(spec=file)
    mock_file.name = '/tmp/file/to.be.pushed'
    mock_file.__enter__.return_value = mock_file
    with mock.patch('tempfile.NamedTemporaryFile',
                    return_value=mock_file):
      with self.assertOldImplCallsSequence(
          cmd_ret=[
              # Create temporary contents file
              (r"adb -s 0123456789abcdef shell "
                  "'test -e \"/fake/storage/path/temp_file-\d+-\d+\"; "
                  "echo \$\?'",
               '1\r\n'),
              # Create temporary script file
              (r"adb -s 0123456789abcdef shell "
                  "'test -e \"/fake/storage/path/temp_file-\d+-\d+\.sh\"; "
                  "echo \$\?'",
               '1\r\n'),
              # Set contents file
              (r'adb -s 0123456789abcdef push /tmp/file/to\.be\.pushed '
                  '/fake/storage/path/temp_file-\d+\d+',
               '100 B/s (100 bytes in 1.000s)\r\n'),
              # Set script file
              (r'adb -s 0123456789abcdef push /tmp/file/to\.be\.pushed '
                  '/fake/storage/path/temp_file-\d+\d+',
               '100 B/s (100 bytes in 1.000s)\r\n'),
              # Call script
              (r"adb -s 0123456789abcdef shell "
                  "'su -c sh /fake/storage/path/temp_file-\d+-\d+\.sh'", ''),
              # Remove device temporaries
              (r"adb -s 0123456789abcdef shell "
                  "'rm /fake/storage/path/temp_file-\d+-\d+\.sh'", ''),
              (r"adb -s 0123456789abcdef shell "
                  "'rm /fake/storage/path/temp_file-\d+-\d+'", '')],
          comp=re.match):
        self.device.WriteFile('/test/file/written.to.device',
                              'new test file contents', as_root=True)

  def testWriteFile_asRoot_rejected(self):
    self.device.old_interface._privileged_command_runner = None
    self.device.old_interface._protected_file_access_method_initialized = True
    with self.assertRaises(device_errors.CommandFailedError):
      self.device.WriteFile('/test/file/no.permissions.to.write',
                            'new test file contents', as_root=True)

  def testLs_nothing(self):
    with self.assertOldImplCallsSequence([
        ("adb -s 0123456789abcdef shell 'ls -lR /this/file/does.not.exist'",
         '/this/file/does.not.exist: No such file or directory\r\n'),
        ("adb -s 0123456789abcdef shell 'date +%z'", '+0000')]):
      self.assertEqual({}, self.device.Ls('/this/file/does.not.exist'))

  def testLs_file(self):
    with self.assertOldImplCallsSequence([
        ("adb -s 0123456789abcdef shell 'ls -lR /this/is/a/test.file'",
         '-rw-rw---- testuser testgroup 4096 1970-01-01 00:00 test.file\r\n'),
        ("adb -s 0123456789abcdef shell 'date +%z'", '+0000')]):
      self.assertEqual(
          {'test.file': (4096, datetime.datetime(1970, 1, 1))},
          self.device.Ls('/this/is/a/test.file'))

  def testLs_directory(self):
    with self.assertOldImplCallsSequence([
        ("adb -s 0123456789abcdef shell 'ls -lR /this/is/a/test.directory'",
         '\r\n'
         '/this/is/a/test.directory:\r\n'
         '-rw-rw---- testuser testgroup 4096 1970-01-01 18:19 test.file\r\n'),
        ("adb -s 0123456789abcdef shell 'date +%z'", '+0000')]):
      self.assertEqual(
          {'test.file': (4096, datetime.datetime(1970, 1, 1, 18, 19))},
          self.device.Ls('/this/is/a/test.directory'))

  def testLs_directories(self):
    with self.assertOldImplCallsSequence([
        ("adb -s 0123456789abcdef shell 'ls -lR /this/is/a/test.directory'",
         '\r\n'
         '/this/is/a/test.directory:\r\n'
         'drwxr-xr-x testuser testgroup 1970-01-01 00:00 test.subdirectory\r\n'
         '\r\n'
         '/this/is/a/test.directory/test.subdirectory:\r\n'
         '-rw-rw---- testuser testgroup 4096 1970-01-01 00:00 test.file\r\n'),
        ("adb -s 0123456789abcdef shell 'date +%z'", '-0700')]):
      self.assertEqual(
          {'test.subdirectory/test.file':
              (4096, datetime.datetime(1970, 1, 1, 7, 0, 0))},
          self.device.Ls('/this/is/a/test.directory'))

  @staticmethod
  def mockNamedTemporary(name='/tmp/file/property.file',
                         read_contents=''):
    mock_file = mock.MagicMock(spec=file)
    mock_file.name = name
    mock_file.__enter__.return_value = mock_file
    mock_file.read.return_value = read_contents
    return mock_file

  def testSetJavaAsserts_enable(self):
    mock_file = self.mockNamedTemporary()
    with mock.patch('tempfile.NamedTemporaryFile',
                    return_value=mock_file), (
         mock.patch('__builtin__.open', return_value=mock_file)):
      with self.assertOldImplCallsSequence(
          [('adb -s 0123456789abcdef shell ls %s' %
                constants.DEVICE_LOCAL_PROPERTIES_PATH,
            '%s\r\n' % constants.DEVICE_LOCAL_PROPERTIES_PATH),
           ('adb -s 0123456789abcdef pull %s %s' %
                (constants.DEVICE_LOCAL_PROPERTIES_PATH, mock_file.name),
            '100 B/s (100 bytes in 1.000s)\r\n'),
           ('adb -s 0123456789abcdef push %s %s' %
                (mock_file.name, constants.DEVICE_LOCAL_PROPERTIES_PATH),
            '100 B/s (100 bytes in 1.000s)\r\n'),
           ('adb -s 0123456789abcdef shell '
                'getprop dalvik.vm.enableassertions',
            '\r\n'),
           ('adb -s 0123456789abcdef shell '
                'setprop dalvik.vm.enableassertions "all"',
            '')]):
        self.device.SetJavaAsserts(True)

  def testSetJavaAsserts_disable(self):
    mock_file = self.mockNamedTemporary(
        read_contents='dalvik.vm.enableassertions=all\n')
    with mock.patch('tempfile.NamedTemporaryFile',
                    return_value=mock_file), (
         mock.patch('__builtin__.open', return_value=mock_file)):
      with self.assertOldImplCallsSequence(
          [('adb -s 0123456789abcdef shell ls %s' %
                constants.DEVICE_LOCAL_PROPERTIES_PATH,
            '%s\r\n' % constants.DEVICE_LOCAL_PROPERTIES_PATH),
           ('adb -s 0123456789abcdef pull %s %s' %
                (constants.DEVICE_LOCAL_PROPERTIES_PATH, mock_file.name),
            '100 B/s (100 bytes in 1.000s)\r\n'),
           ('adb -s 0123456789abcdef push %s %s' %
                (mock_file.name, constants.DEVICE_LOCAL_PROPERTIES_PATH),
            '100 B/s (100 bytes in 1.000s)\r\n'),
           ('adb -s 0123456789abcdef shell '
                'getprop dalvik.vm.enableassertions',
            'all\r\n'),
           ('adb -s 0123456789abcdef shell '
                'setprop dalvik.vm.enableassertions ""',
            '')]):
        self.device.SetJavaAsserts(False)

  def testSetJavaAsserts_alreadyEnabled(self):
    mock_file = self.mockNamedTemporary(
        read_contents='dalvik.vm.enableassertions=all\n')
    with mock.patch('tempfile.NamedTemporaryFile',
                    return_value=mock_file), (
         mock.patch('__builtin__.open', return_value=mock_file)):
      with self.assertOldImplCallsSequence(
          [('adb -s 0123456789abcdef shell ls %s' %
                constants.DEVICE_LOCAL_PROPERTIES_PATH,
            '%s\r\n' % constants.DEVICE_LOCAL_PROPERTIES_PATH),
           ('adb -s 0123456789abcdef pull %s %s' %
                (constants.DEVICE_LOCAL_PROPERTIES_PATH, mock_file.name),
            '100 B/s (100 bytes in 1.000s)\r\n'),
           ('adb -s 0123456789abcdef shell '
                'getprop dalvik.vm.enableassertions',
            'all\r\n')]):
        self.assertFalse(self.device.SetJavaAsserts(True))

  def testGetProp_exists(self):
    with self.assertOldImplCalls(
        'adb -s 0123456789abcdef shell getprop this.is.a.test.property',
        'test_property_value\r\n'):
      self.assertEqual('test_property_value',
                       self.device.GetProp('this.is.a.test.property'))

  def testGetProp_doesNotExist(self):
    with self.assertOldImplCalls(
        'adb -s 0123456789abcdef shell '
            'getprop this.property.does.not.exist', ''):
      self.assertEqual('', self.device.GetProp('this.property.does.not.exist'))

  def testGetProp_cachedRoProp(self):
    with self.assertOldImplCalls(
        'adb -s 0123456789abcdef shell '
            'getprop ro.build.type', 'userdebug'):
      self.assertEqual('userdebug', self.device.GetProp('ro.build.type'))
      self.assertEqual('userdebug', self.device.GetProp('ro.build.type'))

  def testSetProp(self):
    with self.assertOldImplCalls(
        'adb -s 0123456789abcdef shell '
            'setprop this.is.a.test.property "test_property_value"',
        ''):
      self.device.SetProp('this.is.a.test.property', 'test_property_value')


if __name__ == '__main__':
  logging.getLogger().setLevel(logging.DEBUG)
  unittest.main(verbosity=2)

