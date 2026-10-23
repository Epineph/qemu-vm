# QEMU/KVM virtual machines on Arch Linux

`qemu-vm.sh` installs the host tools and creates persistent libvirt guests from
local ISOs, HTTPS URLs, or the newest official Arch installation ISO. Run it
from Bash or invoke the executable from Zsh.
The host must run x86-64 Arch Linux with AMD-V or Intel VT-x available.

Every command that changes state previews its operation until `--execute` is
supplied. `info` and `doctor` query system libvirt and can request sudo
authentication. Run the script as your ordinary account; it uses sudo for the
operations that require root. Host setup and creation also work in a root shell.

## Start here: guided creation and installer display

Open a terminal in your desktop session, then run:

```bash
cd ~/my_repos/qemu-vm
./qemu-vm.sh menu
```

Choose **1: Create a VM**. The guide asks for Linux or Windows, the ISO file,
a new VM name, and resources with defaults you can accept by pressing Enter.
It shows a short summary and asks before applying changes. Creation enables
the existing default VM network after your confirmation. Host setup is an
optional separate choice; it includes a full Arch package upgrade.

After creation, answer **y** to open the installer window. The ISO is already
attached to the VM. You use the installer inside that window. Later, menu
option **2** lists your VMs and starts/opens the one you select.

Running `./qemu-vm.sh` without arguments also opens this menu in a terminal.
Noninteractive invocations without arguments still show help.

Choose a **new name** when a failed attempt has retained its storage folder.
A directory containing an ISO and disk is not yet a registered VM, so it
cannot be opened through the VM list until creation succeeds. The menu keeps
existing guest files; cleanup is a separate administration operation.

To open an already registered VM directly:

```bash
./qemu-vm.sh connect --name AlpineLab2 --execute
```

`connect` starts the VM if it is powered off, then opens `virt-viewer` as your
desktop user. Run it without sudo. Closing the display window leaves the VM
running; shut down the guest normally when finished.

## Host setup

Arch's `bash`, `coreutils`, `kmod`, `pacman`, and `systemd` provide the basic
commands. An ordinary account needs sudo privileges. Setup installs Python and
the remaining tools through their package dependencies.

```bash
cd ~/my_repos/qemu-vm
./qemu-vm.sh --help

# Preview packages, daemon configuration, and the default NAT network.
./qemu-vm.sh setup --with-manager

# Apply the setup. Pacman retains its normal confirmation prompt.
./qemu-vm.sh setup --with-manager --execute
```

The package transaction is:

```bash
sudo pacman -Syu --needed -- \
  qemu-desktop libvirt virt-install virt-viewer edk2-ovmf \
  virt-firmware swtpm dnsmasq nftables curl ca-certificates virt-manager
```

`virt-manager` is included only with `--with-manager`. `--needed` avoids
reinstalling packages already at the current version. `-Syu` also upgrades the
host, keeping Arch's packages consistent during dependency installation.

Setup detects an active libvirt daemon mode first, then an enabled mode.
Existing monolithic installations use `libvirtd`. Fresh installations use
modular QEMU, network, and storage services and their supporting sockets.
Enabling the driver services also makes VM/network autostart work after a host
reboot. The default network's existing configuration is retained; setup defines
the packaged network only when absent and enables its startup. This follows
[libvirt's daemon and autostart guidance](https://libvirt.org/daemons.html).

The script loads `kvm_amd` or `kvm_intel` if `/dev/kvm` is absent. A kernel
without KVM support or disabled firmware virtualization produces a clear error.
A host kernel upgrade may require a reboot before modules match the running
kernel.

Check tools, KVM device presence and libvirt state:

```bash
./qemu-vm.sh doctor
```

This reports executable availability, the selected Python/installer command,
whether the installer runs, KVM device presence, libvirt connectivity, and the
defined guests and networks. It returns a failure status when a required check
fails, including an inactive default network. Enable an existing default
network without reinstalling packages or upgrading the host:

```bash
./qemu-vm.sh network-start
./qemu-vm.sh network-start --execute
```

This starts the network when inactive and enables its autostart. Menu option
**5** provides the same operation with a preview and confirmation.
Firmware execution, network connectivity inside a guest, and VM boot
still require testing with a real guest.

## Fetch the newest Arch ISO automatically

Use `--arch-latest` to resolve the current official release when you apply the
command. This preview makes no network requests:

```bash
./qemu-vm.sh create --name ArchLatest --arch-latest \
  --memory 4096 --vcpus 4 --disk-size 80 --no-start
```

Add `--execute` to download the ISO and create the powered-off guest. The
`archlinux` OS variant and ISO-first boot are selected automatically. You can
configure the host and create the guest in one invocation:

```bash
./qemu-vm.sh create --setup --with-manager --name ArchPrepared \
  --arch-latest --no-start --execute
```

The script reads [Arch's official release metadata][arch-releases], selects its
latest available release, and fetches that release's dated x86-64 ISO from
`geo.mirror.pkgbuild.com`. It checks the ISO against the SHA-256 published in
that metadata before attaching it. Pinning the dated URL keeps the checksum
and image on the same release if a new ISO appears during the download.

This verifies integrity against metadata retrieved over HTTPS. Detached PGP
signature verification is a separate process described on the
[official Arch download page][arch-download].

[arch-releases]: https://archlinux.org/releng/releases/json/
[arch-download]: https://archlinux.org/download/

## Use an installer URL

Use `--iso-url` for another distribution or a vendor-provided download link.
Replace the example URL with a direct installer download:

```bash
./qemu-vm.sh create --name DownloadedLab \
  --iso-url 'https://example.org/installer.iso' --no-start
```

`--iso 'https://example.org/installer.iso'` is an equivalent shortcut. Quote
URLs containing query parameters such as `?` or `&`. A URL can point to a
download endpoint without an `.iso` suffix. The source must use HTTPS, and
redirects must also remain on HTTPS. URL credentials and fragments are rejected.

Supply `--iso-sha256 HEX` to verify a publisher-provided 64-character SHA-256
checksum. This also works with local `--iso` files. Arbitrary URL downloads
without that option are checked for transfer errors and nonempty content;
they have no publisher checksum check. `--arch-latest` always uses its official
checksum and cannot be combined with `--iso-sha256`.

Choose one installation source: local `--iso`, a URL, or `--arch-latest`.
Each remote ISO downloads to the new VM directory as `install.iso.part` and is
renamed to `install.iso` after its checks pass. A failed transfer or checksum
keeps the partial file for inspection and stops before disk creation or VM
registration. `curl` retries transient download errors; rerunning `create`
still refuses an existing VM directory.

## Create an Arch Linux guest

Replace the ISO path with a file that exists on your machine:

```bash
./qemu-vm.sh create \
  --name ArchLab \
  --iso "$HOME/Downloads/archlinux-x86_64.iso" \
  --os-variant archlinux \
  --memory 4096 \
  --vcpus 4 \
  --disk-size 80
```

Review the preview, then repeat with `--execute` to create and start it:

```bash
./qemu-vm.sh create \
  --name ArchLab \
  --iso "$HOME/Downloads/archlinux-x86_64.iso" \
  --os-variant archlinux \
  --memory 4096 \
  --vcpus 4 \
  --disk-size 80 \
  --execute

virt-viewer --connect qemu:///system ArchLab
```

`virt-viewer` opens the installer display. Complete the operating-system
installation there. On Hyprland, the viewer's authorization prompt needs a
running desktop polkit authentication agent. `virt-manager` can manage the same
VMs through its **QEMU/KVM system** connection.

For dependency setup and guest creation in one invocation, add `--setup` to
`create`. Setup runs only when requested; subsequent guests can reuse the host
configuration. The installation ISO remains attached until you eject it.

To prepare a VM without starting it, add `--no-start`. To start it at future
host boots, add `--autostart`.

## Create a Windows 11 guest

```bash
./qemu-vm.sh create \
  --name Windows11 \
  --guest windows \
  --iso "$HOME/Downloads/Windows11.iso" \
  --memory 8192 \
  --vcpus 4 \
  --disk-size 128 \
  --no-start
```

Add `--execute` after reviewing the plan. The Windows preset enables TPM 2.0
and Secure Boot, selects the `win11` OS definition, and uses a SATA disk and
e1000e network interface. Explicit options override these defaults.

For VirtIO storage and networking, obtain a trusted VirtIO driver ISO, then use:

```bash
./qemu-vm.sh create \
  --name WindowsVirtIO \
  --guest windows \
  --iso "$HOME/Downloads/Windows11.iso" \
  --driver-iso "$HOME/Downloads/virtio-win.iso" \
  --disk-bus virtio \
  --nic-model virtio \
  --no-start \
  --execute
```

Load the appropriate Windows storage driver from the second CD-ROM during
installation, then install its networking and other guest drivers.

## More creation examples

These examples also appear in `./qemu-vm.sh --help`. They preview their
operations; add `--execute` to apply one. Each uses a different VM name.

Four vCPUs with a 50% aggregate CPU budget allow about two logical CPUs' worth
of total VM CPU time. This guest starts with 4 GiB RAM and an 8 GiB balloon
ceiling, which requires guest support and manual management:

```bash
./qemu-vm.sh create --name LimitedLab --arch-latest \
  --vcpus 4 --cpu-limit 50 --memory 4096 --memory-max 8192
```

Create an offline guest with 2 GiB RAM, a 32 GiB disk, and no network interface:

```bash
./qemu-vm.sh create --name OfflineLab --arch-latest \
  --network none --memory 2048 --disk-size 32 --no-start
```

The host still needs internet access to fetch the ISO for this offline guest.
Use a local `--iso` instead if the host is also offline.

Attach a guest to an existing Linux bridge named `br0`. Configure the host
bridge before using this example:

```bash
./qemu-vm.sh create --name BridgedLab --arch-latest --network bridge=br0
```

## Main parameters and Hyper-V equivalents

RAM is in MiB; disk capacity is in GiB. Each VM has a new sparse qcow2 disk.

| Hyper-V concept | Script option / Linux behavior |
| --- | --- |
| VM name | `--name NAME` |
| Installation ISO | `--iso PATH` |
| Download an installer | `--iso-url HTTPS_URL` or `--iso HTTPS_URL` |
| Newest official Arch installer | `--arch-latest`; automatic SHA-256 check |
| Expected installer checksum | `--iso-sha256 HEX` |
| Additional driver media | `--driver-iso PATH` |
| Processor count | `--vcpus N`; one socket with N cores |
| CPU model | `--cpu host-passthrough` or `host-model` |
| CPU scheduling weight | `--cpu-shares N`; relative to other guests |
| CPU maximum | `--cpu-limit PERCENT`; aggregate quota for allocated vCPUs |
| Startup memory | `--memory MIB` |
| Balloon memory ceiling | `--memory-max MIB` |
| New virtual disk capacity | `--disk-size GIB` |
| VM storage location | `--storage-dir /absolute/parent` |
| Virtual switch | `--network NAME`, `bridge=BRIDGE`, or `none` |
| Generation 2 firmware | UEFI with the q35 machine type |
| Secure Boot | `--secure-boot off` or `on` |
| Virtual TPM | `--tpm` / `--no-tpm`; software TPM 2.0 |
| Preferred initial boot source | `--boot iso` or `disk` |
| Leave powered off | `--no-start` |
| Start at host boot | `--autostart` |
| WhatIf | Default preview; `--execute` applies the operation |

With four vCPUs, `--cpu-limit 50` allows about two logical CPUs' worth of total
VM CPU time, including emulator work. It does not mean 50% of the entire host.
No quota is imposed unless you supply the option. CPU shares express priority
during contention; they are not percentages. Valid weight ranges depend on
cgroups v1/v2, and the script detects the host's range. See
[libvirt CPU tuning](https://libvirt.org/formatdomain.html#cpu-tuning).

RAM defaults to a fixed setting. A larger `--memory-max` enables a VirtIO
balloon with separate initial/current and maximum memory values. This requires
guest balloon support and manual or external policy management. It does not
implement Hyper-V's automatic Dynamic Memory algorithm or minimum/buffer
settings. For a suitable running guest, an administrator can change the target:

```bash
sudo virsh --connect qemu:///system setmem ArchLab 6144MiB --live --config
```

That example requires creating the VM with a memory ceiling of at least
6144 MiB. Ballooning can reclaim guest memory; it does not add virtual DIMMs.

UEFI boot entries can subsequently be changed by the guest firmware or OS.
Ejecting the installation ISO after installation avoids booting it again.

## Firmware and TPM

Secure Boot defaults to off for Linux and on for the Windows preset. When it
is off, libvirt chooses a non-Secure-Boot UEFI firmware through its metadata.

The installed Arch OVMF package at development time advertised Secure Boot
firmware with an empty variable template. For `on`, the script discovers a
compatible x86-64 q35 firmware descriptor and uses `virt-fw-vars` to create a
separate template with a Microsoft platform key, Microsoft KEK certificates,
and Microsoft Windows/UEFI signing certificates, including the tool's legacy
and newer certificate sets. The `--secure-boot` flag activates enforcement.
Libvirt creates each VM's writable NVRAM from that template. See the
[virt-firmware tool documentation](https://gitlab.com/kraxel/virt-firmware)
and the [libvirt Secure Boot guide](https://libvirt.org/kbase/secureboot.html).

This policy accepts bootloaders signed by the enrolled certificates. It has no
separate Hyper-V Windows/Linux template selector. Use a signed guest bootloader
or keep `--secure-boot off` for an unsigned installer. The template uses the
revocation data supplied by the input template/tool; the script does not fetch
a new DBX revocation list. Maintain guest firmware revocations through the
normal guest administration process.

TPM state is maintained by libvirt and `swtpm`. Back up the guest's disk, NVRAM,
and TPM state together if using guest encryption tied to that TPM.

## Storage and networking

The default guest files are:

```text
/var/lib/libvirt/images/ArchLab/
  disk.qcow2                 New sparse guest disk
  install.iso                Copy of the requested installer, when supplied
  arch-release.json          Official release metadata with --arch-latest
  drivers.iso                Optional driver media copy
  secure-vars-template.fd    Secure Boot template, when enabled
  domain.xml                 Initial definition for inspection
```

Local ISO copies use reflinks when the filesystems support them; otherwise they
use ordinary copies. Copies are compared with their sources before the guest
is defined. Full comparisons read the ISO data. Staging media here lets QEMU
read it without changing permissions on private home directories.

Before creating the guest directory, the script checks that `virt-install`
runs, validates the OS definition against libosinfo (including aliases), and
checks the Secure Boot tool when requested. Windows previews use symbolic
firmware paths so that `create --setup` can be previewed before OVMF is installed.

Existing guest names and guest directories are rejected. The script creates
missing storage ancestors with traversal permissions, and requires existing
ancestors to be traversable by other users. It leaves existing permissions
alone. ACL-only access is outside this check; use the default storage root or
a suitable shared directory. Paths with commas or control characters are
rejected; spaces, quotes, and backslashes are handled.

`--network default` uses libvirt's active default network. Other network names
must already be active. `--network bridge=br0` uses an existing Linux bridge;
the script validates that it exists. `--network none` creates an offline VM.
Setup enables the default NAT network even if a subsequent guest uses a
different network mode.

SPICE/VNC listeners bind to `127.0.0.1`. `--graphics none` provides a serial
console endpoint; the installer and installed guest must themselves support
serial output. It does not inject kernel arguments into an arbitrary ISO.

## Eject media, start, and inspect

After installation, shut down the guest normally. Then:

```bash
./qemu-vm.sh eject-iso --name ArchLab
./qemu-vm.sh eject-iso --name ArchLab --execute
./qemu-vm.sh start --name ArchLab --execute
./qemu-vm.sh info --name ArchLab
```

`eject-iso` changes the persistent first CD-ROM only, requires the guest to be
off, and retains the media file. A second driver CD-ROM stays attached. For a
VM created with driver media only, its first CD-ROM is the driver CD-ROM.

These standard commands also work:

```bash
sudo virsh --connect qemu:///system list --all
sudo virsh --connect qemu:///system shutdown ArchLab
sudo virsh --connect qemu:///system dumpxml ArchLab
sudo virsh --connect qemu:///system net-dhcp-leases default
```

## Troubleshooting failed creation

Run `./qemu-vm.sh doctor` first. The revision fixes a reproduced failure where
Arch's `/usr/bin/virt-install` selected a uv-managed Python from `PATH`, then
failed with `ModuleNotFoundError: No module named 'gi'`. The same problem can
occur under sudo when its configured path includes that Python.

For the packaged `/usr/bin/virt-install` and `/usr/bin/virt-fw-vars`, the script
now explicitly uses `/usr/bin/python3 -I`. This keeps their imports with Arch's
installed dependencies and ignores user Python environment overrides. Custom
tool wrappers on `PATH` retain their own invocation. To test the packaged
installer independently:

```bash
/usr/bin/python3 -I /usr/bin/virt-install --version
/usr/bin/python3 -I /usr/bin/virt-install --osinfo list
```

If creation has already failed, inspect its guest registration and retained
files before retrying. For example:

```bash
./qemu-vm.sh info --name AlpineLab
sudo ls -lh -- /var/lib/libvirt/images/AlpineLab
```

An absent libvirt guest can coexist with a retained ISO and disk if creation
failed before registration. A registered guest can also remain after a later
failure. `create` deliberately refuses both existing names and existing guest
directories. It does not resume or delete partial state. Keep those files for
manual recovery, or choose a new name and directory for a separate attempt.

If `/dev/kvm` is missing, check virtualization support, the running kernel, and
device access on the actual host. Containers and restricted environments can
hide KVM even when the host supports it. `doctor` reports this without trying
to load modules or change the environment.

If network startup reports `firewalld can't find the 'libvirt' zone`, check
whether `/usr/lib/firewalld/zones/libvirt.xml` exists. Firewalld may have
started before libvirt installed its zone files. Review runtime versus saved
zones, policies, direct rules and IP sets before validating and reloading:

```bash
sudo firewall-cmd --check-config
sudo firewall-cmd --reload
./qemu-vm.sh network-start --execute
```

A reload loads saved configuration and can discard runtime-only changes.
The script reports this failure without reloading the firewall automatically.
See [firewalld's reload documentation][firewalld-reload].

[firewalld-reload]: https://firewalld.org/documentation/man-pages/firewall-cmd.html

## Validation and limitations

The script asks `virt-install` to generate one persistent boot configuration
with `--import --print-xml --dry-run`, then verifies the name, fresh UUID, KVM
type, disks, ISO paths, Secure Boot template, and TPM settings before registering
it. It verifies the saved libvirt definition again before starting the guest.
The `--dry-run` matters because `--print-xml` alone can create storage. See the
[virt-install manual](https://man.archlinux.org/man/virt-install.1).

An error preserves partially created guest state for inspection and reports
the retained directory, including failures from explicit validation checks.
After a failed creation, inspect the error and retained files before deciding
how to clean up or recover. `create` has no existing-VM reconfiguration or
deletion mode. Manage existing hardware settings through libvirt/virt-manager.

Checks performed during development: Bash syntax, ShellCheck, shfmt, and offline
CLI safety fixtures. The fixture suite uses simulated privilege, libvirt,
package, service, and firmware tools. It also creates and checks a real sparse
qcow2 image in a temporary directory. Optional installed-tool checks invoke the
real packaged installer with a poisoned user Python environment and generate
Linux/Windows XML through libvirt's in-memory test driver. They check the real
argument parser and, when available, the XML schema, without host services or
real guests. The synthetic capability URI is an internal upstream test hook;
these checks establish compatibility with the installed tools, not host boot
support. Tests skip those optional checks if dependencies are unavailable.
Run them with:

```bash
cd ~/my_repos/qemu-vm
python3 -m unittest discover -s tests -v
bash -n qemu-vm.sh lib/menu.sh
shellcheck qemu-vm.sh lib/menu.sh
shfmt -d -i 2 -ci qemu-vm.sh lib/menu.sh
```

Download tests use simulated HTTPS responses, release metadata, transfer
failures, and checksum mismatches. Small official release metadata can be
checked separately without fetching the full ISO.

`qemu-img` enables the disposable disk tests. Host network activation and an
Alpine guest's real ISO boot and graphical connection were verified on
2026-10-23 outside the restricted execution sandbox. Full package installation,
Secure Boot execution and completion of guest OS installation remain untested.
