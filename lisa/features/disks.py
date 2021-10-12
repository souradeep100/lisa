# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

from functools import partial
from typing import Type

from assertpy.assertpy import assert_that

from lisa import schema
from lisa.feature import Feature
from lisa.tools import Mount
from lisa.tools.mount import PartitionInfo


class Disk(Feature):
    @classmethod
    def settings_type(cls) -> Type[schema.FeatureSettings]:
        return schema.DiskOptionSettings

    @classmethod
    def can_disable(cls) -> bool:
        return False

    def enabled(self) -> bool:
        return True

    def get_partition_with_mount_point(self, mount_point: str) -> PartitionInfo:
        partition_info = self._node.tools[Mount].get_partition_info()
        matched_partitions = [
            partition
            for partition in partition_info
            if partition.mount_point == mount_point
        ]
        assert_that(
            matched_partitions,
            f"Exactly one partition with mount point {mount_point} should be present",
        ).is_length(1)

        partition = matched_partitions[0]
        self._log.debug(f"disk: {partition}, mount_point: {mount_point}")

        return partition


DiskEphemeral = partial(schema.DiskOptionSettings, disk_type=schema.DiskType.Ephemeral)
DiskPremiumSSDLRS = partial(
    schema.DiskOptionSettings, disk_type=schema.DiskType.PremiumSSDLRS
)
DiskStandardHDDLRS = partial(
    schema.DiskOptionSettings, disk_type=schema.DiskType.StandardHDDLRS
)
DiskStandardSSDLRS = partial(
    schema.DiskOptionSettings, disk_type=schema.DiskType.StandardSSDLRS
)