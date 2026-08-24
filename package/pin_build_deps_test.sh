#!/usr/bin/env bash

set -euo pipefail

root="$(cd "$(dirname "$0")/.." && pwd)"
# shellcheck source=../action-install.sh
source "${root}/action-install.sh"

tmpdir="$(mktemp -d)"
trap 'rm -rf "${tmpdir}"' EXIT

mkdir -p "${tmpdir}/bin"
cat > "${tmpdir}/bin/tar" <<'EOF'
#!/bin/sh
echo called >> "$(dirname "$0")/../tar.called"
exit 97
EOF
chmod +x "${tmpdir}/bin/tar"

echo rime > "${tmpdir}/${rime_archive}"
echo deps > "${tmpdir}/${rime_deps_archive}"
echo sparkle > "${tmpdir}/${sparkle_archive}"
echo plugin > "${tmpdir}/${llm_rerank_archive}"

rime_sha256="0000000000000000000000000000000000000000000000000000000000000000"
rime_deps_sha256="$(shasum -a 256 "${tmpdir}/${rime_deps_archive}" | awk '{print $1}')"
sparkle_sha256="$(shasum -a 256 "${tmpdir}/${sparkle_archive}" | awk '{print $1}')"
llm_rerank_sha256="$(shasum -a 256 "${tmpdir}/${llm_rerank_archive}" | awk '{print $1}')"

export PATH="${tmpdir}/bin:${PATH}"

set +e
output="$(stage_download_dir "${tmpdir}" 2>&1)"
status=$?
set -e

if [ "${status}" -eq 0 ]; then
    echo "expected checksum mismatch to fail" >&2
    echo "${output}" >&2
    exit 1
fi
if [ -e "${tmpdir}/tar.called" ]; then
    echo "extract ran after checksum mismatch" >&2
    echo "${output}" >&2
    exit 1
fi
printf '%s\n' "${output}" | grep -q FAILED

rime_sha256="$(shasum -a 256 "${tmpdir}/${rime_archive}" | awk '{print $1}')"
set +e
stage_download_dir "${tmpdir}" >/dev/null 2>&1
set -e
if [ ! -e "${tmpdir}/tar.called" ]; then
    echo "extract was not reached after matching checksums" >&2
    exit 1
fi

echo "ok: checksum mismatch fails before extract"
