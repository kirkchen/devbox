#!/bin/bash
# List all project directories under ~/Code and ~/Code/Personal
find "$HOME/Code" -mindepth 1 -maxdepth 1 -type d -not -name Personal
find "$HOME/Code/Personal" -mindepth 1 -maxdepth 1 -type d
