# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

from typing import Any, cast

from lisa.executable import Tool
from lisa.operating_system import Debian, Posix, Redhat, Suse
from lisa.util import LisaException
from lisa.util.process import Process

from .firewall import Firewall
from .git import Git
from .make import Make


class Marinerperf(Tool):
    
    def test1(self) -> None:
        self.node.execute(
            "echo \"souradeep testing\" ", sudo=True, cwd=code_path
        ).assert_exit_code()
