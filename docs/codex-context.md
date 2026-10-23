# Project context

## Current work

The active checkout is `/home/heini/my_repos/qemu-vm`. The earlier
`/home/heini/qemu-vm` copy is separate. Work in this checkout.

`--help` and the README now include examples for local media, the newest Arch
ISO, installer URLs, Windows/VirtIO, resource limits, and network modes.

## Failure review and revision (2026-10-23)

### Guided use and verified host state

- `menu` (also no arguments in a terminal) guides ISO selection, creation and
  opening the installer display. No-argument pipes retain help behavior. Menu
  actions use fresh Bash children so conditional handling cannot suppress
  errexit inside guest creation. Plans show a human-readable summary and need
  explicit confirmation before network/guest changes.
- `connect --name NAME --execute` checks the desktop and graphics, starts a
  powered-off guest, and launches virt-viewer as the desktop account.
- `network-start --execute` enables the existing default network and its
  autostart without reinstalling packages. Network-start errors identify the
  missing firewalld zone without automatically reloading the host firewall.
- Live host diagnosis found no registered guests, inactive default networking,
  and firewalld missing libvirt's installed zone from its loaded configuration.
  Compared runtime/saved zones, policies, direct rules and IP sets; validated
  saved configuration; approved firewalld reload succeeded. The default network
  is now active and autostarted.
- A second PATH collision affected privileged checks: `/usr/local/bin/test`
  was an invalid colored-text file. Privileged filesystem checks now explicitly
  invoke `/usr/bin/test`; no change was made to the unrelated local file.
- Created real `AlpineLab2`: Alpine 3.24 ISO, 4096 MiB RAM, two vCPUs, sparse
  64 GiB disk. It is running and virt-viewer opened on the desktop. A screenshot
  confirmed the Alpine ISO booted to its root shell. OS installation to disk
  has not been performed by this work.
- At the user's explicit cleanup request, removed the obsolete unregistered
  `/var/lib/libvirt/images/AlpineLab` ISO/disk and empty directory. Final host
  inventory has only AlpineLab2 and its own ISO/disk/domain.xml.

### Earlier tool and validation fixes

- Reproduced `/usr/bin/virt-install --version` failing with
  `ModuleNotFoundError: No module named 'gi'`. Its env-based shebang selected
  uv Python 3.15 from the user's PATH; Arch's gi/libvirt bindings were available
  to `/usr/bin/python3` (3.14). The configured sudo path had the same conflict.
- Packaged `virt-install` and `virt-fw-vars` now run through
  `/usr/bin/python3 -I`. Custom executables retain their resolved paths across
  sudo's PATH boundary. Tools are resolved again after `create --setup` may
  have installed them.
- Before guest storage creation, check installer execution, libosinfo IDs and
  aliases, and the requested Secure Boot tool. These checks prevent known tool
  failures from leaving a newly staged ISO and disk.
- `doctor` checks tools, installer execution, KVM device presence, and libvirt
  queries. It does not invoke host configuration or guest changes. Like `info`,
  it may authenticate with sudo; libvirt socket queries may activate a daemon.
- Windows previews use firmware placeholders, so they work before dependencies
  are installed. Execution still discovers compatible installed firmware.
- EXIT handling reports partial-state recovery guidance for explicit validation
  errors as well as failed commands. Existing guest state is always preserved;
  there is no automatic resume or deletion mode.
- `/var/lib/libvirt/images/AlpineLab` already contained an ISO and disk without
  `domain.xml`, consistent with failure before XML generation. It was left alone.

## Download decisions

- `--arch-latest` resolves the latest available version using
  `https://archlinux.org/releng/releases/json/` during execution.
- Use the dated ISO path from the matching release at the official geo mirror;
  check its SHA-256 against the official metadata before publishing it.
- `--iso-url HTTPS_URL` and `--iso HTTPS_URL` accept other installers.
  `--iso-sha256 HEX` optionally checks these or local images.
- The three installer sources are exclusive. Arch selects `archlinux` as the
  default OS variant; explicit variants remain supported.
- Preview makes no network requests. Curl ignores curlrc and URL globbing and
  restricts initial and redirected requests to HTTPS.
- Downloads use `install.iso.part` in a newly created guest directory. Publish
  as `install.iso` only after transfer/content/checksum checks. Retain failed
  downloads and stop before disk creation or guest registration.
- Detached PGP signature verification is separate from the automatic SHA-256
  check. The README explains the distinction.

## Verification

The offline suite mocks curl, libvirt, services, package installation, and
privilege changes. It also checks disposable real qcow2 images. It covers
successful downloads, failed/empty transfers, checksum mismatches, malformed
release metadata, source conflicts, and previews without side effects. The
revised suite also covers tool preflight failures, OS aliases, firmware-free
previews, and read-only diagnosis. All 77 tests passed after final integration
(59 CLI fixtures, five installed-tool checks and 13 menu tests), alongside
Bash syntax, ShellCheck, shfmt, Ruff, and diff whitespace checks.

`tests/test_installed_tools.py` adds real installed-tool checks: a poisoned user
Python environment, persistent custom tool selection, and Linux/Windows XML
generation. The latter uses virtinst's internal synthetic capability URI and
libvirt's in-memory test driver, plus schema validation when installed. It
cannot establish real host capabilities or guest boot support.

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -v
bash -n qemu-vm.sh lib/menu.sh
shellcheck qemu-vm.sh lib/menu.sh
shfmt -d -i 2 -ci qemu-vm.sh lib/menu.sh
ruff check --no-cache tests
git diff --check
```

The live official metadata and the selected ISO's response headers were checked
on 2026-10-23 in the earlier revision. This review also generated valid real
Linux/Windows domain XML and enrolled Secure Boot certificates in a temporary
NVRAM template. Later live verification outside the sandbox succeeded for
network activation, guest creation, real Alpine ISO boot and its viewer. The
sandbox itself lacks `/dev/kvm`; the host exposes KVM through libvirt. Full ISO
transfer, package installation, Secure Boot execution, and completion of guest
OS installation remain unverified.
