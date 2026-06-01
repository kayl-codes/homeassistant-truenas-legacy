# TrueNAS Integration
![GitHub release (latest by date)](https://img.shields.io/github/v/release/kayl-codes/homeassistant-truenas?style=plastic)
[![hacs_badge](https://img.shields.io/badge/HACS-Default-41BDF5.svg?style=plastic)](https://github.com/hacs/integration)
![Project Stage](https://img.shields.io/badge/project%20stage-development-yellow.svg?style=plastic)
![GitHub all releases](https://img.shields.io/github/downloads/kayl-codes/homeassistant-truenas/total?style=plastic)

![GitHub commits since latest release](https://img.shields.io/github/commits-since/kayl-codes/homeassistant-truenas/latest?style=plastic)
![GitHub commit activity](https://img.shields.io/github/commit-activity/m/kayl-codes/homeassistant-truenas?style=plastic)
![GitHub Workflow Status](https://img.shields.io/github/actions/workflow/status/kayl-codes/homeassistant-truenas/ci.yml?style=plastic)

[![Help localize](https://img.shields.io/badge/lokalise-join-green?style=plastic&logo=data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAA4AAAAOCAYAAAAfSC3RAAAAGXRFWHRTb2Z0d2FyZQBBZG9iZSBJbWFnZVJlYWR5ccllPAAAAyhpVFh0WE1MOmNvbS5hZG9iZS54bXAAAAAAADw/eHBhY2tldCBiZWdpbj0i77u/IiBpZD0iVzVNME1wQ2VoaUh6cmVTek5UY3prYzlkIj8+IDx4OnhtcG1ldGEgeG1sbnM6eD0iYWRvYmU6bnM6bWV0YS8iIHg6eG1wdGs9IkFkb2JlIFhNUCBDb3JlIDUuNi1jMTQ1IDc5LjE2MzQ5OSwgMjAxOC8wOC8xMy0xNjo0MDoyMiAgICAgICAgIj4gPHJkZjpSREYgeG1sbnM6cmRmPSJodHRwOi8vd3d3LnczLm9yZy8xOTk5LzAyLzIyLXJkZi1zeW50YXgtbnMjIj4gPHJkZjpEZXNjcmlwdGlvbiByZGY6YWJvdXQ9IiIgeG1sbnM6eG1wTU09Imh0dHA6Ly9ucy5hZG9iZS5jb20veGFwLzEuMC9tbS8iIHhtbG5zOnN0UmVmPSJodHRwOi8vbnMuYWRvYmUuY29tL3hhcC8xLjAvc1R5cGUvUmVzb3VyY2VSZWYjIiB4bWxuczp4bXA9Imh0dHA6Ly9ucy5hZG9iZS5jb20veGFwLzEuMC8iIHhtcE1NOkRvY3VtZW50SUQ9InhtcC5kaWQ6REVCNzgzOEY4NDYxMTFFQUIyMEY4Njc0NzVDOUZFMkMiIHhtcE1NOkluc3RhbmNlSUQ9InhtcC5paWQ6REVCNzgzOEU4NDYxMTFFQUIyMEY4Njc0NzVDOUZFMkMiIHhtcDpDcmVhdG9yVG9vbD0iQWRvYmUgUGhvdG9zaG9wIENDIDIwMTcgKE1hY2ludG9zaCkiPiA8eG1wTU06RGVyaXZlZEZyb20gc3RSZWY6aW5zdGFuY2VJRD0ieG1wLmlpZDozN0ZDRUY4Rjc0M0UxMUU3QUQ2MDg4M0Q0MkE0NjNCNSIgc3RSZWY6ZG9jdW1lbnRJRD0ieG1wLmRpZDozN0ZDRUY5MDc0M0UxMUU3QUQ2MDg4M0Q0MkE0NjNCNSIvPiA8L3JkZjpEZXNjcmlwdGlvbj4gPC9yZGY6UkRGPiA8L3g6eG1wbWV0YT4gPD94cGFja2V0IGVuZD0iciI/Pjs1zyIAAABVSURBVHjaYvz//z8DOYCJgUxAtkYW9+mXyXIrI7l+ZGHc0k5nGxkupdHZxve1yQR1CjbPZURXh9dGoGJZIPUI2QC4JEgjIfyuJuk/uhgj3dMqQIABAPEGTZ/+h0kEAAAAAElFTkSuQmCC)](https://app.lokalise.com/public/9252786762290237258f09.36273104/)

![English](https://raw.githubusercontent.com/kayl-codes/homeassistant-truenas/master/docs/assets/images/flags/us.png)
![Portuguese](https://raw.githubusercontent.com/kayl-codes/homeassistant-truenas/master/docs/assets/images/flags/pt.png)

![Truenas Logo](https://raw.githubusercontent.com/kayl-codes/homeassistant-truenas/master/docs/assets/images/ui/header.png)

> **Note:** This is an actively maintained and updated fork of the original TrueNAS integration.

Monitor and control your TrueNAS device from Home Assistant.
 * Monitor System (CPU, Load, Memory, Temperature, ARC/L2ARC, Uptime)
 * Monitor Network interfaces in a dedicated device group (RX/TX traffic + link connectivity per NIC)
 * Monitor Disks
 * Monitor Pools (including the boot-pool)
 * Monitor Datasets
 * Monitor and run Replication Tasks
 * Monitor and run Rsync Tasks
 * Monitor Snapshot Tasks
 * Control and Monitor Services
 * Control and Monitor Virtual Machines
 * Control and Monitor Jails (TrueNAS CORE only)
 * Control and Monitor Cloudsync
 * Monitor Active Alerts and Diagnostics
 * Create a Dataset Snapshot
 * Update Sensor
 * Reboot and Shutdown TrueNAS system
 

# Features
## Pools
Monitor status for each TrueNAS pool.

![Pools Health](https://raw.githubusercontent.com/kayl-codes/homeassistant-truenas/master/docs/assets/images/ui/pool_healthy.png)
![Pools Free Space](https://raw.githubusercontent.com/kayl-codes/homeassistant-truenas/master/docs/assets/images/ui/pool_free.png)

## Datasets
Monitor usage and attributes for each TrueNAS dataset.

![Datasets](https://raw.githubusercontent.com/kayl-codes/homeassistant-truenas/master/docs/assets/images/ui/dataset.png)

## Disks
Monitor temperature and attributes for each TrueNAS disk.

![Disks](https://raw.githubusercontent.com/kayl-codes/homeassistant-truenas/master/docs/assets/images/ui/disk.png)

## Network
Each network interface is grouped under its own dedicated device. The integration
exposes RX/TX traffic sensors and a link connectivity binary sensor per interface.
Traffic sensors are created for active interfaces; the link sensor is always
available so disconnected interfaces can be monitored too. Sensors for interfaces
that no longer exist are cleaned up automatically on startup.

## Virtual Machines
Control and monitor status and attributes for each TrueNAS virtual machine.
Control of virtual machines is available through actions.

![Virtual Machines](https://raw.githubusercontent.com/kayl-codes/homeassistant-truenas/master/docs/assets/images/ui/vm.png)

## Jails
*TrueNAS CORE only*

Control and monitor status and attributes for each TrueNAS jail.
Jail control is available through actions.

![Jails](https://raw.githubusercontent.com/kayl-codes/homeassistant-truenas/master/docs/assets/images/ui/jail.png)

## Cloudsync
Control and monitor status and attributes for each TrueNAS cloudsync task.
Cloudsync control is available through actions.

![Cloudsync](https://raw.githubusercontent.com/kayl-codes/homeassistant-truenas/master/docs/assets/images/ui/cloudsync.png)

## Replication Tasks
Monitor status and attributes for each TrueNAS replication task.
Replication tasks can be started on demand through the `replication_run` action.

![Replication Tasks](https://raw.githubusercontent.com/kayl-codes/homeassistant-truenas/master/docs/assets/images/ui/replication.png)

## Rsync Tasks
Monitor status and attributes for each TrueNAS rsync task.
Rsync tasks can be started on demand through the `rsync_run` action.

## Snapshot Tasks
Monitor status and attributes for each TrueNAS snapshot task.

![Snapshot Tasks](https://raw.githubusercontent.com/kayl-codes/homeassistant-truenas/master/docs/assets/images/ui/snapshottask.png)

## Dataset Snapshot
Create a Dataset Snapshot using a Home Assistant action.
Snapshot name will be automatically generated using datetime iso format with microseconds and "custom" prefix. 

![Snapshot UI](https://raw.githubusercontent.com/kayl-codes/homeassistant-truenas/master/docs/assets/images/ui/snapshot_ui.png)
![Snapshot YAML](https://raw.githubusercontent.com/kayl-codes/homeassistant-truenas/master/docs/assets/images/ui/snapshot_yaml.png)

## Services
Control and monitor status and attributes for each TrueNAS service.
Service control is available through actions.
![Services](https://raw.githubusercontent.com/kayl-codes/homeassistant-truenas/master/docs/assets/images/ui/service_1.png)
![Services Control](https://raw.githubusercontent.com/kayl-codes/homeassistant-truenas/master/docs/assets/images/ui/service_2.png)

## Diagnostics
Monitor overall system health and active alerts directly from the device page. The integration provides a dedicated diagnostic sensor that automatically detects any disk, pool, or SMART issues.
![Diagnostics](https://raw.githubusercontent.com/kayl-codes/homeassistant-truenas/master/docs/assets/images/ui/diagnostics.png)

## Reboot and Shutdown
Reboot or shut down a TrueNAS system.
Power control is available through actions.
Target system uptime sensor.

![image](https://user-images.githubusercontent.com/36953052/221521930-f8f789e6-deec-4cc2-b11e-740caa056e44.png)

# Install integration from Custom Repository
1. Open HACS, click the 3-dot menu in the upper right corner and select **Custom repositories**.
2. Add the following details:
   * **Repository:** `https://github.com/kayl-codes/homeassistant-truenas.git`
   * **Category:** Integration
3. Click **Add** and download the integration.
4. Restart Home Assistant (full restart, not quick reload).
5. Navigate to **Settings -> Devices & services -> Add Integration** and search for **TrueNAS**.


Minimum requirements:
* TrueNAS 25.04
* Home Assistant 2024.8.0

## Using TrueNAS development branch
If you are using development branch for TrueNAS, some features may stop working.

## Setup integration
1. Create an API key for Home Assistant on your TrueNAS system.

![Setup step 1](https://raw.githubusercontent.com/kayl-codes/homeassistant-truenas/master/docs/assets/images/ui/setup_1.png)
![Setup step 2](https://raw.githubusercontent.com/kayl-codes/homeassistant-truenas/master/docs/assets/images/ui/setup_2.png)
![Setup step 3](https://raw.githubusercontent.com/kayl-codes/homeassistant-truenas/master/docs/assets/images/ui/setup_3.png)

2. Setup this integration for your TrueNAS device in Home Assistant via `Configuration -> Integrations -> Add -> TrueNAS`.
You can add this integration several times for different devices.

NOTES: 
- If you dont see "TrueNAS" integration, clear your browser cache.

![Add Integration](https://raw.githubusercontent.com/kayl-codes/homeassistant-truenas/master/docs/assets/images/ui/setup_integration.png)
* "Name of the integration" - Friendly name for this router
* "Host" - Use hostname or IP and if you need port seperated by colon eG: 192.168.100.100:8888
* "API key" - TrueNAS API key for Home Assistant 
* "Data size unit" - Choose how storage sizes are displayed. You can select between **GB** (Gigabytes, base 1000) and **GiB** (Gibibytes, base 1024). This will automatically adjust all dataset, pool, and memory sensors.

# Development

## Translation
To help out with the translation you need an account on Lokalise, the easiest way to get one is to [click here](https://lokalise.com/login/) then select "Log in with GitHub".
After you have created your account [click here to join TrueNAS Integrations project on Lokalise](https://app.lokalise.com/public/9252786762290237258f09.36273104/).

If you want to add translations for a language that is not listed please [open a Feature request](https://github.com/kayl-codes/homeassistant-truenas/issues/new?labels=enhancement&title=%5BLokalise%5D%20Add%20new%20translations%20language).

## Enabling debug
To enable debug for TrueNAS integration, add following to your configuration.yaml:
```
logger:
  default: info
  logs:
    custom_components.truenas: debug
```
