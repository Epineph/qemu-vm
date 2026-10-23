# Project context

## Current work

The active checkout is `/home/heini/my_repos/qemu-vm`. The earlier
`/home/heini/qemu-vm` copy is separate. Work in this checkout.

`--help` and the README now include examples for local media, the newest Arch
ISO, installer URLs, Windows/VirtIO, resource limits, and network modes.

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
release metadata, source conflicts, and previews without side effects. All 38
tests passed after integration, along with the static checks below.

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -v
bash -n qemu-vm.sh
shellcheck qemu-vm.sh
shfmt -d -i 2 -ci qemu-vm.sh
ruff check --no-cache tests/test_cli.py
git diff --check
```

The live official metadata and the selected ISO's response headers were checked
on 2026-10-23. Full ISO transfer, privileged host setup, and real VM boot remain
unverified in this work.
