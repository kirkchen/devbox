#!/bin/bash

# Required parameters:
# @raycast.schemaVersion 1
# @raycast.title reconnect wifi
# @raycast.mode compact

# Optional parameters:
# @raycast.icon 🤖

# Documentation:
# @raycast.author kirkchen
# @raycast.authorURL https://raycast.com/kirkchen

# Set variables
ssidName="JKOPay WiFi"
maxRetries=10
counter=0

function get_bssid {
    bssid=$(ioreg -l | grep "IO80211BSSID" | awk -F' = ' '{print $2}' | sed 's/[<>]//g')
    echo "$bssid"
}

function reconnect_wifi {
    echo "Reconnecting to Wi-Fi SSID: $ssidName..."
    networksetup -setairportpower en0 off
    sleep 3
    networksetup -setairportpower en0 on
    sleep 5
    networksetup -setairportnetwork en0 "$ssidName"
    sleep 5
}

# 1. Get the current BSSID
currentBSSID=$(get_bssid)

if [ -z "$currentBSSID" ]; then
    echo "Initial BSSID could not be retrieved, exiting script." >&2
    exit 1
fi

echo "Current BSSID: $currentBSSID"

while [ $counter -lt $maxRetries ]; do
    # 2. Reconnect Wi-Fi
    reconnect_wifi

    # 3. Get the new BSSID
    newBSSID=$(get_bssid)

    if [ -z "$newBSSID" ]; then
        echo "Unable to retrieve the new BSSID, exiting script." >&2
        exit 1
    fi

    echo "New BSSID: $newBSSID"

    # 4. Check if BSSID has changed
    if [ "$currentBSSID" != "$newBSSID" ]; then
        echo "BSSID has changed, exiting script."
        exit 0
    else
        counter=$((counter + 1))
        echo "BSSID has not changed, retrying $counter of $maxRetries times..."
    fi
done

# 5. If BSSID has not changed after maximum retries, print a message
echo "Please contact IT support." >&2
exit 1
