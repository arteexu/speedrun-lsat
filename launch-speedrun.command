#!/bin/bash
cd "$(dirname "$0")"
export ANKI_BASE="$PWD/.ankidata"
exec ./run
