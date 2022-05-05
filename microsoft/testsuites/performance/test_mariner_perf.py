# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.
from typing import Any

from lisa import (
    Logger,
    TestCaseMetadata,
    TestSuite,
    TestSuiteMetadata,
    simple_requirement,
    Node,
)
from lisa.environment import Environment
from lisa.features import Sriov, Synthetic
from lisa.tools.mariner_test import  Marinerperf
from lisa.tools.docker import Docker
from microsoft.testsuites.performance.common import (
    cleanup_process,
)


@TestSuiteMetadata(
    area="network",
    category="performance",
    description="""
    This test suite is to validate linux network performance.
    """,
)
class TestMariner(TestSuite):
    TIMEOUT = 12000

    @TestCaseMetadata(
        description="""
        This test case uses lagscope to test synthetic network latency.
        """,
        priority=2,
        requirement=simple_requirement(
            min_count=2,
            network_interface=Synthetic(),
        ),
    )
    
    def test_mariner_docker(self, node: Node, environment: Environment) -> None:
        node_docker = node.tools[Docker]
        node.execute("docker  run -d --name recv egernst/ntttcp  -r -t 30",sudo=True,shell=True)
        recv_ip = node.execute("docker inspect -f '{{range.NetworkSettings.Networks}}{{.IPAddress}}{{end}}'"+" recv",sudo=True,shell=True)
        command = "docker  run --name send egernst/ntttcp  -s " + str(recv_ip)
        node.execute(command, sudo=True, shell=True)

    def after_case(self, log: Logger, **kwargs: Any) -> None:
        environment: Environment = kwargs.pop("environment")
        for process in ["lagscope", "netperf", "netserver", "ntttcp", "iperf3"]:
            cleanup_process(environment, process)
