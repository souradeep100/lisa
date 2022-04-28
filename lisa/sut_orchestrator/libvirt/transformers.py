# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

from dataclasses import dataclass, field
from pathlib import PurePath
from typing import Any, Dict, List, Optional, Type, cast

from dataclasses_json import dataclass_json

from lisa import schema
from lisa.lisa.operating_system import CBLMariner, Ubuntu
from lisa.lisa.tools.python import Pip
from lisa.node import Node, quick_connect
from lisa.operating_system import Posix, Linux
from lisa.secret import PATTERN_HEADTAIL, add_secret
from lisa.tools import Uname
from lisa.transformer import Transformer
from lisa.util import field_metadata, filter_ansi_escape, get_matched_str, subclasses
from lisa.util.logger import Logger, get_logger

LIBVIRT_INSTALLER = "libvirt_installer"

@dataclass_json()
@dataclass
class BaseInstallerSchema(schema.TypedSchema, schema.ExtendableSchemaMixin):
    ...


@dataclass_json()
@dataclass
class PackageInstallerSchema(BaseInstallerSchema):
    ...


@dataclass_json()
@dataclass
class SourceInstallerSchema(BaseInstallerSchema):
    # source code repo
    repo: str = ""
    ref: str = ""
    # where to clone the repo
    path: str = field(
        default="/mnt/",
        metadata=field_metadata(
            required=True,
        ),
    )


@dataclass_json
@dataclass
class InstallerTransformerSchema(schema.Transformer):
    # SSH connection information to the node
    connection: Optional[schema.RemoteNode] = field(
        default=None, metadata=field_metadata(required=True)
    )
    # installer's parameters.
    installer: Optional[BaseInstallerSchema] = field(
        default=None, metadata=field_metadata(required=True)
    )


class BaseInstaller(subclasses.BaseClassWithRunbookMixin):
    def __init__(
        self,
        runbook: Any,
        node: Node,
        parent_log: Logger,
        *args: Any,
        **kwargs: Any,
    ) -> None:
        super().__init__(runbook, *args, **kwargs)
        self._node = node
        self._log = get_logger(LIBVIRT_INSTALLER, parent=parent_log)

    def validate(self) -> None:
        raise NotImplementedError()

    def install(self) -> str:
        raise NotImplementedError()

    def _get_version(self) -> str:
        raise NotImplementedError()

class LibvirtInstallerTransformer(Transformer):
    @classmethod
    def type_name(cls) -> str:
        return LIBVIRT_INSTALLER

    @classmethod
    def type_schema(cls) -> Type[schema.TypedSchema]:
        return InstallerTransformerSchema

    @property
    def _output_names(self) -> List[str]:
        return []

    def _internal_run(self) -> Dict[str, Any]:
        runbook: InstallerTransformerSchema = self.runbook
        assert runbook.connection, "connection must be defined."
        assert runbook.installer, "installer must be defined."

        node = quick_connect(runbook.connection, "libvirt_installer_node")

        factory = subclasses.Factory[BaseInstaller](BaseInstaller)
        installer = factory.create_by_runbook(
            runbook=runbook.installer, node=node, parent_log=self._log
        )

        libvirt_version = installer.install()
        self._log.info(f"installed libvirt version: {libvirt_version}")

        self._log.info("rebooting")
        node.reboot()

        # Do additional steps as per each distro needs.
        # check if the livirtd is running properly after installation

        return {}


class QemuInstallerTransformer(Transformer):
    @classmethod
    def type_name(cls) -> str:
        return "qemu_installer"

    @classmethod
    def type_schema(cls) -> Type[schema.TypedSchema]:
        return InstallerTransformerSchema

    @property
    def _output_names(self) -> List[str]:
        return []

    def _internal_run(self) -> Dict[str, Any]:
        runbook: InstallerTransformerSchema = self.runbook
        assert runbook.connection, "connection must be defined."
        assert runbook.installer, "installer must be defined."

        node = quick_connect(runbook.connection, "qemu_installer_node")

        factory = subclasses.Factory[BaseInstaller](BaseInstaller)
        installer = factory.create_by_runbook(
            runbook=runbook.installer, node=node, parent_log=self._log
        )

        qemu_version = installer.install()
        self._log.info(f"installed qemu version: {qemu_version}")

        self._log.info("rebooting")
        node.reboot()

        # Do additional steps as per each distro needs.
        # check if the livirtd is running properly after installation

        return {}


class PackageInstaller(BaseInstaller):

    __distro_package_mapping = {}

    @classmethod
    def type_schema(cls) -> Type[schema.TypedSchema]:
        return PackageInstallerSchema

    def validate(self) -> None:
        assert type(self._node.os).__name__ in self.__distro_package_mapping, (
            f"The '{self.type_name()}' installer only support Linux Distros. "
            f"The current os is {self._node.os.name}"
        )

    def install(self) -> str:
        node: Node = self._node
        linux: Linux = cast(Linux, node.os)

        packages_list = self.__distro_package_mapping[type(linux).__name__]
        self._log.info(f"installing package: {packages_list}")
        linux.install_packages(packages_list)
        version = self._get_version()

        return version


class SourceInstaller(BaseInstaller):

    @classmethod
    def type_schema(cls) -> Type[schema.TypedSchema]:
        return SourceInstallerSchema

    def validate(self) -> None:
        assert type(self._node.os).__name__ in self.__distro_package_mapping, (
            f"The '{self.type_name()}' installer only support Linux Distros. "
            f"The current os is {self._node.os.name}"
        )

    def _get_source_code(self) -> PurePath:
        runbook: SourceInstallerSchema = self.runbook
        code_path = _get_code_path(runbook.path, self._node, f"{self.type_name()}_code")

        echo = self._node.tools[Echo]
        echo_result = echo.run(str(code_path), shell=True)

        code_path = self._node.get_pure_path(echo_result.stdout)

        if self._node.shell.exists(code_path):
            self._node.shell.remove(code_path, True)

        # create and give permission on code folder
        self._node.execute(f"mkdir -p {code_path}", sudo=True)
        self._node.execute(f"chmod -R 777 {code_path}", sudo=True)

        self._log.info(f"cloning code from {runbook.repo} to {code_path}...")
        git = self._node.tools[Git]
        code_path = git.clone(
            url=runbook.repo, cwd=code_path
        )

        git.fetch(cwd=code_path)

        if runbook.ref:
            self._log.info(f"checkout code from: '{runbook.ref}'")
            git.checkout(ref=runbook.ref, cwd=code_path)

        return code_path


class LibvirtPackageInstaller(PackageInstaller):

    __distro_package_mapping = {
        Ubuntu.__name__: ["libvirt-daemon-system"],
        CBLMariner.__name__: ["dmidecode", "dnsmasq", "ebtables", "libvirt*"]
    }

    @classmethod
    def type_name(cls) -> str:
        return "libvirt_package"

    def _get_version(self) -> str:
        result = self._node.execute(f"libvirtd --version", shell=True)
        result_output = filter_ansi_escape(result.stdout)
        return result_output


class LibvirtSourceInstaller(SourceInstaller):
    @classmethod
    def type_name(cls) -> str:
        return "libvirt_source"

    @classmethod
    def type_schema(cls) -> Type[schema.TypedSchema]:
        return SourceInstallerSchema

    def validate(self) -> None:
        assert isinstance(self._node.os, Linux), (
            f"The '{self.type_name()}' installer only support Linux Distros. "
            f"The current os is {self._node.os.name}"
        )

    def _build_code_and_install(self, code_path: PurePath) -> None:
        self._node.execute("pip3 install meson", shell=True, sudo=True)
        self._log.info("building libvirt code...")
        self._node.execute(
            f"meson build -D driver_ch=enabled -D driver_qemu=disabled \\"
            f"-D driver_openvz=disabled -D driver_esx=disabled \\"
            f"-D driver_vmware=disabled  -D driver_lxc=disabled \\"
            f"-D driver_libxl=disabled -D driver_vbox=disabled \\"
            f"-D selinux=disabled -D system=true --prefix=/usr",
            shell=True
        )
        self._node.execute("ninja -C build", shell=True)
        self._node.execute("ninja -C build install", shell=True, sudo=True)
        self._node.execute("ldconfig", shell=True, sudo=True)

    def install(self) -> str:
        node: Node = self._node
        linux: Linux = cast(Linux, node.os)

        self._log.debug("installing dependencies for Libvirt")
        dep_list = [ "dnsmasq-base", "ninja-build", "libxml2-utils", "xsltproc", \
            "python3-docutils", "libglib2.0-dev", "libgnutls28-dev", "libxml2-dev", \
            "libnl-3-dev", "libnl-route-3-dev", "libyajl-dev", "make", "qemu-utils", \
            "libcurl4-gnutls-dev", "libssl-dev", "libudev-dev", "libpciaccess-dev", \
            "mtools", "flex", "bison", "libelf-dev", "libtirpc-dev", "python3-pip" ]
        linux.install_packages(dep_list)
        code_path = self._get_source_code()
        self._build_code_and_install(code_path)

        return ""


class QemuPackageInstaller(PackageInstaller):

    __distro_package_mapping = {
        Ubuntu.__name__: ["qemu-kvm"],
        CBLMariner.__name__: ["qemu-kvm"]
    }

    @classmethod
    def type_name(cls) -> str:
        return "qemu_package"

    def _get_version(self) -> str:
        result = self._node.execute(f"qemu --version", shell=True)
        result_output = filter_ansi_escape(result.stdout)
        return result_output


class CloudHypervisorPackageInstaller(PackageInstaller):

    __distro_package_mapping = {
        CBLMariner.__name__: ["cloud-hypervisor*"]
    }

    @classmethod
    def type_name(cls) -> str:
        return "cloudhypervisor_package"

    def _get_version(self) -> str:
        result = self._node.execute(f"cloud-hypervisor --version", shell=True)
        result_output = filter_ansi_escape(result.stdout)
        return result_output


class CloudHypervisorSourceInstaller(SourceInstaller):
    @classmethod
    def type_name(cls) -> str:
        return "cloudhypervisor_source"

    def _build_code_and_install(self, code_path: PurePath) -> None:
        self._node.execute("curl https://sh.rustup.rs -sSf | sh -s -- -y",
                shell=True, sudo=False)
        self._node.execute("source ~/.cargo/env", shell=True, sudo=False)
        self._node.execute("cargo build --release", shell=True, sudo=False)
        self._node.execute("cp ./target/release/cloud-hypervisor /usr/local/bin",
                    shell=True, sudo=True)
        self._node.execute("setcap cap_net_admin+ep /usr/local/bin/cloud-hypervisor",
                    shell=True, sudo=True)


    def install(self) -> str:
        node: Node = self._node
        linux: Linux = cast(Linux, node.os)

        self._log.debug("installing dependencies for Libvirt")
        dep_list = [ "gcc" ]
        linux.install_packages(dep_list)
        code_path = self._get_source_code()
        self._build_code_and_install(code_path)

        return ""


# remove this and import from kernel_sopurce_install file
def _get_code_path(path: str, node: Node, default_name: str) -> PurePath:
    if path:
        code_path = node.get_pure_path(path)
    else:
        code_path = node.working_path / default_name

    return code_path


"""
gcc
"""