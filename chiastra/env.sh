#!/bin/bash
export THIS_MACHINE=$(hostname -I | awk '{print $1}')
export GOOGLE_CLOUD_PROJECT="chiastra26"
export CHIASTRA_BOOM_CONFIG=MegaBoomV3Config
export CHIASTRA_GEMINI_MODEL=gemini-3.5-flash-lite
export CHIASTRA_BUILD_TIMEOUT=3600
export CHIASTRA_MAKE_JOBS=32
export REPORT_PATH="$PWD/output/boom_cache_report.md"