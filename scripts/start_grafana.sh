#!/bin/bash

# --- Configuration ---
INFLUXDB_CONTAINER_NAME="influxdb3"
INFLUXDB_VOLUME_NAME="influxdb3-data"
INFLUXDB_IMAGE="influxdb:3-core"

GRAFANA_CONTAINER_NAME="grafana"
GRAFANA_VOLUME_NAME="grafana-data" # Changed from grafana-storage for consistency
GRAFANA_IMAGE="grafana/grafana-oss"

# --- Helper Function ---

# Function to check if a container is running
container_is_running() {
    [ "$(podman container inspect -f '{{.State.Status}}' "$1")" == "running" ]
}

# --- Main Logic ---

# 1. Manage InfluxDB Volume
echo "--- InfluxDB Volume Management ---"
if podman volume exists "$INFLUXDB_VOLUME_NAME"; then
    echo "Volume '$INFLUXDB_VOLUME_NAME' already exists. No action needed."
else
    echo "Volume '$INFLUXDB_VOLUME_NAME' not found. Creating it..."
    podman volume create "$INFLUXDB_VOLUME_NAME"
    echo "Volume '$INFLUXDB_VOLUME_NAME' created."
fi
echo ""

# 2. Manage Grafana Volume
echo "--- Grafana Volume Management ---"
if podman volume exists "$GRAFANA_VOLUME_NAME"; then
    echo "Volume '$GRAFANA_VOLUME_NAME' already exists. No action needed."
else
    echo "Volume '$GRAFANA_VOLUME_NAME' not found. Creating it..."
    podman volume create "$GRAFANA_VOLUME_NAME"
    echo "Volume '$GRAFANA_VOLUME_NAME' created."
fi
echo ""

# 3. Manage InfluxDB Container
echo "--- InfluxDB Container Management ---"
if podman container exists "$INFLUXDB_CONTAINER_NAME"; then
    echo "Container '$INFLUXDB_CONTAINER_NAME' exists."
    if container_is_running "$INFLUXDB_CONTAINER_NAME"; then
        echo "Container is already running. No action needed."
    else
        echo "Container is stopped. Starting it..."
        podman start "$INFLUXDB_CONTAINER_NAME"
        echo "Container '$INFLUXDB_CONTAINER_NAME' started."
    fi
else
    echo "Container '$INFLUXDB_CONTAINER_NAME' not found. Creating and starting it..."
    podman run -d --name "$INFLUXDB_CONTAINER_NAME" \
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
if podman container exists "$GRAFANA_CONTAINER_NAME"; then
    echo "Container '$GRAFANA_CONTAINER_NAME' exists."
    if container_is_running "$GRAFANA_CONTAINER_NAME"; then
        echo "Container is already running. No action needed."
    else
        echo "Container is stopped. Starting it..."
        podman start "$GRAFANA_CONTAINER_NAME"
        echo "Container '$GRAFANA_CONTAINER_NAME' started."
    fi
else
    echo "Container '$GRAFANA_CONTAINER_NAME' not found. Creating and starting it..."
    podman run -d --name "$GRAFANA_CONTAINER_NAME" \
      --restart always \
      --network host \
      -v "$GRAFANA_VOLUME_NAME:/var/lib/grafana" \
      "$GRAFANA_IMAGE"
    echo "Container '$GRAFANA_CONTAINER_NAME' created and started."
fi
echo ""

echo "--- Script Finished ---"
