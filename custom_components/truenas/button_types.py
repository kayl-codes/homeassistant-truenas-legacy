"""Definitions for TrueNAS button entities."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, NamedTuple

from homeassistant.components.button import ButtonEntityDescription

# Run buttons mirror the on-demand "*_run" actions, but as one-tap controls on the
# task's device page. Each carries the JSON-RPC method to call with the object id.


@dataclass
class TrueNASButtonEntityDescription(ButtonEntityDescription):
    """Class describing TrueNAS button entities."""

    api_method: str | None = None
    ha_group: str | None = None
    ha_connection: str | None = None
    ha_connection_value: str | None = None
    data_path: str | None = None
    data_name: str | None = None
    data_uid: str | None = None
    data_reference: str | None = None
    data_attributes_list: list[str] = field(default_factory=list)
    func: str = "TrueNASButton"


SENSOR_TYPES: tuple[TrueNASButtonEntityDescription, ...] = (
    TrueNASButtonEntityDescription(
        key="snapshottask_run",
        name="Run",
        icon="mdi:play-circle-outline",
        api_method="pool.snapshottask.run",
        ha_group="Snapshot tasks",
        data_path="snapshottask",
        data_name="dataset",
        data_uid=None,
        data_reference="id",
    ),
    TrueNASButtonEntityDescription(
        key="rsync_run",
        name="Run",
        icon="mdi:play-circle-outline",
        api_method="rsynctask.run",
        ha_group="Rsync tasks",
        data_path="rsynctask",
        data_name="desc",
        data_uid=None,
        data_reference="id",
    ),
    TrueNASButtonEntityDescription(
        key="replication_run",
        name="Run",
        icon="mdi:play-circle-outline",
        api_method="replication.run",
        ha_group="Replication",
        data_path="replication",
        data_name="name",
        data_uid=None,
        data_reference="id",
    ),
    TrueNASButtonEntityDescription(
        key="cloudsync_run",
        name="Run",
        icon="mdi:play-circle-outline",
        api_method="cloudsync.sync",
        ha_group="Cloudsync",
        data_path="cloudsync",
        data_name="description",
        data_uid=None,
        data_reference="id",
    ),
)


class ButtonService(NamedTuple):
    """Service definition."""

    name: str
    schema: Any
    action: str


SENSOR_SERVICES: tuple[ButtonService, ...] = ()
