#!/usr/bin/env bash

set -e

rime_version=1.17.0
rime_git_hash="33e7814"
sparkle_version=2.6.2

# librime-llm-rerank release artifact (Habit130/librime-llm-rerank), built
# against the librime revision pinned above. The sha256 is that of the
# universal dylib attached to the release; regenerate it on bump with:
#   shasum -a 256 librime-llm-rerank.dylib
llm_rerank_version="v1.0.2"
llm_rerank_sha256="268e111c7ac2aae9c44ca427c1ef5588c2f54baf197ee1d89678bfa4a2d9aa68"

rime_archive="rime-${rime_git_hash}-macOS-universal.tar.bz2"
rime_download_url="https://github.com/rime/librime/releases/download/${rime_version}/${rime_archive}"

rime_deps_archive="rime-deps-${rime_git_hash}-macOS-universal.tar.bz2"
rime_deps_download_url="https://github.com/rime/librime/releases/download/${rime_version}/${rime_deps_archive}"

sparkle_archive="Sparkle-${sparkle_version}.tar.xz"
sparkle_download_url="https://github.com/sparkle-project/Sparkle/releases/download/${sparkle_version}/${sparkle_archive}"

llm_rerank_archive="librime-llm-rerank.dylib"
llm_rerank_download_url="https://github.com/Habit130/librime-llm-rerank/releases/download/${llm_rerank_version}/${llm_rerank_archive}"

mkdir -p download && (
    cd download
    [ -z "${no_download}" ] && curl -LO "${rime_download_url}"
    tar --bzip2 -xf "${rime_archive}"
    [ -z "${no_download}" ] && curl -LO "${rime_deps_download_url}"
    tar --bzip2 -xf "${rime_deps_archive}"
    [ -z "${no_download}" ] && curl -LO "${sparkle_download_url}"
    tar -xJf "${sparkle_archive}"
    [ -z "${no_download}" ] && curl -LO "${llm_rerank_download_url}"
)

mkdir -p librime/share
mkdir -p Frameworks
cp -R download/dist librime/
cp -R download/share/opencc librime/share/
cp -R download/Sparkle.framework Frameworks/

# skip building librime and opencc-data; use downloaded artifacts
make copy-rime-binaries copy-opencc-data

# librime-llm-rerank is a custom plugin, absent from the official librime
# release; fetch its release artifact and verify the pinned checksum.
echo "${llm_rerank_sha256}  download/${llm_rerank_archive}" | shasum -a 256 -c -
mkdir -p lib/rime-plugins
cp "download/${llm_rerank_archive}" lib/rime-plugins/

echo "SQUIRREL_BUNDLED_RECIPES=${SQUIRREL_BUNDLED_RECIPES}"

git submodule update --init plum
# install Rime recipes
rime_dir=plum/output bash plum/rime-install ${SQUIRREL_BUNDLED_RECIPES}
make copy-plum-data
