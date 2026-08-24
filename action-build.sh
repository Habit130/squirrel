#!/usr/bin/env bash

set -e

target="${1:-release}"

export ARCHS='arm64 x86_64'
export BUILD_UNIVERSAL=1

./action-install.sh

# build dependencies
# make deps

# build Squirrel
make "${target}"

echo 'Installer package:'
find package -type f -name '*.pkg' -or -name '*.zip'
