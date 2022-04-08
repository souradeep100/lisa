# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.
from __future__ import annotations

import re
from typing import List, Pattern, Type

from lisa.executable import Tool
from lisa.util import find_patterns_in_lines

from .dmesg import Dmesg
from .git import Git
from .make import Make
from .service import Systemctl


class HibernationSetup(Tool):
    _repo = "https://github.com/microsoft/hibernation-setup-tool"
    _entry_pattern = re.compile(r"^(.*hibernation entry.*)$", re.MULTILINE)
    _exit_pattern = re.compile(r"^(.*hibernation exit.*)$", re.MULTILINE)

    @property
    def command(self) -> str:
        return "hibernation-setup-tool"

    @property
    def dependencies(self) -> List[Type[Tool]]:
        return [Git, Make]

    @property
    def can_install(self) -> bool:
        return True

    def start(self) -> None:
        self.run(
            sudo=True,
            expected_exit_code=0,
            expected_exit_code_failure_message="fail to start",
        )

    def check_entry(self) -> int:
        return self._check(self._entry_pattern)

    def check_exit(self) -> int:
        return self._check(self._exit_pattern)

    def hibernate(self) -> None:
        self.node.tools[Systemctl].hibernate()

    def _install(self) -> bool:
        tool_path = self.get_tool_path()
        git = self.node.tools[Git]
        git.clone(self._repo, tool_path)
        code_path = tool_path.joinpath("hibernation-setup-tool")
        make = self.node.tools[Make]
        make.make_install(code_path)
        return self._check_exists()

    def _check(self, pattern: Pattern[str]) -> int:
        dmesg = self.node.tools[Dmesg]
        dmesg_output = dmesg.get_output(force_run=True)
        matched_lines = find_patterns_in_lines(dmesg_output, [pattern])
        if not matched_lines:
            return 0
        return len(matched_lines[0])