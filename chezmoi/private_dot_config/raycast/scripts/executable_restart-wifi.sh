#!/bin/bash

# Required parameters:
# @raycast.schemaVersion 1
# @raycast.title restart wifi
# @raycast.mode compact

# Optional parameters:
# @raycast.icon 🤖

# Documentation:
# @raycast.description restart wifi
# @raycast.author jamis_liao
# @raycast.authorURL https://raycast.com/jamis_liao
networksetup -setairportpower Wi-Fi off
networksetup -setairportpower Wi-Fi on
echo Successed restart wifi
