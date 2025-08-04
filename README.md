# Test Cases for Siemens Energy HiL System

## Set up grafana for truck charging monitoring

To start Grafana and influxdb3, run the script in the `scripts` directory:

Run the following command to create the initial admin token for InfluxDB 3 and
safe the token.

```sh
podman exec -ti influxdb3 influxdb3 create token --admin
```

As a next step, you need to create a datasource in Grafana.


## Create snap

Note: The python snapcraft plugin doesn't support cross-compilation, 
so the snap must be built on the target architecture.

To create a snap from a python project that uses `pyproject.toml`, is this project, file we need 
to use Snapcraft from the edge channel [2].

```
sudo snap refresh snapcraft --edge
```

Running the app in the snap works by running an auto created run script as defined in the pyproject.toml
file [1].

[1] https://packaging.python.org/en/latest/guides/writing-pyproject-toml/#creating-executable-scripts
[2] https://snapcraft.io/docs/python-apps
