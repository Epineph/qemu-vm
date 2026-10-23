#!/usr/bin/env bash
# Guided terminal workflow. Source this file from qemu-vm.sh.

# ---------------------------------------------------------------------------
# Prompts and isolated CLI actions
# ---------------------------------------------------------------------------

function menu_read() {
  local variable=$1 prompt=$2 default=${3:-} menu_value=''
  printf '%s' "$prompt"
  if [[ -t 0 ]]; then
    IFS= read -e -r menu_value || return 1
  else
    IFS= read -r menu_value || return 1
  fi
  printf -v "$variable" '%s' "${menu_value:-$default}"
}

function menu_confirm() {
  local answer=''
  menu_read answer "$1 [y/N]: " || return 1
  [[ "${answer,,}" == y || "${answer,,}" == yes ]]
}

function menu_run_command() {
  local script_path=$1
  shift
  # A fresh process retains its own errexit and guest defaults. Calling main
  # in an if-condition would disable errexit throughout its shell functions.
  if bash "$script_path" "$@"; then
    return 0
  else
    printf '\nThat operation failed. Read the first Error above.\n' >&2
    printf 'Existing guest files have been kept. Returning to the menu.\n' >&2
    return 1
  fi
}

function menu_iso_path() {
  local variable=$1 source_path=''
  printf 'Paste the full ISO path. Enclosing quotes are accepted.\n'
  printf 'Blank input returns to the menu.\n'
  while true; do
    menu_read source_path 'Installer ISO path: ' || return 1
    [[ -n "$source_path" ]] || return 1
    # Accept a quoted pasted filename without evaluating shell expressions.
    if ((${#source_path} >= 2)) &&
      [[ "$source_path" == \"*\" || "$source_path" == \'*\' ]]; then
      source_path=${source_path:1:${#source_path}-2}
    fi
    if [[ "$source_path" == \~/* ]]; then
      source_path="$HOME/${source_path:2}"
    fi
    if [[ -f "$source_path" && -r "$source_path" && -s "$source_path" &&
      "${source_path,,}" == *.iso ]]; then
      printf -v "$variable" '%s' "$source_path"
      return 0
    fi
    printf 'Choose a readable, nonempty file ending in .iso.\n' >&2
  done
}

# ---------------------------------------------------------------------------
# Guided creation and existing guest display
# ---------------------------------------------------------------------------

function menu_create() {
  local script_path=$1 guest_choice='' source_choice='' iso_path='' url=''
  local guest=linux name='' memory=4096 vcpus=2 disk=64 setup=0
  local source_label='' plan='' confirmation=''
  local -a arguments=(create --no-start)
  printf '\nCreate a VM and attach its installer ISO\n'
  printf 'The VM display opens the installer after creation.\n'
  menu_read guest_choice 'Guest: 1) Linux  2) Windows [1]: ' 1 || return 0
  case "$guest_choice" in
    1) ;;
    2)
      guest=windows
      memory=8192
      vcpus=4
      disk=128
      ;;
    *)
      printf 'Choose Linux or Windows from the menu.\n' >&2
      return 0
      ;;
  esac
  arguments+=(--guest "$guest")
  printf '\nInstaller source:\n'
  printf '  1) ISO file already downloaded\n'
  printf '  2) Download the latest Arch Linux ISO\n'
  printf '  3) Download from an HTTPS URL\n'
  menu_read source_choice 'Source [1]: ' 1 || return 0
  case "$source_choice" in
    1)
      menu_iso_path iso_path || return 0
      arguments+=(--iso "$iso_path")
      source_label=$iso_path
      ;;
    2)
      if [[ "$guest" != linux ]]; then
        printf 'The Arch Linux installer requires choosing Linux.\n' >&2
        return 0
      fi
      arguments+=(--arch-latest)
      source_label='Latest official Arch Linux ISO (download)'
      ;;
    3)
      menu_read url 'Direct HTTPS installer URL (blank to cancel): ' || return 0
      [[ -n "$url" ]] || return 0
      arguments+=(--iso-url "$url")
      source_label=$url
      ;;
    *)
      printf 'Choose installer source 1, 2 or 3.\n' >&2
      return 0
      ;;
  esac
  printf '\nUse a NEW name; previous failed attempts may retain that name\n'
  printf 'as a storage folder. Existing files are never deleted here.\n'
  menu_read name 'New VM name (blank to cancel): ' || return 0
  [[ -n "$name" ]] || return 0
  menu_read memory "RAM in MiB [$memory]: " "$memory" || return 0
  menu_read vcpus "CPU count [$vcpus]: " "$vcpus" || return 0
  menu_read disk "Disk capacity in GiB [$disk]: " "$disk" || return 0
  arguments+=(--name "$name" --memory "$memory" --vcpus "$vcpus"
    --disk-size "$disk")
  printf '\nHost setup installs dependencies, performs a full Arch upgrade,\n'
  printf 'and enables libvirt plus its default network.\n'
  if menu_confirm 'Include host setup before creation?'; then
    arguments+=(--setup --with-manager)
    setup=1
  fi
  # Validate through the ordinary CLI, but keep its raw command preview out of
  # the guided screen. Preserve that output if validation reports a problem.
  if ! plan=$(menu_run_command "$script_path" "${arguments[@]}" 2>&1); then
    printf '%s\n' "$plan" >&2
    return 0
  fi
  if ((setup == 0)); then
    if ! plan=$(menu_run_command "$script_path" network-start 2>&1); then
      printf '%s\n' "$plan" >&2
      return 0
    fi
  fi
  printf '\nReady to create:\n'
  printf '  Name: %s\n  Guest: %s\n' "$name" "$guest"
  printf '  Installer: %s\n' "$source_label"
  printf '  RAM: %s MiB; CPUs: %s; disk: %s GiB\n' "$memory" "$vcpus" "$disk"
  printf '  Attach the ISO and create the VM powered off.\n'
  printf '  Enable the default VM network now and at host startup.\n'
  if ((setup)); then
    printf '  Run host setup, including the full Arch package upgrade.\n'
  fi
  confirmation='Enable the default VM network and create this VM now?'
  if ! menu_confirm "$confirmation"; then
    printf 'Creation cancelled; no VM was created.\n'
    return 0
  fi
  if ((setup == 0)); then
    if ! menu_run_command "$script_path" network-start --execute; then
      return 0
    fi
  fi
  if ! menu_run_command "$script_path" "${arguments[@]}" --execute; then
    return 0
  fi
  printf '\nVM created. Its installer ISO is attached.\n'
  if menu_confirm 'Start the VM and open its installer window?'; then
    menu_run_command "$script_path" connect --name "$name" --execute || true
  fi
}

function menu_connect() {
  local script_path=$1 names='' name='' choice='' index=0
  local -a privileges=() guests=()
  if ((EUID != 0)); then privileges=(sudo --); fi
  printf '\nExisting VMs:\n'
  if ! names=$("${privileges[@]}" virsh --connect qemu:///system \
    list --all --name); then
    printf 'Cannot list VMs. Choose Check host or Setup host from the menu.\n' >&2
    return 0
  fi
  while IFS= read -r name; do
    [[ -z "$name" ]] || guests+=("$name")
  done <<<"$names"
  if ((${#guests[@]} == 0)); then
    printf 'No VM is registered. Choose Create a VM first.\n'
    return 0
  fi
  for name in "${guests[@]}"; do
    index=$((index + 1))
    printf '  %s) %s\n' "$index" "$name"
  done
  menu_read choice 'VM number (blank to cancel): ' || return 0
  [[ -n "$choice" ]] || return 0
  if [[ ! "$choice" =~ ^[1-9][0-9]{0,5}$ ]] ||
    ((choice > ${#guests[@]})); then
    printf 'Choose one of the displayed VM numbers.\n' >&2
    return 0
  fi
  name=${guests[choice - 1]}
  if menu_confirm "Start $name if needed and open its display?"; then
    menu_run_command "$script_path" connect --name "$name" --execute || true
  fi
}

function menu_setup() {
  local script_path=$1
  menu_run_command "$script_path" setup --with-manager || return 0
  printf '\nSetup performs a full Arch package upgrade and enables libvirt\n'
  printf 'and its default network. Pacman also asks for confirmation.\n'
  if menu_confirm 'Apply host setup?'; then
    menu_run_command "$script_path" setup --with-manager --execute || true
  fi
}

function menu_network() {
  local script_path=$1
  menu_run_command "$script_path" network-start || return 0
  if menu_confirm 'Enable the default VM network?'; then
    menu_run_command "$script_path" network-start --execute || true
  fi
}

# ---------------------------------------------------------------------------
# Main menu
# ---------------------------------------------------------------------------

function interactive_menu() {
  local script_path=$1 choice=''
  if [[ ! -t 0 || ! -t 1 ]]; then
    printf 'The menu needs an interactive terminal. Run: %s menu\n' \
      "$script_path" >&2
    return 1
  fi
  printf 'QEMU VM guide\n'
  printf 'An ISO is installer media attached to a VM. Open the VM display\n'
  printf 'to use that installer.\n'
  while true; do
    printf '\n  1) Create a VM from an installer ISO\n'
    printf '  2) Start a VM and open its display\n'
    printf '  3) Check host\n'
    printf '  4) Setup host\n'
    printf '  5) Enable default VM network\n'
    printf '  0) Exit\n'
    menu_read choice 'Choose [0]: ' 0 || return 0
    case "$choice" in
      1) menu_create "$script_path" ;;
      2) menu_connect "$script_path" ;;
      3) menu_run_command "$script_path" doctor || true ;;
      4) menu_setup "$script_path" ;;
      5) menu_network "$script_path" ;;
      0) return 0 ;;
      *) printf 'Choose 0, 1, 2, 3, 4 or 5.\n' >&2 ;;
    esac
  done
}
