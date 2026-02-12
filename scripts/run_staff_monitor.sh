#!/bin/bash
#
# Cron wrapper script for staff_update_monitor.py
#
# This script:
# 1. Sets up the environment
# 2. Runs the staff update monitor
# 3. Logs output to cron-specific log file
#
# Usage:
#   ./run_staff_monitor.sh
#
# Crontab example (run every 4 hours):
#   0 */4 * * * /path/to/coach-database/scripts/run_staff_monitor.sh
#

set -euo pipefail

# Get the directory where this script is located
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

# Change to project directory
cd "$PROJECT_DIR"

# Load environment variables if .env file exists
if [ -f "$PROJECT_DIR/.env" ]; then
    export $(cat "$PROJECT_DIR/.env" | grep -v '^#' | xargs)
fi

# Set required environment variables (edit these or use .env file)
export OPENAI_API_KEY="${OPENAI_API_KEY:-}"
export WEBHOOK_API_KEY="${WEBHOOK_API_KEY:-f0db180c08995ba77850b8aa4caccb72a02d9751f38ce7b570a5d95bc7c41c5d}"
export BRAVE_API_KEY="${BRAVE_API_KEY:-}"

# Activate virtual environment if it exists
if [ -d "$PROJECT_DIR/venv" ]; then
    source "$PROJECT_DIR/venv/bin/activate"
fi

# Ensure logs directory exists
mkdir -p "$PROJECT_DIR/logs"

# Run the monitor
echo "[$(date '+%Y-%m-%d %H:%M:%S')] Starting staff update monitor..."
python3 "$SCRIPT_DIR/staff_update_monitor.py" 2>&1 | tee -a "$PROJECT_DIR/logs/staff_monitor_cron.log"

echo "[$(date '+%Y-%m-%d %H:%M:%S')] Staff update monitor completed"
