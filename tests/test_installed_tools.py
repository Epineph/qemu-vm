#!/usr/bin/env python3
"""Exercise installed Python tools without sudo, services, or real guests.

These tests supplement the simulated CLI suite with the real virt-install
parser and libvirt XML schema. The optional virtinst test URI is an upstream
internal hook: it opens libvirt's in-memory test driver with synthetic host
capabilities. It proves argument/XML compatibility, not QEMU bootability.
"""

import json
import os
import shutil
import subprocess
import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / 'qemu-vm.sh'
SYSTEM_PYTHON = Path('/usr/bin/python3')
VIRT_INSTALL = Path('/usr/bin/virt-install')

CAPABILITIES = '''\
<capabilities>
  <host><cpu><arch>x86_64</arch></cpu></host>
  <guest>
    <os_type>hvm</os_type>
    <arch name="x86_64">
      <wordsize>64</wordsize>
      <emulator>/usr/bin/qemu-system-x86_64</emulator>
      <machine>q35</machine><domain type="kvm"/>
    </arch>
    <features><acpi default="on" toggle="yes"/></features>
  </guest>
</capabilities>
'''

DOMAIN_CAPABILITIES = '''\
<domainCapabilities>
  <path>/usr/bin/qemu-system-x86_64</path>
  <domain>kvm</domain><machine>q35</machine><arch>x86_64</arch>
  <vcpu max="1024"/>
  <os supported="yes">
    <enum name="firmware"><value>efi</value></enum>
  </os>
  <cpu><mode name="host-passthrough" supported="yes"/></cpu>
  <devices>
    <tpm supported="yes">
      <enum name="model"><value>tpm-crb</value></enum>
      <enum name="backendModel"><value>emulator</value></enum>
      <enum name="backendVersion"><value>2.0</value></enum>
    </tpm>
  </devices>
</domainCapabilities>
'''

GENERATE_XML = r'''
source "$1"
shift
init_python_tools
parse_args "$@"
validate_create
VM_URI=$QVM_TEST_URI
# virt-install requires attached media to exist even for --print-xml --dry-run.
mkdir -p -- "$VM_DIR"
cp -- "$ISO" "$MEDIA_PATH"
if [[ "$SECURE_BOOT" == on ]]; then discover_secure_firmware; fi
build_install_args
"${INSTALL_ARGS[@]}"
'''


class InstalledToolsTests(unittest.TestCase):
  @classmethod
  def setUpClass(cls):
    for command in (SYSTEM_PYTHON, VIRT_INSTALL):
      if not command.is_file():
        raise unittest.SkipTest(f'Optional installed tool unavailable: {command}')
    probe = subprocess.run(
      [str(SYSTEM_PYTHON), '-I', str(VIRT_INSTALL), '--version'],
      text=True, capture_output=True, check=False,
    )
    if probe.returncode:
      if ('ModuleNotFoundError:' in probe.stderr or
          'ImportError:' in probe.stderr):
        raise unittest.SkipTest('Optional virt-install dependencies unavailable: '
                                + probe.stderr.strip().splitlines()[-1])
      raise RuntimeError('Installed virt-install cannot start: ' + probe.stderr)
    cls.version = probe.stdout.strip()
    driver = subprocess.run(
      [str(SYSTEM_PYTHON), '-I', '-c',
       "import libvirt; libvirt.open('test:///default').close()"],
      text=True, capture_output=True, check=False,
    )
    cls.test_driver_error = driver.stderr.strip() if driver.returncode else ''

  def setUp(self):
    self.temp = tempfile.TemporaryDirectory(prefix='qemu-vm-installed-')
    self.addCleanup(self.temp.cleanup)
    self.base = Path(self.temp.name)
    self.env = dict(os.environ)
    self.env.update({
      'PATH': '/usr/bin:/bin',
      'XDG_CACHE_HOME': str(self.base / 'cache'),
    })

  def run_bash(self, code, *arguments, env=None):
    return subprocess.run(
      ['/bin/bash', '-c', code, 'installed-tool-test', str(SCRIPT),
       *map(str, arguments)],
      env=env or self.env, text=True, capture_output=True, check=False,
    )

  def test_packaged_installer_ignores_user_python_environment(self):
    poison = self.base / 'poison'
    poison.mkdir()
    interpreter = poison / 'python3'
    interpreter.write_text('#!/bin/sh\necho wrong-python >&2\nexit 99\n')
    interpreter.chmod(0o755)
    (poison / 'gi.py').write_text('raise RuntimeError("poisoned gi module")\n')
    env = dict(self.env, PATH=str(poison) + ':/usr/bin:/bin',
               PYTHONPATH=str(poison), PYTHONHOME=str(poison))
    result = self.run_bash(r'''
source "$1"
init_python_tools
"${VIRT_INSTALL[@]}" --version
''', env=env)
    self.assertEqual(result.returncode, 0, result.stderr)
    self.assertEqual(result.stdout.strip(), self.version)
    self.assertNotIn('wrong-python', result.stderr)

  def test_custom_installer_survives_later_path_change(self):
    custom_bin = self.base / 'custom-bin'
    custom_bin.mkdir()
    wrapper = custom_bin / 'virt-install'
    wrapper.write_text('#!/bin/sh\nprintf "custom-installer %s\\n" "$1"\n')
    wrapper.chmod(0o755)
    env = dict(self.env, PATH=str(custom_bin) + ':/usr/bin:/bin')
    result = self.run_bash(r'''
source "$1"
init_python_tools
# sudo can search a different PATH after the executable has been selected.
PATH=/usr/bin:/bin
"${VIRT_INSTALL[@]}" --version
''', env=env)
    self.assertEqual(result.returncode, 0, result.stderr)
    self.assertEqual(result.stdout.strip(), 'custom-installer --version')

  def test_creation_preflight_refreshes_tools_installed_after_initial_lookup(self):
    if not shutil.which('qemu-img', path=self.env['PATH']):
      self.skipTest('Optional qemu-img unavailable for creation preflight')
    empty_bin = self.base / 'empty-bin'
    empty_bin.mkdir()
    poison = self.base / 'poison'
    poison.mkdir()
    interpreter = poison / 'python3'
    interpreter.write_text('#!/bin/sh\necho wrong-python >&2\nexit 99\n')
    interpreter.chmod(0o755)
    env = dict(self.env, PATH=str(empty_bin))
    result = self.run_bash(r'''
source "$1"
init_python_tools
# Simulate setup making the distro tools newly visible to this invocation.
PATH="$2:/usr/bin:/bin"
OS_VARIANT=generic
SECURE_BOOT=off
check_creation_tools
"${VIRT_INSTALL[@]}" --version
''', poison, env=env)
    self.assertEqual(result.returncode, 0, result.stderr)
    self.assertEqual(result.stdout.strip().splitlines()[-1], self.version)
    self.assertNotIn('wrong-python', result.stderr)

  def generate_xml(self, *arguments):
    if self.test_driver_error:
      self.skipTest('Optional libvirt test driver unavailable: '
                    + self.test_driver_error)
    caps = self.base / 'capabilities.xml'
    domcaps = self.base / 'domain-capabilities.xml'
    caps.write_text(CAPABILITIES)
    domcaps.write_text(DOMAIN_CAPABILITIES)
    self.env['QVM_TEST_URI'] = (
      '__virtinst_test__test:///default,fakeuri=qemu:///system,'
      f'caps={caps},domcaps={domcaps}'
    )
    # Embedded quotes/backslashes exercise virt-install's second parsing layer.
    storage = self.base / '''storage with ' and " and \\ marks'''
    self.iso = self.base / '''installer with ' and " and \\ marks.iso'''
    self.iso.write_bytes(b'offline parser fixture\n')
    result = self.run_bash(
      GENERATE_XML, 'create', '--name', 'ParserTest', '--iso', self.iso,
      '--storage-dir', storage, '--disk-size', '1', '--network', 'none',
      '--memory', '2048', '--memory-max', '8192', '--vcpus', '4',
      '--cpu-limit', '50', *arguments,
    )
    self.assertEqual(result.returncode, 0, result.stderr)
    root = ET.fromstring(result.stdout)
    self.assertEqual(root.findtext('memory'), '8388608')
    self.assertEqual(root.findtext('currentMemory'), '2097152')
    self.assertEqual(root.findtext('cputune/global_quota'), '200000')
    self.assertEqual(root.findtext('vcpu'), '4')
    self.assertEqual(root.find('devices/memballoon').get('model'), 'virtio')
    self.assertEqual(root.findall('devices/interface'), [])
    disk = root.find("devices/disk[@device='disk']/source")
    self.assertEqual(disk.get('file'), str(storage / 'ParserTest/disk.qcow2'))
    media = root.find("devices/disk[@device='cdrom']/source")
    self.assertEqual(media.get('file'), str(storage / 'ParserTest/install.iso'))
    self.assertFalse((storage / 'ParserTest/disk.qcow2').exists(),
                     'XML preview must not create the guest disk')
    if all(shutil.which(tool, path=self.env['PATH'])
           for tool in ('virt-xml-validate', 'xmllint')):
      xml_file = self.base / 'domain.xml'
      xml_file.write_text(result.stdout)
      validation = subprocess.run(
        ['virt-xml-validate', str(xml_file), 'domain'], env=self.env,
        text=True, capture_output=True, check=False,
      )
      self.assertEqual(validation.returncode, 0, validation.stderr)
    return root

  def test_linux_arguments_generate_valid_real_xml(self):
    root = self.generate_xml()
    self.assertEqual(root.find('os').get('firmware'), 'efi')
    feature = root.find("os/firmware/feature[@name='secure-boot']")
    self.assertEqual(feature.get('enabled'), 'no')
    self.assertIsNone(root.find('devices/tpm'))

  def test_windows_arguments_generate_valid_real_xml(self):
    compatible_firmware = False
    for descriptor in Path('/usr/share/qemu/firmware').glob('*.json'):
      info = json.loads(descriptor.read_text())
      mapping = info.get('mapping', {})
      if ('secure-boot' in info.get('features', []) and
          any(target.get('architecture') == 'x86_64'
              for target in info.get('targets', [])) and
          mapping.get('device') == 'flash' and
          all(Path(mapping.get(key, {}).get('filename', '')).is_file()
              for key in ('executable', 'nvram-template'))):
        compatible_firmware = True
        break
    if not compatible_firmware:
      self.skipTest('Optional x86_64 Secure Boot firmware unavailable')
    root = self.generate_xml('--guest', 'windows')
    loader = root.find('os/loader')
    self.assertEqual(loader.get('secure'), 'yes')
    self.assertEqual(loader.get('type'), 'pflash')
    self.assertEqual(root.find('features/smm').get('state'), 'on')
    self.assertTrue(root.find('os/nvram').get('template').endswith(
      '/ParserTest/secure-vars-template.fd'))
    backend = root.find('devices/tpm/backend')
    self.assertEqual(backend.get('type'), 'emulator')
    self.assertEqual(backend.get('version'), '2.0')


if __name__ == '__main__':
  unittest.main()
