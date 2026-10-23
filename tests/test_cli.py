#!/usr/bin/env python3
"""Offline CLI/safety checks. Libvirt, downloads and firmware are simulated.

Run: python3 -m unittest discover -s tests -v
The real qemu-img checks a disposable sparse qcow2 image when available.
No sudo authentication, package installation, services, or real VMs are used.
"""

import hashlib
import json
import os
import shutil
import stat
import subprocess
import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / 'qemu-vm.sh'
REAL_QEMU_IMG = shutil.which('qemu-img')
DOWNLOAD_BYTES = b'fixture downloaded installation ISO\n'
DOWNLOAD_SHA256 = hashlib.sha256(DOWNLOAD_BYTES).hexdigest()
ARCH_VERSION = '2026.10.01'
ARCH_RELEASES_URL = 'https://archlinux.org/releng/releases/json/'
ARCH_ISO_URL = (
  f'https://geo.mirror.pkgbuild.com/iso/{ARCH_VERSION}/'
  f'archlinux-{ARCH_VERSION}-x86_64.iso'
)
INSTALLER_URL = 'https://example.invalid/installer.iso?download=1&edition=lab'
RUNNER = r'''
source "$1"
shift
function ensure_kvm() { :; }
function check_host() { :; }
main "$@"
'''

DISPATCHER = r'''#!/usr/bin/env python3
import hashlib
import json
import os
from pathlib import Path
import shlex
import sys
import uuid
import xml.etree.ElementTree as ET

tool = Path(sys.argv[0]).name
args = sys.argv[1:]
state = Path(os.environ['QVM_STATE_DIR'])
with open(os.environ['QVM_LOG'], 'a') as stream:
  stream.write(json.dumps({'tool': tool, 'args': args}) + '\n')

if os.environ.get('QVM_FAIL_TOOL') == tool:
  raise SystemExit('Simulated failure: ' + tool)

def options(value):
  lexer = shlex.shlex(value, posix=True)
  lexer.whitespace = ','
  lexer.whitespace_split = True
  lexer.commenters = ''
  return dict(item.split('=', 1) if '=' in item else (item, '')
              for item in lexer)

def argument(key):
  return args[args.index(key) + 1]

if tool == 'sudo':
  if args[0] == '--':
    args.pop(0)
  os.execvp(args[0], args)
elif tool == 'qemu-img':
  os.execv(os.environ['QVM_REAL_QEMU_IMG'], ['qemu-img', *args])
elif tool == 'pacman':
  pass
elif tool == 'curl':
  destination = Path(argument('--output'))
  url = args[-1]
  metadata = url == 'https://archlinux.org/releng/releases/json/'
  kind = 'metadata' if metadata else 'iso'
  content = b'fixture downloaded installation ISO\n'
  if os.environ.get('QVM_CURL_FAIL') == kind:
    destination.write_bytes(b'partial transfer\n')
    print('Simulated curl transfer failure', file=sys.stderr)
    raise SystemExit(22)
  if os.environ.get('QVM_CURL_EMPTY') == kind:
    destination.write_bytes(b'')
  elif metadata:
    version = '2026.10.01'
    prefix = '/iso/'
    release = {
      'version': version,
      'available': True,
      'release_date': '2026-10-01',
      'iso_url': prefix + version + '/archlinux-' + version + '-x86_64.iso',
      'sha256_sum': hashlib.sha256(content).hexdigest(),
    }
    # The latest entry is deliberately not first: select latest_version's entry.
    older = dict(release, version='2026.09.01', sha256_sum='0' * 64,
                 iso_url=prefix + '2026.09.01/archlinux-2026.09.01-x86_64.iso')
    payload = {'version': 1, 'latest_version': version,
               'releases': [older, release]}
    invalid = os.environ.get('QVM_ARCH_BAD_METADATA', '')
    if invalid == 'wrong-schema':
      payload['version'] = 2
    elif invalid == 'missing-latest':
      del payload['latest_version']
    elif invalid == 'missing-release':
      payload['latest_version'] = '2026.10.02'
    elif invalid == 'unavailable':
      release['available'] = False
    elif invalid == 'availability-string':
      release['available'] = 'true'
    elif invalid == 'duplicate-release':
      payload['releases'].append(dict(release))
    elif invalid == 'bad-version':
      payload['latest_version'] = 'latest'
      release['version'] = 'latest'
      release['iso_url'] = prefix + 'latest/archlinux-latest-x86_64.iso'
    elif invalid == 'bad-hash':
      release['sha256_sum'] = 'z' * 64
    elif invalid == 'missing-hash':
      del release['sha256_sum']
    elif invalid == 'bad-url':
      release['iso_url'] = older['iso_url']
    elif invalid == 'insecure-url':
      release['iso_url'] = 'http://geo.mirror.pkgbuild.com' + release['iso_url']
    destination.write_text('{invalid' if invalid == 'invalid-json'
                           else json.dumps(payload))
  else:
    if os.environ.get('QVM_ISO_BAD_HASH'):
      content += b'corrupted transfer\n'
    destination.write_bytes(content)
elif tool == 'systemctl':
  if args[0] in ('is-active', 'is-enabled'):
    configured = os.environ.get('QVM_' + args[0].upper().replace('-', '_'), '')
    raise SystemExit(0 if args[-1] in configured.split(',') else 1)
elif tool == 'virt-fw-vars':
  Path(argument('--output')).write_bytes(b'fixture NVRAM')
elif tool == 'virt-install':
  root = ET.Element('domain', type='kvm')
  ET.SubElement(root, 'name').text = argument('--name')
  ET.SubElement(root, 'uuid').text = str(uuid.uuid4())
  boot = options(argument('--boot'))
  guest_os = ET.SubElement(root, 'os')
  ET.SubElement(guest_os, 'type', arch='x86_64', machine='q35').text = 'hvm'
  for source in ('cdrom', 'hd'):
    if source in boot:
      ET.SubElement(guest_os, 'boot', dev=source)
  if 'loader' in boot:
    ET.SubElement(guest_os, 'loader', secure='yes').text = boot['loader']
    ET.SubElement(guest_os, 'nvram', template=boot['nvram.template'])
  else:
    guest_os.set('firmware', 'efi')
    firmware = ET.SubElement(guest_os, 'firmware')
    ET.SubElement(firmware, 'feature', name='secure-boot', enabled='no')
  devices = ET.SubElement(root, 'devices')
  for index, token in enumerate(args):
    if token != '--disk':
      continue
    disk = options(args[index + 1])
    device = ET.SubElement(devices, 'disk', device=disk.get('device', 'disk'))
    ET.SubElement(device, 'source', file=disk['path'])
    target = 'vda' if device.get('device') == 'disk' else (
      'sdb' if disk['path'].endswith('install.iso') else 'sdc')
    ET.SubElement(device, 'target', dev=target)
  if argument('--tpm') != 'none':
    tpm = ET.SubElement(devices, 'tpm', model='tpm-crb')
    ET.SubElement(tpm, 'backend', type='emulator', version='2.0')
  if os.environ.get('QVM_BAD_GENERATED'):
    root.find('name').text = 'WrongGuest'
  print(ET.tostring(root, encoding='unicode'))
elif tool == 'virsh':
  assert args[:2] == ['--connect', 'qemu:///system']
  args = args[2:]
  command = args[0]
  if command == 'list':
    if '--name' in args:
      print(os.environ.get('QVM_EXISTING', ''))
      for entry in state.glob('*.xml'):
        print(entry.stem)
  elif command == 'net-list':
    if os.environ.get('QVM_MISSING_NETWORK') != '1':
      print('default')
  elif command == 'define':
    if os.environ.get('QVM_DEFINE_RACE'):
      raise SystemExit('Domain already exists with a different UUID')
    content = Path(args[1]).read_text()
    name = ET.fromstring(content).findtext('name')
    (state / (name + '.xml')).write_text(content)
  elif command == 'dumpxml':
    content = (state / (args[1] + '.xml')).read_text()
    if os.environ.get('QVM_BAD_DEFINED'):
      content = content.replace('install.iso', 'different.iso')
    print(content)
  elif command == 'domstate':
    print(os.environ.get('QVM_GUEST_STATE', 'shut off'))
  elif command == 'change-media':
    location = state / (args[1] + '.xml')
    root = ET.fromstring(location.read_text())
    for disk in root.findall('devices/disk'):
      if disk.find('target').get('dev') == args[2]:
        source = disk.find('source')
        if source is not None:
          disk.remove(source)
    location.write_text(ET.tostring(root, encoding='unicode'))
  elif command in ('start', 'autostart', 'net-start', 'net-autostart',
                   'net-define', 'dominfo', 'domblklist', 'domiflist'):
    print('fixture: ' + command)
  else:
    raise SystemExit('Unexpected virsh command: ' + command)
else:
  raise SystemExit('Unexpected tool: ' + tool)
'''


class CliSafetyTests(unittest.TestCase):
  def setUp(self):
    self.temp = tempfile.TemporaryDirectory(prefix='qemu-vm-test-')
    self.addCleanup(self.temp.cleanup)
    self.base = Path(self.temp.name)
    self.base.chmod(0o755)
    self.bin = self.base / 'bin'
    self.bin.mkdir()
    self.state = self.base / 'state'
    self.state.mkdir()
    self.log = self.base / 'commands.jsonl'
    self.storage = self.base / 'storage'
    self.iso = self.base / "installer with spaces & 'quotes'.iso"
    self.iso.write_bytes(b'fixture installation ISO\n')
    dispatcher = self.bin / 'dispatcher.py'
    dispatcher.write_text(DISPATCHER)
    dispatcher.chmod(0o755)
    for tool in ('sudo', 'pacman', 'curl', 'systemctl', 'virsh', 'virt-install',
                 'virt-fw-vars', 'qemu-img'):
      (self.bin / tool).symlink_to(dispatcher)
    self.env = dict(os.environ)
    self.env.update({
      'PATH': str(self.bin) + os.pathsep + os.environ['PATH'],
      'QVM_STATE_DIR': str(self.state),
      'QVM_LOG': str(self.log),
      'QVM_REAL_QEMU_IMG': REAL_QEMU_IMG or '/nonexistent/qemu-img',
    })

  def run_cli(self, *arguments, real_host=False, **environment):
    env = dict(self.env, **environment)
    argv = (['bash', str(SCRIPT)] if real_host else
            ['bash', '-c', RUNNER, 'fixture', str(SCRIPT)])
    return subprocess.run(
      [*argv, *map(str, arguments)], env=env, text=True,
      capture_output=True, check=False,
    )

  def create(self, *arguments, **environment):
    if not REAL_QEMU_IMG:
      self.skipTest('qemu-img is required for disposable disk checks')
    return self.run_cli(
      'create', '--name', 'LabVM', '--storage-dir', self.storage,
      '--iso', self.iso, *arguments, **environment,
    )

  def commands(self, tool=None):
    records = [json.loads(line) for line in self.log.read_text().splitlines()
               ] if self.log.exists() else []
    return [record for record in records if tool in (None, record['tool'])]

  def create_download(self, *arguments, **environment):
    if not REAL_QEMU_IMG:
      self.skipTest('qemu-img is required for disposable disk checks')
    return self.run_cli(
      'create', '--name', 'LabVM', '--storage-dir', self.storage,
      *arguments, **environment,
    )

  def assert_no_disk_or_definition(self):
    self.assertEqual(self.commands('qemu-img'), [])
    self.assertEqual(list(self.storage.rglob('disk.qcow2')), [])
    self.assertEqual(list(self.state.glob('*.xml')), [])
    actions = [r['args'][2] for r in self.commands('virsh')]
    self.assertNotIn('define', actions)
    self.assertNotIn('start', actions)

  def assert_https_download(self, record, expected_url):
    arguments = record['args']
    self.assertEqual(arguments[0], '-q')
    for flag in ('--globoff', '--fail', '--location', '--output'):
      self.assertIn(flag, arguments)
    self.assertEqual(arguments[arguments.index('--proto') + 1], '=https')
    self.assertEqual(arguments[arguments.index('--proto-redir') + 1], '=https')
    self.assertEqual(arguments[-2:], ['--', expected_url])

  def assert_success(self, result):
    self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

  def assert_failure(self, result, message):
    self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
    self.assertIn(message, result.stderr)

  def test_help_needs_no_privileges(self):
    result = self.run_cli('--help', real_host=True)
    self.assert_success(result)
    self.assertIn('--disk-size', result.stdout)
    self.assertEqual(self.commands(), [])

  def test_setup_preview_runs_no_commands(self):
    result = self.run_cli('setup', '--with-manager')
    self.assert_success(result)
    self.assertIn('pacman -Syu --needed', result.stdout)
    self.assertIn('virt-manager', result.stdout)
    self.assertEqual(self.commands(), [])

  def test_create_preview_runs_no_commands_or_storage_writes(self):
    result = self.create('--setup')
    self.assert_success(result)
    self.assertIn('Plan for LabVM', result.stdout)
    self.assertEqual(self.commands(), [])
    self.assertFalse(self.storage.exists())

  def test_url_preview_never_downloads_or_uses_privileged_tools(self):
    result = self.create_download('--iso-url', INSTALLER_URL, '--setup')
    self.assert_success(result)
    self.assertEqual(self.commands(), [])
    self.assertFalse(self.storage.exists())

  def test_latest_arch_preview_never_fetches_release_metadata(self):
    result = self.create_download('--arch-latest', '--setup')
    self.assert_success(result)
    self.assertEqual(self.commands(), [])
    self.assertFalse(self.storage.exists())

  def test_url_and_checksum_argument_conflicts_fail_before_privileged_work(self):
    cases = [
      ('--arch-latest', '--iso', self.iso),
      ('--arch-latest', '--iso-url', INSTALLER_URL),
      ('--iso', self.iso, '--iso-url', INSTALLER_URL),
      ('--arch-latest', '--iso-sha256', DOWNLOAD_SHA256),
      ('--arch-latest', '--guest', 'windows'),
      ('--iso-url', 'http://example.invalid/installer.iso'),
      ('--iso', 'http://example.invalid/installer.iso'),
      ('--iso-url', 'file:///tmp/installer.iso'),
      ('--iso-url', 'https://'),
      ('--iso-url', 'https://example.invalid/unsafe\ninstaller.iso'),
      ('--iso-url', INSTALLER_URL, '--iso-sha256', 'z' * 64),
      ('--iso-url', INSTALLER_URL, '--iso-sha256', 'a' * 63),
      ('--iso-url', INSTALLER_URL, '--iso-sha256'),
      ('--iso-sha256', DOWNLOAD_SHA256),
    ]
    for arguments in cases:
      with self.subTest(arguments=arguments):
        result = self.create_download(*arguments, '--execute')
        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
    self.assertEqual(self.commands(), [])
    self.assertFalse(self.storage.exists())

  def test_url_download_stages_verified_bytes_before_definition(self):
    result = self.create_download('--iso-url', INSTALLER_URL,
                                  '--iso-sha256', DOWNLOAD_SHA256.upper(),
                                  '--no-start', '--execute')
    self.assert_success(result)
    guest_dir = self.storage / 'LabVM'
    self.assertEqual((guest_dir / 'install.iso').read_bytes(), DOWNLOAD_BYTES)
    self.assertFalse((guest_dir / 'install.iso.part').exists())
    calls = self.commands('curl')
    self.assertEqual(len(calls), 1)
    self.assert_https_download(calls[0], INSTALLER_URL)
    destination = calls[0]['args'][calls[0]['args'].index('--output') + 1]
    self.assertEqual(destination, str(guest_dir / 'install.iso.part'))
    ordered_tools = [r['tool'] for r in self.commands()]
    self.assertLess(ordered_tools.index('curl'), ordered_tools.index('qemu-img'))
    root = ET.parse(self.state / 'LabVM.xml').getroot()
    self.assertTrue(any(
      d.get('device') == 'cdrom' and
      d.find('source').get('file') == str(guest_dir / 'install.iso')
      for d in root.findall('devices/disk')
    ))

  def test_iso_argument_accepts_https_source_without_optional_checksum(self):
    result = self.create_download('--iso', INSTALLER_URL,
                                  '--no-start', '--execute')
    self.assert_success(result)
    self.assertEqual((self.storage / 'LabVM' / 'install.iso').read_bytes(),
                     DOWNLOAD_BYTES)
    self.assert_https_download(self.commands('curl')[0], INSTALLER_URL)

  def test_local_iso_accepts_matching_sha256_without_download(self):
    digest = hashlib.sha256(self.iso.read_bytes()).hexdigest()
    result = self.create('--iso-sha256', digest, '--no-start', '--execute')
    self.assert_success(result)
    self.assertEqual(self.commands('curl'), [])
    self.assertEqual((self.storage / 'LabVM' / 'install.iso').read_bytes(),
                     self.iso.read_bytes())

  def test_local_iso_checksum_mismatch_preserves_source_and_creates_no_disk(self):
    original = self.iso.read_bytes()
    result = self.create('--iso-sha256', '0' * 64, '--execute')
    self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
    self.assertEqual(self.iso.read_bytes(), original)
    self.assertEqual(self.commands('curl'), [])
    self.assert_no_disk_or_definition()

  def test_latest_arch_selects_pinned_release_and_automatic_os_variant(self):
    result = self.create_download('--arch-latest', '--no-start', '--execute')
    self.assert_success(result)
    guest_dir = self.storage / 'LabVM'
    self.assertEqual((guest_dir / 'install.iso').read_bytes(), DOWNLOAD_BYTES)
    self.assertFalse((guest_dir / 'install.iso.part').exists())
    metadata = json.loads((guest_dir / 'arch-release.json').read_text())
    self.assertEqual(metadata['latest_version'], ARCH_VERSION)
    calls = self.commands('curl')
    self.assertEqual(len(calls), 2)
    self.assert_https_download(calls[0], ARCH_RELEASES_URL)
    self.assert_https_download(calls[1], ARCH_ISO_URL)
    self.assertNotIn('/latest/', calls[1]['args'][-1])
    installer = self.commands('virt-install')[0]['args']
    self.assertEqual(installer[installer.index('--osinfo') + 1], 'archlinux')

  def test_latest_arch_preserves_explicit_os_variant(self):
    result = self.create_download('--arch-latest', '--os-variant', 'generic',
                                  '--no-start', '--execute')
    self.assert_success(result)
    installer = self.commands('virt-install')[0]['args']
    self.assertEqual(installer[installer.index('--osinfo') + 1], 'generic')

  def test_latest_arch_rejects_invalid_metadata_before_downloading_iso(self):
    cases = ('wrong-schema', 'missing-latest', 'missing-release', 'unavailable',
             'availability-string', 'duplicate-release', 'bad-version',
             'bad-hash', 'missing-hash', 'bad-url', 'insecure-url',
             'invalid-json')
    for index, invalid in enumerate(cases):
      with self.subTest(metadata=invalid):
        result = self.run_cli(
          'create', '--name', f'InvalidMetadata{index}', '--storage-dir',
          self.storage, '--arch-latest', '--execute',
          QVM_ARCH_BAD_METADATA=invalid,
        )
        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
    calls = self.commands('curl')
    self.assertEqual(len(calls), len(cases))
    for call in calls:
      self.assert_https_download(call, ARCH_RELEASES_URL)
    self.assert_no_disk_or_definition()

  def test_latest_arch_automatically_rejects_iso_checksum_mismatch(self):
    result = self.create_download('--arch-latest', '--execute',
                                  QVM_ISO_BAD_HASH='1')
    self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
    self.assertTrue((self.storage / 'LabVM' / 'install.iso.part').exists())
    self.assertFalse((self.storage / 'LabVM' / 'install.iso').exists())
    self.assert_no_disk_or_definition()

  def test_explicit_url_checksum_mismatch_preserves_partial_download(self):
    result = self.create_download('--iso-url', INSTALLER_URL,
                                  '--iso-sha256', '0' * 64, '--execute')
    self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
    self.assertTrue((self.storage / 'LabVM' / 'install.iso.part').exists())
    self.assertFalse((self.storage / 'LabVM' / 'install.iso').exists())
    self.assert_no_disk_or_definition()

  def test_failed_download_preserves_partial_file_and_does_not_create_disk(self):
    result = self.create_download('--iso-url', INSTALLER_URL, '--execute',
                                  QVM_CURL_FAIL='iso')
    self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
    self.assertEqual((self.storage / 'LabVM' / 'install.iso.part').read_bytes(),
                     b'partial transfer\n')
    self.assertFalse((self.storage / 'LabVM' / 'install.iso').exists())
    self.assert_no_disk_or_definition()

  def test_empty_download_does_not_publish_iso_or_create_disk(self):
    result = self.create_download('--iso-url', INSTALLER_URL, '--execute',
                                  QVM_CURL_EMPTY='iso')
    self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
    self.assertTrue((self.storage / 'LabVM' / 'install.iso.part').exists())
    self.assertFalse((self.storage / 'LabVM' / 'install.iso').exists())
    self.assert_no_disk_or_definition()

  def test_failed_arch_metadata_download_never_requests_iso(self):
    result = self.create_download('--arch-latest', '--execute',
                                  QVM_CURL_FAIL='metadata')
    self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
    self.assertEqual(len(self.commands('curl')), 1)
    self.assert_https_download(self.commands('curl')[0], ARCH_RELEASES_URL)
    self.assertEqual(
      (self.storage / 'LabVM' / 'arch-release.json.part').read_bytes(),
      b'partial transfer\n',
    )
    self.assert_no_disk_or_definition()

  def test_empty_arch_metadata_download_never_requests_iso(self):
    result = self.create_download('--arch-latest', '--execute',
                                  QVM_CURL_EMPTY='metadata')
    self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
    self.assertEqual(len(self.commands('curl')), 1)
    self.assert_https_download(self.commands('curl')[0], ARCH_RELEASES_URL)
    self.assertTrue((self.storage / 'LabVM' / 'arch-release.json.part').exists())
    self.assert_no_disk_or_definition()

  def test_host_identification_preserves_guest_name(self):
    if 'ID=arch\n' not in Path('/etc/os-release').read_text():
      self.skipTest('This regression check requires the actual Arch host')
    result = self.run_cli('create', '--name', 'KeepThisName', real_host=True)
    self.assert_success(result)
    self.assertIn('Plan for KeepThisName', result.stdout)
    self.assertNotIn('--name Arch', result.stdout)

  def test_invalid_arguments_never_invoke_privileged_tools(self):
    cases = [
      ('create', '--name', '../unsafe'),
      ('create', '--name', 'Guest', '--memory'),
      ('create', '--name', 'Guest', '--memory', '0'),
      ('create', '--name', 'Guest', '--memory', '04'),
      ('create', '--name', 'Guest', '--memory-max', '1024'),
      ('create', '--name', 'Guest', '--vcpus', '100000000000000000'),
      ('create', '--name', 'Guest', '--cpu-limit', '101'),
      ('create', '--name', 'Guest', '--boot', 'iso'),
      ('create', '--name', 'Guest', '--network', 'default,model=e1000e'),
      ('create', '--name', 'Guest', '--storage-dir', '/tmp/a,b'),
      ('create', '--name', 'Guest', '--iso', '/missing.iso'),
      ('create', '--name', 'Guest', '--execute', '--dry-run'),
      ('start', '--name', 'Guest', '--disk-size', '80'),
      ('setup', '--name', 'Guest'),
      ('info', '--name', 'Guest', '--with-manager'),
    ]
    for arguments in cases:
      with self.subTest(arguments=arguments):
        self.assertNotEqual(self.run_cli(*arguments).returncode, 0)
    self.assertEqual(self.commands(), [])

  def test_canonical_path_delimiters_are_rejected(self):
    destination = self.base / 'hidden,delimiter'
    destination.mkdir()
    link = self.base / 'innocent'
    link.symlink_to(destination)
    result = self.create('--storage-dir', link)
    self.assert_failure(result, 'commas or control characters')
    self.assertEqual(self.commands(), [])

  def test_existing_storage_is_preserved(self):
    guest_dir = self.storage / 'LabVM'
    guest_dir.mkdir(parents=True)
    sentinel = guest_dir / 'disk.qcow2'
    sentinel.write_bytes(b'do not overwrite')
    result = self.create('--execute')
    self.assert_failure(result, 'storage already exists')
    self.assertEqual(sentinel.read_bytes(), b'do not overwrite')
    self.assertEqual(self.commands(), [])

  def test_existing_guest_is_rejected_before_storage_writes(self):
    result = self.create('--execute', QVM_EXISTING='LabVM')
    self.assert_failure(result, 'VM already exists')
    self.assertFalse(self.storage.exists())
    self.assertEqual(self.commands('qemu-img'), [])

  def test_missing_network_is_rejected_before_storage_writes(self):
    result = self.create('--execute', QVM_MISSING_NETWORK='1')
    self.assert_failure(result, 'absent or inactive')
    self.assertFalse(self.storage.exists())

  def test_private_storage_ancestor_is_not_chmodded(self):
    self.storage.mkdir(mode=0o700)
    result = self.create('--execute')
    self.assert_failure(result, 'not traversable by QEMU')
    self.assertEqual(stat.S_IMODE(self.storage.stat().st_mode), 0o700)
    self.assertFalse((self.storage / 'LabVM').exists())

  def test_creation_handles_nested_parser_and_real_sparse_disk(self):
    self.storage = self.base / 'spaces & \'single\' "double" \\backslash' / 'vms'
    result = self.create('--no-start', '--execute')
    self.assert_success(result)
    guest_dir = self.storage / 'LabVM'
    self.assertEqual(stat.S_IMODE(self.storage.stat().st_mode), 0o755)
    self.assertEqual(stat.S_IMODE(self.storage.parent.stat().st_mode), 0o755)
    self.assertEqual((guest_dir / 'install.iso').read_bytes(),
                     self.iso.read_bytes())
    info = subprocess.run(
      [REAL_QEMU_IMG, 'info', '--output=json', str(guest_dir / 'disk.qcow2')],
      capture_output=True, text=True, check=True,
    )
    image = json.loads(info.stdout)
    self.assertEqual(image['format'], 'qcow2')
    self.assertEqual(image['virtual-size'], 64 * 1024**3)
    self.assertLess(image['actual-size'], 2 * 1024**2)
    self.assert_success(subprocess.run(
      [REAL_QEMU_IMG, 'check', str(guest_dir / 'disk.qcow2')],
      capture_output=True, text=True, check=False,
    ))
    root = ET.parse(self.state / 'LabVM.xml').getroot()
    self.assertEqual(root.find('devices/disk/source').get('file'),
                     str(guest_dir / 'disk.qcow2'))
    self.assertFalse(any(r['args'][2] == 'start' for r in self.commands('virsh')))
    installer = self.commands('virt-install')[0]['args']
    self.assertIn('--print-xml', installer)
    self.assertIn('--dry-run', installer)

  def test_windows_secure_boot_tpm_and_driver_media(self):
    drivers = self.base / 'virtio.iso'
    drivers.write_bytes(b'fixture drivers')
    result = self.create('--guest', 'windows', '--driver-iso', drivers,
                         '--no-start', '--execute')
    self.assert_success(result)
    self.assertEqual((self.storage / 'LabVM' / 'drivers.iso').read_bytes(),
                     drivers.read_bytes())
    firmware = self.commands('virt-fw-vars')[0]['args']
    for option in ('--enroll-microsoft', '--microsoft-db', '--microsoft-kek',
                   '--secure-boot'):
      self.assertIn(option, firmware)
    root = ET.parse(self.state / 'LabVM.xml').getroot()
    self.assertEqual(root.find('os/loader').get('secure'), 'yes')
    self.assertEqual(root.find('devices/tpm/backend').get('version'), '2.0')
    installer = self.commands('virt-install')[0]['args']
    self.assertIn('network=default,model=e1000e', installer)

  def test_cpu_budget_and_balloon_arguments(self):
    result = self.create('--vcpus', '4', '--cpu-limit', '50',
                         '--memory', '2048', '--memory-max', '8192',
                         '--no-start', '--execute')
    self.assert_success(result)
    installer = self.commands('virt-install')[0]['args']
    self.assertIn('global_period=100000,global_quota=200000', installer)
    self.assertIn('2048,maxmemory=8192', installer)
    self.assertEqual(installer[installer.index('--memballoon') + 1], 'virtio')

  def test_start_follows_definition_verification(self):
    result = self.create('--autostart', '--execute')
    self.assert_success(result)
    actions = [r['args'][2] for r in self.commands('virsh')]
    self.assertLess(actions.index('define'), actions.index('dumpxml'))
    self.assertLess(actions.index('dumpxml'), actions.index('autostart'))
    self.assertLess(actions.index('autostart'), actions.index('start'))

  def test_invalid_generated_xml_preserves_disk_and_does_not_define(self):
    result = self.create('--execute', QVM_BAD_GENERATED='1')
    self.assert_failure(result, 'unexpected guest name')
    self.assertIn('Partial VM state was preserved', result.stderr)
    self.assertTrue((self.storage / 'LabVM' / 'disk.qcow2').exists())
    actions = [r['args'][2] for r in self.commands('virsh')]
    self.assertNotIn('define', actions)
    self.assertNotIn('start', actions)

  def test_changed_defined_iso_prevents_start(self):
    result = self.create('--execute', QVM_BAD_DEFINED='1')
    self.assert_failure(result, 'requested ISO is absent')
    self.assertFalse(any(r['args'][2] == 'start' for r in self.commands('virsh')))

  def test_racing_guest_name_does_not_start_or_delete_partial_state(self):
    result = self.create('--execute', QVM_DEFINE_RACE='1')
    self.assert_failure(result, 'different UUID')
    self.assertTrue((self.storage / 'LabVM' / 'disk.qcow2').exists())
    self.assertFalse(any(r['args'][2] == 'start' for r in self.commands('virsh')))

  def test_setup_enables_services_for_boot_time_autostart(self):
    result = self.run_cli('setup', '--execute')
    self.assert_success(result)
    units = next(r['args'] for r in self.commands('systemctl')
                 if r['args'][0] == 'enable')
    self.assertIn('virtqemud.service', units)
    self.assertIn('virtnetworkd.service', units)
    self.assertIn('virtstoraged.service', units)
    self.assertNotIn('libvirtd.service', units)

  def test_active_monolithic_beats_inactive_enabled_modular(self):
    result = self.run_cli('setup', '--execute',
                          QVM_IS_ACTIVE='libvirtd.service',
                          QVM_IS_ENABLED='virtqemud.socket')
    self.assert_success(result)
    units = next(r['args'] for r in self.commands('systemctl')
                 if r['args'][0] == 'enable')
    self.assertIn('libvirtd.service', units)
    self.assertNotIn('virtqemud.socket', units)

  def test_competing_active_daemons_are_rejected(self):
    result = self.run_cli('setup', '--execute',
                          QVM_IS_ACTIVE='libvirtd.service,virtqemud.socket')
    self.assert_failure(result, 'Both libvirt daemon modes')
    self.assertFalse(any(r['args'][0] == 'enable'
                         for r in self.commands('systemctl')))

  def seed_media_guest(self):
    root = ET.Element('domain')
    ET.SubElement(root, 'name').text = 'LabVM'
    devices = ET.SubElement(root, 'devices')
    for target, filename in [('sdb', 'install.iso'), ('sdc', 'drivers.iso')]:
      disk = ET.SubElement(devices, 'disk', device='cdrom')
      ET.SubElement(disk, 'source', file='/fixture/' + filename)
      ET.SubElement(disk, 'target', dev=target)
    (self.state / 'LabVM.xml').write_text(ET.tostring(root, encoding='unicode'))

  def test_eject_refuses_running_guest(self):
    self.seed_media_guest()
    result = self.run_cli('eject-iso', '--name', 'LabVM', '--execute',
                          QVM_GUEST_STATE='running')
    self.assert_failure(result, 'powered-off VM')
    self.assertFalse(any(r['args'][2] == 'change-media'
                         for r in self.commands('virsh')))

  def test_eject_preserves_second_cdrom(self):
    self.seed_media_guest()
    result = self.run_cli('eject-iso', '--name', 'LabVM', '--execute')
    self.assert_success(result)
    root = ET.parse(self.state / 'LabVM.xml').getroot()
    disks = root.findall('devices/disk')
    self.assertIsNone(disks[0].find('source'))
    self.assertEqual(disks[1].find('source').get('file'), '/fixture/drivers.iso')
    change = next(r['args'] for r in self.commands('virsh')
                  if r['args'][2] == 'change-media')
    self.assertIn('--config', change)
    self.assertNotIn('--live', change)


if __name__ == '__main__':
  unittest.main()
