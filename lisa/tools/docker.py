# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

from lisa.base_tools import Wget
from lisa.executable import Tool
from lisa.operating_system import CBLMariner, CentOs, Debian, Redhat
from lisa.tools.service import Service
from lisa.util import LisaException


class Docker(Tool):
    @property
    def command(self) -> str:
        return "docker"

    @property
    def can_install(self) -> bool:
        return True

    def build_image(self, image_name: str, dockerfile: str) -> None:
        self.run(
            f"build -t {image_name} -f {dockerfile} .",
            shell=True,
            sudo=True,
            cwd=self.node.working_path,
            force_run=True,
            expected_exit_code=0,
            expected_exit_code_failure_message="Docker image build failed.",
        )

    # Executes command inside of container
    def exec_command(self, container_name: str, command: str) -> str:
        return self.run(f"exec {container_name} {command}", sudo=True).stdout

    def exec_command_async(self, container_name: str, command: str) -> None:
        return self.run_async(f"exec {container_name} {command}", sudo=True)

    def remove_container(self, container_name: str) -> None:
        self._log.debug(f"Removing Docker Container {container_name}")
        self.run(f"rm {container_name}", sudo=True, force_run=True)

    def remove_image(self, image_name: str) -> None:
        self._log.debug(f"Removing Docker Image {image_name}")
        self.run(f"rmi {image_name}", sudo=True, force_run=True)

    def run_container(
        self,
        image_name: str,
        container_name: str,
        docker_run_output: str,
    ) -> None:
        self.run(
            f"run --name {container_name} " f"{image_name} ",
            shell=True,
            sudo=True,
            cwd=self.node.working_path,
            force_run=True,
            expected_exit_code=0,
            expected_exit_code_failure_message="Docker run failed.",
        )

    def run_container_detached(
        self,
        image_name: str,
        container_name: str,
        docker_run_output: str,
    ) -> None:
        self.run(
            f"run -d --name {container_name} " f"{image_name} ",
            shell=True,
            sudo=True,
            cwd=self.node.working_path,
            force_run=True,
            expected_exit_code=0,
            expected_exit_code_failure_message="Docker run failed.",
        )


    def start(self) -> None:
        self._log.debug("Start docker engine")
        service = self.node.tools[Service]
        service.enable_service("docker")
        service.restart_service("docker")

    def install(self) -> bool:
        if isinstance(self.node.os, Debian):
            self.node.os.install_packages("docker.io")
        elif (
            isinstance(self.node.os, CentOs)
            and self.node.os.information.release >= "8.0"
        ):
            wget_tool = self.node.tools[Wget]
            wget_tool.get(
                "https://get.docker.com",
                filename="get-docker.sh",
                file_path="./",
                executable=True,
            )
            self.node.execute("./get-docker.sh", sudo=True)
        # RHEL 8 and its derivatives don't support docker
        elif isinstance(self.node.os, Redhat):
            self.node.os.install_packages(
                ["docker", "docker-ce", "docker.socket", "docker.service"]
            )
        elif isinstance(self.node.os, CBLMariner):
            self.node.execute("wget    https://download.docker.com/linux/static/stable/x86_64/docker-20.10.12.tgz")
            self.node.execute("tar zxvf docker-20.10.12.tgz", sudo=True)
            self.node.execute("cp -f docker/* /usr/bin/", sudo=True, shell=True)
            self.node.execute_async("/usr/bin/dockerd", sudo=True, shell=True)
        else:
            raise LisaException(f"{self.node.os.information.vendor} not supported")

        return self._check_exists()
