#!/usr/bin/env bash
################################################################################
# tests/deploy/test_set_boot_screen.sh — set-boot-screen.sh behavioural catalog
#
# Verifies deploy/set-boot-screen.sh (US-885-b / F-139) against a fixture
# /boot/firmware (config.txt, cmdline.txt, initramfs_2712, initramfs8), a
# fixture plymouthd.conf and themes dir, and PATH stubs for
# plymouth-set-default-theme and lsinitramfs. Runs entirely on the dev
# workstation -- no Pi, no real boot partition, no real initramfs.
#
# The plymouth-set-default-theme stub emulates the real tool: `-R <theme>`
# writes Theme=<theme> into the fixture plymouthd.conf and "rebuilds" both
# initramfs files as a listing that names themes/<theme>. Before doing so it
# logs whether a cmp-equal set-boot-screen .bak of each initramfs existed at
# the moment it was called. The lsinitramfs stub cats the file it is given.
#
# Usage:
#   bash tests/deploy/test_set_boot_screen.sh
#
# Exit codes:
#   0  - all assertions passed
#   1  - one or more assertions failed
################################################################################

set -u

SELF_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SELF_DIR/../.." && pwd)"
SCRIPT="$REPO_ROOT/deploy/set-boot-screen.sh"
MODE_SCRIPT="$REPO_ROOT/deploy/set-display-mode.sh"
THEME_REPO="$REPO_ROOT/deploy/plymouth/eclipse"

PASS=0
FAIL=0

# ---- helpers ----

assert_rc() {
    local desc="$1" expected="$2" got="$3"
    if [ "$got" = "$expected" ]; then
        echo "  PASS: $desc (rc=$got)"
        PASS=$((PASS + 1))
    else
        echo "  FAIL: $desc (expected rc=$expected, got=$got)"
        FAIL=$((FAIL + 1))
    fi
}

assert_nonzero() {
    local desc="$1" got="$2"
    if [ "$got" != "0" ]; then
        echo "  PASS: $desc (rc=$got)"
        PASS=$((PASS + 1))
    else
        echo "  FAIL: $desc (expected a non-zero exit, got 0)"
        FAIL=$((FAIL + 1))
    fi
}

assert_eq() {
    local desc="$1" expected="$2" got="$3"
    if [ "$got" = "$expected" ]; then
        echo "  PASS: $desc"
        PASS=$((PASS + 1))
    else
        echo "  FAIL: $desc"
        echo "         expected: $expected"
        echo "         got:      $got"
        FAIL=$((FAIL + 1))
    fi
}

assert_files_identical() {
    local desc="$1" a="$2" b="$3"
    if cmp -s "$a" "$b"; then
        echo "  PASS: $desc"
        PASS=$((PASS + 1))
    else
        echo "  FAIL: $desc (files differ)"
        diff "$a" "$b" | head -10
        FAIL=$((FAIL + 1))
    fi
}

assert_true() {
    local desc="$1"
    shift
    if "$@"; then
        echo "  PASS: $desc"
        PASS=$((PASS + 1))
    else
        echo "  FAIL: $desc"
        FAIL=$((FAIL + 1))
    fi
}

# True if TOKEN is one whole token on FILE's first line.
has_token() {
    local file="$1" token="$2" word
    for word in $(head -1 "$file"); do
        [ "$word" = "$token" ] && return 0
    done
    return 1
}

lacks_token() { ! has_token "$@"; }

# The effective disable_splash value (last one in an applicable section).
effective_disable_splash() {
    awk '
        { t = $0; sub(/^[ \t]+/, "", t); sub(/[ \t\r]+$/, "", t) }
        t ~ /^\[/ { section = tolower(t); next }
        (section == "" || section == "[all]" || section == "[pi5]") && t ~ /^disable_splash[ \t]*=/ {
            v = t; sub(/^disable_splash[ \t]*=[ \t]*/, "", v); last = v
        }
        END { print last }
    ' "$1"
}

# Count of -R calls the stub received.
r_calls() { grep -c '^-R ' "$STUB_LOG" 2>/dev/null || true; }

# Count of set-boot-screen .bak files for one initramfs name.
bak_count() {
    local n=0 f
    for f in "$FW/$1".bak-boot-screen-*; do
        [ -f "$f" ] && n=$((n + 1))
    done
    echo "$n"
}

WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

STUB_BIN="$WORK/bin"
FAIL_CMP_BIN="$WORK/failcmp"
mkdir -p "$STUB_BIN" "$FAIL_CMP_BIN"

cat > "$STUB_BIN/plymouth-set-default-theme" <<'STUB'
#!/usr/bin/env bash
echo "$*" >> "$STUB_LOG"
for f in initramfs_2712 initramfs8; do
    ok=no
    for b in "$PI_BOOT_FIRMWARE_DIR/$f".bak-boot-screen-*; do
        [ -f "$b" ] && cmp -s "$b" "$PI_BOOT_FIRMWARE_DIR/$f" && ok=yes
    done
    echo "bak:$f:$ok" >> "$STUB_LOG"
done
[ "$1" = "-R" ] || exit 2
# A failed rebuild may already have copied a half-built image (Atlas P3).
if [ "${STUB_RC:-0}" != "0" ]; then
    printf 'half-built\n' > "$PI_BOOT_FIRMWARE_DIR/initramfs_2712"
    printf 'half-built\n' > "$PI_BOOT_FIRMWARE_DIR/initramfs8"
    exit "$STUB_RC"
fi
printf '[Daemon]\nTheme=%s\n' "$2" > "$PI_PLYMOUTHD_CONF"
for f in initramfs_2712 initramfs8; do
    printf 'usr/lib/plymouth/script.so\nusr/share/plymouth/themes/%s/%s.plymouth\n' "$2" "$2" \
        > "$PI_BOOT_FIRMWARE_DIR/$f"
done
exit 0
STUB

cat > "$STUB_BIN/lsinitramfs" <<'STUB'
#!/usr/bin/env bash
cat "$1"
STUB

cat > "$FAIL_CMP_BIN/cmp" <<'STUB'
#!/usr/bin/env bash
exit 1
STUB

chmod +x "$STUB_BIN"/* "$FAIL_CMP_BIN"/*

PRISTINE_CMDLINE='console=serial0,115200 console=tty1 root=PARTUUID=13c15a4b-02 rootfstype=ext4 fsck.repair=yes rootwait quiet splash plymouth.ignore-serial-consoles cfg80211.ieee80211_regdom=US'

# A fresh fixture boot dir + plymouth tree. $1 = the plymouthd.conf Theme=.
setup() {
    local theme="${1:-pix}"
    rm -rf "$WORK/case"
    FW="$WORK/case/boot/firmware"
    THEMES="$WORK/case/usr/share/plymouth/themes"
    CONF="$WORK/case/etc/plymouth/plymouthd.conf"
    THEME_SRC="$WORK/case/theme-src"
    STUB_LOG="$WORK/case/stub.log"
    DRM="$WORK/case/drm"
    mkdir -p "$FW" "$THEMES/pix" "$(dirname "$CONF")" "$THEME_SRC"
    cp "$THEME_REPO"/* "$THEME_SRC/"
    printf '[Daemon]\nTheme=%s\n' "$theme" > "$CONF"
    printf '%s\n' "$PRISTINE_CMDLINE" > "$FW/cmdline.txt"
    printf '%s\n' \
        '# For more options and information see' \
        'dtparam=audio=on' \
        'auto_initramfs=1' \
        'dtoverlay=vc4-kms-v3d' \
        '' \
        '[cm4]' \
        'otg_mode=1' \
        '' \
        '[all]' \
        'dtparam=rtc_bbat_vchg=3000000' > "$FW/config.txt"
    printf 'usr/lib/plymouth/script.so\nusr/share/plymouth/themes/pix/pix.plymouth\n' > "$FW/initramfs_2712"
    printf 'usr/lib/plymouth/script.so\nusr/share/plymouth/themes/pix/pix.plymouth\n' > "$FW/initramfs8"
    : > "$STUB_LOG"
    # A panel advertising 480x320, so set-display-mode.sh writes its video= pin.
    mkdir -p "$DRM/card1-HDMI-A-1" "$DRM/card1-HDMI-A-2"
    printf 'connected\n' > "$DRM/card1-HDMI-A-1/status"
    printf '480x320\n640x480' > "$DRM/card1-HDMI-A-1/modes"
    printf 'disconnected\n' > "$DRM/card1-HDMI-A-2/status"
    : > "$DRM/card1-HDMI-A-2/modes"
    cp "$FW/config.txt" "$WORK/case/config.before"
    cp "$FW/cmdline.txt" "$WORK/case/cmdline.before"
    cp "$FW/initramfs_2712" "$WORK/case/initramfs_2712.before"
    cp "$FW/initramfs8" "$WORK/case/initramfs8.before"
}

# Run set-boot-screen.sh against the fixture. Extra args pass through.
run_bs() {
    PATH="$STUB_BIN:$PATH" \
    STUB_LOG="$STUB_LOG" \
    PI_BOOT_FIRMWARE_DIR="$FW" \
    PI_PLYMOUTHD_CONF="$CONF" \
    PI_PLYMOUTH_THEMES_DIR="$THEMES" \
    ECLIPSE_PLYMOUTH_THEME_SRC="$THEME_SRC" \
        bash "$SCRIPT" "$@" > "$WORK/case/out.txt" 2>&1
}

run_mode() {
    PI_DRM_DIR="$DRM" \
    PI_CMDLINE_TXT="$FW/cmdline.txt" \
    PI_FB_SIZE_FILE="$WORK/case/no-such-fb" \
        bash "$MODE_SCRIPT" > "$WORK/case/mode-out.txt" 2>&1
}

# ---- 1. apply on a fixture boot dir ----

echo "--- 1. apply: config, tokens, theme, rebuild ---"
setup pix
run_bs; rc=$?
assert_rc "apply exits 0" 0 "$rc"
assert_eq "disable_splash=1 is effective" "1" "$(effective_disable_splash "$FW/config.txt")"
assert_true "loglevel=3 present" has_token "$FW/cmdline.txt" "loglevel=3"
assert_true "vt.global_cursor_default=0 present" has_token "$FW/cmdline.txt" "vt.global_cursor_default=0"
assert_true "console=tty1 removed" lacks_token "$FW/cmdline.txt" "console=tty1"
assert_true "console=serial0,115200 kept (whole-token compare)" has_token "$FW/cmdline.txt" "console=serial0,115200"
assert_true "root= preserved" has_token "$FW/cmdline.txt" "root=PARTUUID=13c15a4b-02"
assert_eq "cmdline.txt still one line" "1" "$(wc -l < "$FW/cmdline.txt" | tr -d ' ')"
assert_true "theme installed byte-identical" diff -r -q "$THEME_REPO" "$THEMES/eclipse"
assert_eq "stub called once, with -R eclipse" "-R eclipse" "$(grep '^-R ' "$STUB_LOG")"
assert_eq "initramfs_2712 .bak cmp-equal existed when -R ran" "1" "$(grep -c '^bak:initramfs_2712:yes' "$STUB_LOG")"
assert_eq "initramfs8 .bak cmp-equal existed when -R ran" "1" "$(grep -c '^bak:initramfs8:yes' "$STUB_LOG")"
assert_eq "one initramfs_2712 .bak" "1" "$(bak_count initramfs_2712)"
assert_eq "one initramfs8 .bak" "1" "$(bak_count initramfs8)"
for b in "$FW"/initramfs_2712.bak-boot-screen-*; do
    assert_files_identical "initramfs_2712 .bak equals the pre-install file" "$WORK/case/initramfs_2712.before" "$b"
done
for b in "$FW"/initramfs8.bak-boot-screen-*; do
    assert_files_identical "initramfs8 .bak equals the pre-install file" "$WORK/case/initramfs8.before" "$b"
done
assert_eq "prior theme recorded beside the backup" "pix" "$(cat "$FW/eclipse-boot-screen.prior-theme" 2>/dev/null)"
assert_true "initramfs now carries themes/eclipse" grep -q themes/eclipse "$FW/initramfs_2712"
assert_true "the [cm4] line is untouched" grep -qx 'otg_mode=1' "$FW/config.txt"

# ---- 2. apply then set-display-mode, and the reverse order ----

echo "--- 2. union of tokens in either order ---"
setup pix
run_bs; rcA=$?
run_mode; rcB=$?
assert_rc "boot-screen first exits 0" 0 "$rcA"
assert_rc "display-mode second exits 0" 0 "$rcB"
orderA="$(tr ' ' '\n' < "$FW/cmdline.txt" | sort | tr '\n' ' ')"
assert_true "A: video= pinned" has_token "$FW/cmdline.txt" "video=HDMI-A-1:480x320"
assert_true "A: loglevel=3 present" has_token "$FW/cmdline.txt" "loglevel=3"
assert_true "A: console=tty1 absent" lacks_token "$FW/cmdline.txt" "console=tty1"

setup pix
run_mode; rcB=$?
run_bs; rcA=$?
assert_rc "display-mode first exits 0" 0 "$rcB"
assert_rc "boot-screen second exits 0" 0 "$rcA"
orderB="$(tr ' ' '\n' < "$FW/cmdline.txt" | sort | tr '\n' ' ')"
assert_true "B: video= pinned" has_token "$FW/cmdline.txt" "video=HDMI-A-1:480x320"
assert_true "B: vt.global_cursor_default=0 present" has_token "$FW/cmdline.txt" "vt.global_cursor_default=0"
assert_eq "both orders give the same token set" "$orderA" "$orderB"

# ---- 3. apply then --revert ----

echo "--- 3. apply then --revert restores both files byte-identical ---"
setup pix
run_bs
run_bs --revert; rc=$?
assert_rc "revert exits 0" 0 "$rc"
assert_files_identical "config.txt byte-identical after revert" "$WORK/case/config.before" "$FW/config.txt"
assert_files_identical "cmdline.txt byte-identical after revert" "$WORK/case/cmdline.before" "$FW/cmdline.txt"
assert_eq "revert rebuilt with the recorded prior theme" "-R pix" "$(grep '^-R ' "$STUB_LOG" | tail -1)"
assert_eq "revert took its backups before -R (2712)" "2" "$(grep -c '^bak:initramfs_2712:yes' "$STUB_LOG")"
assert_eq "revert took its backups before -R (8)" "2" "$(grep -c '^bak:initramfs8:yes' "$STUB_LOG")"
assert_true "installed eclipse theme removed" test ! -e "$THEMES/eclipse"
assert_true "prior-theme record removed" test ! -e "$FW/eclipse-boot-screen.prior-theme"
if grep -q themes/eclipse "$FW/initramfs_2712"; then
    echo "  FAIL: initramfs still carries themes/eclipse after revert"; FAIL=$((FAIL + 1))
else
    echo "  PASS: initramfs no longer carries themes/eclipse"; PASS=$((PASS + 1))
fi
assert_eq "one .bak pair kept after revert" "1 1" "$(bak_count initramfs_2712) $(bak_count initramfs8)"

echo "--- 3b. apply, set-display-mode, revert: only the boot-screen tokens go ---"
setup pix
run_mode
cp "$FW/cmdline.txt" "$WORK/mode-only"
setup pix
run_bs
run_mode
run_bs --revert; rc=$?
assert_rc "revert exits 0" 0 "$rc"
assert_files_identical "cmdline equals the display-mode-only result" "$WORK/mode-only" "$FW/cmdline.txt"

echo "--- 3c. a pre-existing loglevel=3 is the operator's: revert keeps it ---"
setup pix
printf '%s loglevel=3\n' "$PRISTINE_CMDLINE" > "$FW/cmdline.txt"
cp "$FW/cmdline.txt" "$WORK/case/cmdline.before"
run_bs
run_bs --revert
assert_files_identical "cmdline byte-identical, operator loglevel=3 kept" "$WORK/case/cmdline.before" "$FW/cmdline.txt"

echo "--- 3d. config ending inside [cm4]: [all] opened, revert byte-identical ---"
setup pix
printf '[cm4]\notg_mode=1' > "$FW/config.txt"
cp "$FW/config.txt" "$WORK/case/config.before"
run_bs; rc=$?
assert_rc "apply exits 0" 0 "$rc"
assert_eq "disable_splash=1 effective despite the [cm4] tail" "1" "$(effective_disable_splash "$FW/config.txt")"
run_bs --revert
assert_files_identical "config.txt byte-identical (no trailing newline kept)" "$WORK/case/config.before" "$FW/config.txt"

echo "--- 3e. an effective disable_splash=1 already present: config untouched ---"
setup pix
printf '[all]\ndisable_splash=1\n' >> "$FW/config.txt"
cp "$FW/config.txt" "$WORK/case/config.before"
run_bs
assert_files_identical "config.txt untouched by apply" "$WORK/case/config.before" "$FW/config.txt"
run_bs --revert
assert_files_identical "config.txt untouched by revert" "$WORK/case/config.before" "$FW/config.txt"

# ---- 4. apply twice ----

echo "--- 4. second apply takes no backup and makes no -R call ---"
setup pix
run_bs
cp "$FW/config.txt" "$WORK/case/config.after1"
cp "$FW/cmdline.txt" "$WORK/case/cmdline.after1"
run_bs; rc=$?
assert_rc "second apply exits 0" 0 "$rc"
assert_eq "stub -R call count 1" "1" "$(r_calls)"
assert_eq "still one .bak pair" "1 1" "$(bak_count initramfs_2712) $(bak_count initramfs8)"
assert_files_identical "config.txt unchanged by the second apply" "$WORK/case/config.after1" "$FW/config.txt"
assert_files_identical "cmdline.txt unchanged by the second apply" "$WORK/case/cmdline.after1" "$FW/cmdline.txt"

echo "--- 4b. the initramfs lost the theme (kernel update): rebuild ---"
printf 'usr/share/plymouth/themes/pix/pix.plymouth\n' > "$FW/initramfs_2712"
run_bs; rc=$?
assert_rc "apply exits 0" 0 "$rc"
assert_eq "stub -R call count 2" "2" "$(r_calls)"

# ---- 5. retention ----

echo "--- 5. three applies, asset changed before each: one pair remains ---"
setup pix
printf 'foreign-2712\n' > "$FW/initramfs_2712.bak-6.18.29-claude"
printf 'foreign-8\n' > "$FW/initramfs8.bak-6.18.29-claude"
cp "$FW/initramfs_2712.bak-6.18.29-claude" "$WORK/case/foreign-2712"
cp "$FW/initramfs8.bak-6.18.29-claude" "$WORK/case/foreign-8"
for i in 1 2 3; do
    printf '\n# asset change %s\n' "$i" >> "$THEME_SRC/eclipse.script"
    run_bs; rc=$?
    assert_rc "apply $i exits 0" 0 "$rc"
done
assert_eq "three rebuilds" "3" "$(r_calls)"
assert_eq "exactly one set-boot-screen .bak pair" "1 1" "$(bak_count initramfs_2712) $(bak_count initramfs8)"
assert_files_identical "foreign initramfs_2712 .bak untouched" "$WORK/case/foreign-2712" "$FW/initramfs_2712.bak-6.18.29-claude"
assert_files_identical "foreign initramfs8 .bak untouched" "$WORK/case/foreign-8" "$FW/initramfs8.bak-6.18.29-claude"
assert_true "installed theme follows the changed asset" cmp -s "$THEME_SRC/eclipse.script" "$THEMES/eclipse/eclipse.script"

# ---- 6. a failed rebuild ----

echo "--- 6. -R exits 1: both initramfs restored, script exits non-zero ---"
setup pix
STUB_RC=1 run_bs; rc=$?
assert_nonzero "apply exits non-zero" "$rc"
assert_files_identical "initramfs_2712 byte-identical to before" "$WORK/case/initramfs_2712.before" "$FW/initramfs_2712"
assert_files_identical "initramfs8 byte-identical to before" "$WORK/case/initramfs8.before" "$FW/initramfs8"
assert_true "failure reported loudly" grep -q 'ERROR' "$WORK/case/out.txt"

# ---- 7. backups before -R; a failing cmp never reaches -R ----

echo "--- 7. a failing cmp aborts with nothing changed and no -R call ---"
setup pix
PATH="$FAIL_CMP_BIN:$PATH" run_bs; rc=$?
assert_nonzero "apply exits non-zero" "$rc"
assert_eq "stub never called" "0" "$(r_calls)"
assert_files_identical "config.txt unchanged" "$WORK/case/config.before" "$FW/config.txt"
assert_files_identical "cmdline.txt unchanged" "$WORK/case/cmdline.before" "$FW/cmdline.txt"
assert_files_identical "initramfs_2712 unchanged" "$WORK/case/initramfs_2712.before" "$FW/initramfs_2712"
assert_eq "no .bak left behind" "0 0" "$(bak_count initramfs_2712) $(bak_count initramfs8)"
assert_true "no theme installed" test ! -e "$THEMES/eclipse"
assert_true "no prior-theme record" test ! -e "$FW/eclipse-boot-screen.prior-theme"

echo "--- 7b. a missing initramfs8 aborts with nothing changed ---"
setup pix
rm -f "$FW/initramfs8"
run_bs; rc=$?
assert_nonzero "apply exits non-zero" "$rc"
assert_eq "stub never called" "0" "$(r_calls)"
assert_files_identical "cmdline.txt unchanged" "$WORK/case/cmdline.before" "$FW/cmdline.txt"

# ---- 8. revert's theme choice ----

echo "--- 8. revert uses the recorded prior theme, pix without a record ---"
setup spinner
run_bs
assert_eq "recorded prior theme" "spinner" "$(cat "$FW/eclipse-boot-screen.prior-theme" 2>/dev/null)"
run_bs --revert
assert_eq "revert rebuilds with -R spinner" "-R spinner" "$(grep '^-R ' "$STUB_LOG" | tail -1)"

setup pix
run_bs
rm -f "$FW/eclipse-boot-screen.prior-theme"
: > "$STUB_LOG"
run_bs --revert; rc=$?
assert_rc "revert without a record exits 0" 0 "$rc"
assert_eq "no record: -R pix" "-R pix" "$(grep '^-R ' "$STUB_LOG")"
assert_eq "no record: backups taken before -R" "bak:initramfs_2712:yes" "$(grep '^bak:initramfs_2712' "$STUB_LOG")"

# ---- 9. usage ----

echo "--- 9. an unknown argument is a usage error, nothing written ---"
setup pix
run_bs --bogus; rc=$?
assert_rc "unknown argument exits 1" 1 "$rc"
assert_eq "stub never called" "0" "$(r_calls)"
assert_files_identical "cmdline.txt unchanged" "$WORK/case/cmdline.before" "$FW/cmdline.txt"

echo
echo "=== Results: $PASS passed, $FAIL failed ==="
[ "$FAIL" -eq 0 ]
