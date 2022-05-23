# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

import re
from dataclasses import dataclass
from enum import Enum
from functools import partial
from typing import Any, List, Set, Type, cast

from dataclasses_json import dataclass_json

from lisa import schema
from lisa.base_tools import Wget
from lisa.feature import Feature
from lisa.operating_system import Redhat, Ubuntu
from lisa.sut_orchestrator.azure.tools import LisDriver
from lisa.tools import Lsmod, Lspci, Lsvmbus, NvidiaSmi
from lisa.tools.lspci import PciDevice
from lisa.util import LisaException, constants

FEATURE_NAME_GPU = "Gpu"


@dataclass_json()
@dataclass()
class GpuSettings(schema.FeatureSettings):
    type: str = FEATURE_NAME_GPU
    install_by_platform: bool = True
    is_enabled: bool = False

    def __hash__(self) -> int:
        return hash(self._get_key())

    def _get_key(self) -> str:
        return f"{self.type}/{self.install_by_platform}"

    def _generate_min_capability(self, capability: Any) -> Any:
        return self


# Link to the latest GRID driver
# The DIR link is
# https://download.microsoft.com/download/9/5/c/95c667ff-ab95-4c56-89e0-e13e9a76782d/NVIDIA-Linux-x86_64-460.32.03-grid-azure.run
DEFAULT_GRID_DRIVER_URL = "https://go.microsoft.com/fwlink/?linkid=874272"

DEFAULT_CUDA_DRIVER_VERSION = "10.1.105-1"


class ComputeSDK(str, Enum):
    GRID = "GRID"
    CUDA = "CUDA"
    AMD = "AMD"


class Gpu(Feature):
    _redhat_gpu_dependencies = [
        "kernel-devel-$(uname -r)",
        "kernel-headers-$(uname -r)",
        "mesa-libGL",
        "mesa-libEGL",
        "libglvnd-devel",
        "dkms",
    ]

    _ubuntu_gpu_dependencies = [
        "build-essential",
        "libelf-dev",
        "linux-tools-$(uname -r)",
        "linux-cloud-tools-$(uname -r)",
        "python",
        "libglvnd-dev",
        "ubuntu-desktop",
    ]

    @classmethod
    def settings_type(cls) -> Type[schema.FeatureSettings]:
        return GpuSettings

    @classmethod
    def name(cls) -> str:
        return FEATURE_NAME_GPU

    @classmethod
    def can_disable(cls) -> bool:
        return True

    @classmethod
    def on_before_deployment(cls, *args: Any, **kwargs: Any) -> None:
        """
        The driver may be installed by platform, like Azure extensions. The
        platform needs to implement _install_by_platform. And call this method
        in platform.
        """
        settings = cast(GpuSettings, kwargs.get("settings"))

        # default to install by platform, unless it's specified to skip.
        if (settings.is_enabled) and settings.install_by_platform:
            cls._install_by_platform(*args, **kwargs)

    @classmethod
    def remove_virtual_gpus(cls, devices: List[PciDevice]) -> List[PciDevice]:
        return [x for x in devices if x.vendor != "Microsoft Corporation"]

    def enabled(self) -> bool:
        return True

    def is_supported(self) -> bool:
        raise NotImplementedError

    def is_module_loaded(self) -> bool:
        lsmod_tool = self._node.tools[Lsmod]
        if (len(self.gpu_vendor) > 0) and all(
            lsmod_tool.module_exists(vendor) for vendor in self.gpu_vendor
        ):
            return True

        return False

    def install_compute_sdk(self, version: str = "") -> None:
        # install GPU dependencies before installing driver
        self._install_gpu_dep()
        try:
            # install LIS driver if required and not already installed.
            self._node.tools[LisDriver]
        except Exception as identifier:
            self._log.debug(
                f"LisDriver is not installed. It might not be required. {identifier}"
            )

        # install the driver
        supported_driver = self.get_supported_driver()
        for driver in supported_driver:
            if driver == ComputeSDK.GRID:
                if not version:
                    version = DEFAULT_GRID_DRIVER_URL
                    self._install_grid_driver(version)
                    self.gpu_vendor.add("nvidia")
            elif driver == ComputeSDK.CUDA:
                if not version:
                    version = DEFAULT_CUDA_DRIVER_VERSION
                    self._install_cuda_driver(version)
                    self.gpu_vendor.add("nvidia")
            else:
                raise LisaException(f"{driver} is not a valid value of ComputeSDK")

        if not self.gpu_vendor:
            raise LisaException("No supported gpu driver/vendor found for this node.")

    def get_gpu_count_with_lsvmbus(self) -> int:
        lsvmbus_device_count = 0
        bridge_device_count = 0

        lsvmbus_tool = self._node.tools[Lsvmbus]
        device_list = lsvmbus_tool.get_device_channels()
        for device in device_list:
            for name, id, bridge_count in NvidiaSmi.gpu_devices:
                if id in device.device_id:
                    lsvmbus_device_count += 1
                    bridge_device_count = bridge_count
                    self._log.debug(f"GPU device {name} found!")
                    break

        return lsvmbus_device_count - bridge_device_count

    def get_gpu_count_with_lspci(self) -> int:
        lspci_tool = self._node.tools[Lspci]
        device_list = lspci_tool.get_devices_by_type(constants.DEVICE_TYPE_GPU)
        # Remove Microsoft Virtual one. It presents with GRID driver.
        device_list = self.remove_virtual_gpus(device_list)

        return len(device_list)

    def get_gpu_count_with_vendor_cmd(self) -> int:
        nvidiasmi = self._node.tools[NvidiaSmi]
        return nvidiasmi.get_gpu_count()

    def get_supported_driver(self) -> List[ComputeSDK]:
        raise NotImplementedError()

    def _initialize(self, *args: Any, **kwargs: Any) -> None:
        self.gpu_vendor: Set[str] = set()

    @classmethod
    def _install_by_platform(cls, *args: Any, **kwargs: Any) -> None:
        raise NotImplementedError()

    # download and install NVIDIA grid driver
    def _install_grid_driver(self, driver_url: str) -> None:
        self._log.debug("Starting GRID driver installation")
        # download and install the NVIDIA GRID driver
        wget_tool = self._node.tools[Wget]
        grid_file_path = wget_tool.get(
            driver_url,
            str(self._node.working_path),
            "NVIDIA-Linux-x86_64-grid.run",
            executable=True,
        )
        result = self._node.execute(
            f"{grid_file_path} --no-nouveau-check --silent --no-cc-version-check"
        )
        if result.exit_code != 0:
            raise LisaException(
                "Failed to install the GRID driver! "
                f"exit-code: {result.exit_code} stderr: {result.stderr}"
            )

        self._log.debug("Successfully installed the GRID driver")

    # download and install CUDA Driver
    def _install_cuda_driver(self, version: str) -> None:
        self._log.debug("Starting CUDA driver installation")
        cuda_repo = ""
        os_information = self._node.os.information

        if isinstance(self._node.os, Redhat):
            release = os_information.release.split(".")[0]
            cuda_repo_pkg = f"cuda-repo-rhel{release}-{version}.x86_64.rpm"
            cuda_repo = (
                "http://developer.download.nvidia.com/"
                f"compute/cuda/repos/rhel{release}/x86_64/{cuda_repo_pkg}"
            )
            # download and install the cuda driver package from the repo
            self._node.os._install_package_from_url(
                f"{cuda_repo}", package_name="cuda-drivers.rpm", signed=False
            )
        elif isinstance(self._node.os, Ubuntu):
            release = re.sub("[^0-9]+", "", os_information.release)
            # there is no ubuntu2110 and ubuntu2104 folder under nvidia site
            if release in ["2110", "2104"]:
                release = "2004"

            # Public CUDA GPG key is needed to be installed for Ubuntu
            self._node.execute(
                "apt-key adv --fetch-keys http://developer.download.nvidia.com/compute/"
                f"cuda/repos/ubuntu{release}/x86_64/7fa2af80.pub",
                sudo=True,
            )
            if "1804" == release:
                cuda_repo_pkg = f"cuda-repo-ubuntu{release}_{version}_amd64.deb"
                cuda_repo = (
                    "http://developer.download.nvidia.com/compute/"
                    f"cuda/repos/ubuntu{release}/x86_64/{cuda_repo_pkg}"
                )
                # download and install the cuda driver package from the repo
                self._node.os._install_package_from_url(
                    f"{cuda_repo}", package_name="cuda-drivers.deb", signed=False
                )
            else:
                self._node.tools[Wget].get(
                    f"https://developer.download.nvidia.com/compute/cuda/repos/"
                    f"ubuntu{release}/x86_64/cuda-ubuntu{release}.pin",
                    "/etc/apt/preferences.d",
                    "cuda-repository-pin-600",
                    sudo=True,
                    overwrite=False,
                )
                repo_entry = (
                    f"deb http://developer.download.nvidia.com/compute/cuda/repos/"
                    f"ubuntu{release}/x86_64/ /"
                )
                self._node.execute(
                    f'add-apt-repository -y "{repo_entry}"',
                    sudo=True,
                    expected_exit_code=0,
                    expected_exit_code_failure_message=(
                        f"failed to add repo {repo_entry}"
                    ),
                )
                # the latest version cuda-drivers-510 has issues
                # nvidia-smi
                # No devices were found
                # dmesg
                # NVRM: GPU 0001:00:00.0: RmInitAdapter failed! (0x63:0x55:2344)
                # NVRM: GPU 0001:00:00.0: rm_init_adapter failed, device minor number 0
                #  switch to use 495
                self._node.os.install_packages("cuda-drivers-495")
        else:
            raise LisaException(
                f"Distro {self._node.os.name}" "not supported to install CUDA driver."
            )

    def _install_gpu_dep(self) -> None:
        # install dependency libraries for distros
        if isinstance(self._node.os, Redhat):
            self._node.os.install_packages(
                list(self._redhat_gpu_dependencies), signed=False
            )
        elif isinstance(self._node.os, Ubuntu):
            self._node.os.install_packages(
                list(self._ubuntu_gpu_dependencies), timeout=2000
            )
        else:
            raise LisaException(
                f"Distro {self._node.os.name} is not supported for GPU."
            )


GpuEnabled = partial(GpuSettings, is_enabled=True)
