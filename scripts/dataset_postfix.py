#!/usr/bin/env python3
# Copyright 2025 Yingwei Zheng
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.


import os
import sys
import llvm_helper
import json
import funcname_loc
from unidiff import PatchSet


def verify_issue(issue):
    path = os.path.join(llvm_helper.dataset_dir, issue)
    with open(path) as f:
        data = json.load(f)

    # Remove unrelated comments
    comments = data["issue"]["comments"]
    data["issue"]["comments"] = [x for x in comments if llvm_helper.is_valid_comment(x)]

    # Update func names
    base_commit = data["base_commit"]
    fix_commit = data["hints"]["fix_commit"]
    patchset = PatchSet(
        llvm_helper.git_execute(
            ["show", fix_commit, "--", "llvm/lib/*", "llvm/include/*"]
        )
    )
    bug_location_funcname = dict()

    for file in patchset:
        source_code = llvm_helper.git_execute(["show", f"{base_commit}:{file.path}"])
        modified_funcs_valid = funcname_loc.get_funcname_loc(file, source_code)
        if len(modified_funcs_valid) != 0:
            bug_location_funcname[file.path] = sorted(list(modified_funcs_valid))
    if len(bug_location_funcname) == 0:
        if issue.removesuffix(".json") not in ["88297"]:
            print(f"{issue} Warning: bug_location_funcname is empty")
    data["hints"]["bug_location_funcname"] = bug_location_funcname

    with open(path, "w") as f:
        json.dump(data, f, indent=2)


task_list = []
if len(sys.argv) == 2:
    task_list = [sys.argv[1] + ".json"]
else:
    for name in os.listdir(llvm_helper.dataset_dir):
        if name.endswith(".json"):
            task_list.append(name)
task_list.sort()

for idx, task in enumerate(task_list):
    # print("Verifying", idx + 1, task.removesuffix(".json"))
    verify_issue(task)
