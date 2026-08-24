#!/usr/bin/env bash

set -e

rime_version=1.17.0
rime_git_hash="33e7814"
sparkle_version=2.6.2

# librime-llm-rerank release artifact (Habit130/librime-llm-rerank), built
# against the librime revision pinned above.
llm_rerank_version="v1.0.2"

# SHA-256 of each downloaded artifact. Verified before extract/copy.
# Regenerate on bump with: shasum -a 256 download/<archive>
rime_sha256="11d8dc663c6ec06d5ccb6111ba664a9e7b631b703ac6acd07cffbac664021850"
rime_deps_sha256="dfe6047e87be271963d7466bd1a6e3d9e660c30e5e73e4bb94e8782c0a6ac8df"
sparkle_sha256="2300a7dc2545a4968e54621b7f351d388ddf1a5cb49e79f6c99e9a09d826f5e8"
llm_rerank_sha256="268e111c7ac2aae9c44ca427c1ef5588c2f54baf197ee1d89678bfa4a2d9aa68"

rime_archive="rime-${rime_git_hash}-macOS-universal.tar.bz2"
rime_download_url="https://github.com/rime/librime/releases/download/${rime_version}/${rime_archive}"

rime_deps_archive="rime-deps-${rime_git_hash}-macOS-universal.tar.bz2"
rime_deps_download_url="https://github.com/rime/librime/releases/download/${rime_version}/${rime_deps_archive}"

sparkle_archive="Sparkle-${sparkle_version}.tar.xz"
sparkle_download_url="https://github.com/sparkle-project/Sparkle/releases/download/${sparkle_version}/${sparkle_archive}"

llm_rerank_archive="librime-llm-rerank.dylib"
llm_rerank_download_url="https://github.com/Habit130/librime-llm-rerank/releases/download/${llm_rerank_version}/${llm_rerank_archive}"

verify_sha256() {
    echo "${1}  ${2}" | shasum -a 256 -c -
}

verify_download_dir() {
    local dir="$1"
    local status=0
    verify_sha256 "${rime_sha256}" "${dir}/${rime_archive}" || status=1
    verify_sha256 "${rime_deps_sha256}" "${dir}/${rime_deps_archive}" || status=1
    verify_sha256 "${sparkle_sha256}" "${dir}/${sparkle_archive}" || status=1
    verify_sha256 "${llm_rerank_sha256}" "${dir}/${llm_rerank_archive}" || status=1
    return "${status}"
}

extract_download_dir() {
    local dir="$1"
    tar --bzip2 -xf "${dir}/${rime_archive}" -C "${dir}"
    tar --bzip2 -xf "${dir}/${rime_deps_archive}" -C "${dir}"
    tar -xJf "${dir}/${sparkle_archive}" -C "${dir}"
}

stage_download_dir() {
    verify_download_dir "$1" || return 1
    extract_download_dir "$1"
}

install_squirrel_deps() {
    mkdir -p download
    if [ -z "${no_download}" ]; then
        curl -L -o "download/${rime_archive}" "${rime_download_url}"
        curl -L -o "download/${rime_deps_archive}" "${rime_deps_download_url}"
        curl -L -o "download/${sparkle_archive}" "${sparkle_download_url}"
        curl -L -o "download/${llm_rerank_archive}" "${llm_rerank_download_url}"
    fi
    stage_download_dir download

    mkdir -p librime/share
    mkdir -p Frameworks
    cp -R download/dist librime/
    cp -R download/share/opencc librime/share/
    cp -R download/Sparkle.framework Frameworks/

    # skip building librime and opencc-data; use downloaded artifacts
    make copy-rime-binaries copy-opencc-data

    mkdir -p lib/rime-plugins
    cp "download/${llm_rerank_archive}" lib/rime-plugins/

    bundled_recipes_file="package/bundled_recipes"
    test -f "${bundled_recipes_file}"
    bundled_recipes=(
        $(grep -vE '^[[:space:]]*(#|$)' "${bundled_recipes_file}")
    )
    echo "bundled recipes: ${bundled_recipes[*]}"

    git submodule update --init plum
    rime_dir=plum/output bash plum/rime-install "${bundled_recipes[@]}"
    make copy-plum-data
}

if [ "${BASH_SOURCE[0]}" = "$0" ]; then
    install_squirrel_deps
fi
