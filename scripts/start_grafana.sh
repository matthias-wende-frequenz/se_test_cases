#!/bin/bash

# --- Configuration ---
INFLUXDB_CONTAINER_NAME="influxdb3"
INFLUXDB_VOLUME_NAME="influxdb3-data"
INFLUXDB_IMAGE="influxdb:3-core"

GRAFANA_CONTAINER_NAME="grafana"
GRAFANA_VOLUME_NAME="grafana-data"
GRAFANA_IMAGE="grafana/grafana-oss"

# --- Container Engine Detection ---
# Check for podman first, then fall back to docker.
if command -v podman &> /dev/null; then
    CONTAINER_ENGINE="podman"
elif command -v docker &> /dev/null; then
    CONTAINER_ENGINE="docker"
else
    echo "Error: Neither podman nor docker is installed. Please install one to continue." >&2
    exit 1
fi
echo "✅ Using '$CONTAINER_ENGINE' as the container engine."
echo ""

# --- Helper Functions ---

# Function to check if a container is running. This is compatible with both podman and docker.
container_is_running() {
    # Redirect stderr to /dev/null to suppress errors if the container doesn't exist.
    [ "$($CONTAINER_ENGINE container inspect -f '{{.State.Status}}' "$1" 2>/dev/null)" == "running" ]
}

# Function to check if a container exists, handling differences between podman and docker.
container_exists() {
    if [ "$CONTAINER_ENGINE" == "podman" ]; then
        $CONTAINER_ENGINE container exists "$1"
    else # docker
        # Docker doesn't have a direct 'exists' command. We list all containers and filter by exact name.
        # The `name=^/$1$` filter ensures an exact match. We then check if the output is non-empty.
        [ -n "$($CONTAINER_ENGINE ps -a --filter "name=^/$1$" --format '{{.Names}}')" ]
    fi
}

# Function to check if a volume exists, handling differences between podman and docker.
volume_exists() {
    if [ "$CONTAINER_ENGINE" == "podman" ]; then
        $CONTAINER_ENGINE volume exists "$1"
    else # docker
        # Docker doesn't have a direct 'exists' command for volumes. We list volumes and filter by exact name.
        # The `name=^$1$` filter ensures an exact match. We then check if the output is non-empty.
        [ -n "$($CONTAINER_ENGINE volume ls --filter "name=^$1$" --format '{{.Name}}')" ]
    fi
}

# --- Main Logic ---

# 1. Manage InfluxDB Volume
echo "--- InfluxDB Volume Management ---"
if volume_exists "$INFLUXDB_VOLUME_NAME"; then
    echo "Volume '$INFLUXDB_VOLUME_NAME' already exists. No action needed."
else
    echo "Volume '$INFLUXDB_VOLUME_NAME' not found. Creating it..."
    $CONTAINER_ENGINE volume create "$INFLUXDB_VOLUME_NAME"
    echo "Volume '$INFLUXDB_VOLUME_NAME' created."
fi
echo ""

# 2. Manage Grafana Volume
echo "--- Grafana Volume Management ---"
if volume_exists "$GRAFANA_VOLUME_NAME"; then
    echo "Volume '$GRAFANA_VOLUME_NAME' already exists. No action needed."
else
    echo "Volume '$GRAFANA_VOLUME_NAME' not found. Creating it..."
    $CONTAINER_ENGINE volume create "$GRAFANA_VOLUME_NAME"
    echo "Volume '$GRAFANA_VOLUME_NAME' created."
fi
echo ""

# 3. Manage InfluxDB Container
echo "--- InfluxDB Container Management ---"
if container_exists "$INFLUXDB_CONTAINER_NAME"; then
    echo "Container '$INFLUXDB_CONTAINER_NAME' exists."
    if container_is_running "$INFLUXDB_CONTAINER_NAME"; then
        echo "Container is already running. No action needed."
    else
        echo "Container is stopped. Starting it..."
        $CONTAINER_ENGINE start "$INFLUXDB_CONTAINER_NAME"
        echo "Container '$INFLUXDB_CONTAINER_NAME' started."
    fi
else
    echo "Container '$INFLUXDB_CONTAINER_NAME' not found. Creating and starting it..."
    $CONTAINER_ENGINE run -d --name "$INFLUXDB_CONTAINER_NAME" \
      --privileged \
      --network host \
      -v "$INFLUXDB_VOLUME_NAME:/influxdb3-data" \
      "$INFLUXDB_IMAGE" \
      --node-id host01 \
      --object-store file \
      --data-dir /influxdb3-data
    echo "Container '$INFLUXDB_CONTAINER_NAME' created and started."
fi
echo ""

# 4. Manage Grafana Container
echo "--- Grafana Container Management ---"
if container_exists "$GRAFANA_CONTAINER_NAME"; then
    echo "Container '$GRAFANA_CONTAINER_NAME' exists."
    if container_is_running "$GRAFANA_CONTAINER_NAME"; then
        echo "Container is already running. No action needed."
    else
        echo "Container is stopped. Starting it..."
        $CONTAINER_ENGINE start "$GRAFANA_CONTAINER_NAME"
        echo "Container '$GRAFANA_CONTAINER_NAME' started."
    fi
else
    echo "Container '$GRAFANA_CONTAINER_NAME' not found. Creating and starting it..."
    $CONTAINER_ENGINE run -d --name "$GRAFANA_CONTAINER_NAME" \
      --restart always \
      --network host \
      -v "$GRAFANA_VOLUME_NAME:/var/lib/grafana" \
      "$GRAFANA_IMAGE"
    echo "Container '$GRAFANA_CONTAINER_NAME' created and started."
fi
echo ""

echo "--- Script Finished ---"
