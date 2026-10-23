#!/usr/bin/env python3
"""Exercise guided choices without packages, libvirt, viewers or real guests."""

import json
import os
import pty
import select
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

MENU = Path(__file__).resolve().parents[1] / 'lib/menu.sh'
FAKE_CLI = r'''#!/usr/bin/env bash
set -Eeuo pipefail
"$QVM_TEST_PYTHON" -c '
import json
import os
import sys
with open(os.environ["QVM_MENU_LOG"], "a") as stream:
  stream.write(json.dumps(sys.argv[1:]) + "\n")
' "$@"
printf 'fixture raw command details\n'
if [[ "${QVM_MENU_FAIL:-}" == preview && "$*" != *--execute* ]]; then
  printf 'Error: fixture preview failure\n' >&2
  exit 19
fi
if [[ "${QVM_MENU_FAIL:-}" == execute && "$1" == create &&
  "$*" == *--execute* ]]; then
  printf 'Error: fixture creation failure\n' >&2
  exit 20
fi
'''


class GuidedMenuTests(unittest.TestCase):
  def setUp(self):
    self.temp = tempfile.TemporaryDirectory(prefix='qemu-menu-test-')
    self.addCleanup(self.temp.cleanup)
    self.base = Path(self.temp.name)
    self.cli = self.base / 'fake-cli.sh'
    self.cli.write_text(FAKE_CLI)
    self.log = self.base / 'commands.jsonl'
    self.iso = self.base / '''installer with spaces & 'quotes'.iso'''
    self.iso.write_bytes(b'fixture installer\n')
    self.env = dict(os.environ, QVM_TEST_PYTHON=sys.executable,
                    QVM_MENU_LOG=str(self.log))

  def run_helper(self, helper, lines, **environment):
    return subprocess.run(
      ['bash', '-c', 'set -Eeuo pipefail; source "$1"; "$3" "$2"',
       'menu-test', str(MENU), str(self.cli), helper],
      input='\n'.join(lines) + ('\n' if lines else ''),
      text=True, capture_output=True, check=False,
      cwd=self.base,
      env=dict(self.env, **environment),
    )

  def commands(self):
    if not self.log.exists():
      return []
    return [json.loads(line) for line in self.log.read_text().splitlines()]

  def creation_answers(self, confirm='y', connect='n'):
    return ['', '', f'"{self.iso}"', 'NewGuest', '', '', '',
            'n', confirm, connect]

  def assert_success(self, result):
    self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

  def test_creation_previews_then_applies_then_connects(self):
    result = self.run_helper('menu_create', self.creation_answers(connect='y'))
    self.assert_success(result)
    preview, network_preview, network, create, connect = self.commands()
    self.assertNotIn('--execute', preview)
    self.assertEqual(create, [*preview, '--execute'])
    self.assertEqual(preview[preview.index('--iso') + 1], str(self.iso))
    self.assertEqual(preview[preview.index('--name') + 1], 'NewGuest')
    self.assertIn('--no-start', preview)
    self.assertNotIn('--setup', preview)
    self.assertEqual(network_preview, ['network-start'])
    self.assertEqual(network, ['network-start', '--execute'])
    self.assertEqual(connect, ['connect', '--name', 'NewGuest', '--execute'])

  def test_declining_creation_only_previews(self):
    result = self.run_helper('menu_create', self.creation_answers(confirm='n'))
    self.assert_success(result)
    self.assertEqual(len(self.commands()), 2)
    self.assertNotIn('--execute', self.commands()[0])
    self.assertIn('Creation cancelled', result.stdout)
    self.assertIn('Ready to create:', result.stdout)
    self.assertNotIn('fixture raw command details', result.stdout)

  def test_eof_at_creation_confirmation_never_applies(self):
    result = self.run_helper('menu_create', self.creation_answers()[:8])
    self.assert_success(result)
    self.assertEqual(len(self.commands()), 2)
    self.assertNotIn('--execute', self.commands()[0])

  def test_preview_failure_never_offers_creation(self):
    result = self.run_helper('menu_create', self.creation_answers(),
                             QVM_MENU_FAIL='preview')
    self.assert_success(result)
    self.assertEqual(len(self.commands()), 1)
    self.assertNotIn('create this VM now?', result.stdout)
    self.assertIn('Returning to the menu', result.stderr)

  def test_creation_failure_never_connects(self):
    result = self.run_helper('menu_create', self.creation_answers(connect='y'),
                             QVM_MENU_FAIL='execute')
    self.assert_success(result)
    self.assertEqual(len(self.commands()), 4)
    self.assertNotIn('Start the VM', result.stdout)

  def test_path_text_is_never_evaluated(self):
    literal = self.base / 'installer $(touch unwanted).iso'
    literal.write_bytes(b'fixture installer\n')
    answers = self.creation_answers(confirm='n')
    answers[2] = str(literal)
    result = self.run_helper('menu_create', answers)
    self.assert_success(result)
    preview = self.commands()[0]
    self.assertEqual(preview[preview.index('--iso') + 1], str(literal))
    self.assertFalse((self.base / 'unwanted').exists())

  def test_windows_cannot_select_arch_installer(self):
    result = self.run_helper('menu_create', ['2', '2'])
    self.assert_success(result)
    self.assertEqual(self.commands(), [])
    self.assertIn('requires choosing Linux', result.stderr)

  def test_network_setup_requires_explicit_yes(self):
    result = self.run_helper('menu_network', ['n'])
    self.assert_success(result)
    self.assertEqual(self.commands(), [['network-start']])
    self.log.unlink()
    result = self.run_helper('menu_network', ['yes'])
    self.assert_success(result)
    self.assertEqual(self.commands(),
                     [['network-start'], ['network-start', '--execute']])

  def fake_guest_query(self):
    tools = self.base / 'bin'
    tools.mkdir()
    sudo = tools / 'sudo'
    sudo.write_text('''#!/usr/bin/env bash
if [[ "$1" == -- ]]; then shift; fi
exec "$@"
''')
    virsh = tools / 'virsh'
    virsh.write_text('''#!/usr/bin/env bash
printf '%s\n' "$QVM_MENU_GUESTS"
''')
    for tool in (sudo, virsh):
      tool.chmod(0o755)
    return str(tools) + os.pathsep + self.env['PATH']

  def test_existing_guest_selection_opens_selected_display(self):
    result = self.run_helper('menu_connect', ['2', 'y'],
                             PATH=self.fake_guest_query(),
                             QVM_MENU_GUESTS='FirstGuest\nSecondGuest')
    self.assert_success(result)
    self.assertEqual(self.commands(),
                     [['connect', '--name', 'SecondGuest', '--execute']])

  def test_empty_guest_list_explains_creation_is_needed(self):
    result = self.run_helper('menu_connect', [],
                             PATH=self.fake_guest_query(), QVM_MENU_GUESTS='')
    self.assert_success(result)
    self.assertEqual(self.commands(), [])
    self.assertIn('No VM is registered', result.stdout)

  def test_external_child_keeps_errexit_inside_conditional(self):
    marker = self.base / 'unsafe-continuation'
    self.cli.write_text('''#!/usr/bin/env bash
set -Eeuo pipefail
false
touch -- "$QVM_TEST_MARKER"
''')
    result = self.run_helper('menu_run_command', [],
                             QVM_TEST_MARKER=str(marker))
    self.assertNotEqual(result.returncode, 0)
    self.assertFalse(marker.exists())

  def test_explicit_menu_requires_a_terminal(self):
    result = self.run_helper('interactive_menu', [])
    self.assertNotEqual(result.returncode, 0)
    self.assertIn('needs an interactive terminal', result.stderr)

  def test_terminal_menu_returns_after_failed_action(self):
    master, slave = pty.openpty()
    self.addCleanup(os.close, master)
    process = subprocess.Popen(
      ['bash', '-c', ('set -Eeuo pipefail; source "$1"; '
                     'interactive_menu "$2"'),
       'menu-test', str(MENU), str(self.cli)],
      stdin=slave, stdout=slave, stderr=slave,
      env=dict(self.env, QVM_MENU_FAIL='preview'), close_fds=True,
    )
    os.close(slave)
    self.addCleanup(lambda: process.kill() if process.poll() is None else None)
    os.write(master, b'3\n0\n')
    output = bytearray()
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
      readable, _, _ = select.select([master], [], [], 0.1)
      if readable:
        try:
          output.extend(os.read(master, 65536))
        except OSError:
          break
      elif process.poll() is not None:
        break
    process.wait(timeout=2)
    self.assertEqual(process.returncode, 0, output.decode(errors='replace'))
    self.assertEqual(self.commands(), [['doctor']])
    self.assertIn(b'Returning to the menu', output)
    self.assertGreaterEqual(output.count(b'Choose [0]:'), 2)


if __name__ == '__main__':
  unittest.main()
