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
import hints
from unidiff import PatchSet

fix_commit_set = set()


def verify_issue(issue):
    global fix_commit_set
    path = os.path.join(llvm_helper.dataset_dir, issue)
    with open(path) as f:
        data = json.load(f)

    # Remove unrelated comments
    comments = data["issue"]["comments"]
    data["issue"]["comments"] = [x for x in comments if llvm_helper.is_valid_comment(x)]

    # Update hints
    bug_location_lineno = {}
    base_commit = data["base_commit"]
    fix_commit = data["hints"]["fix_commit"]
    patchset = PatchSet(
        llvm_helper.git_execute(
            ["show", fix_commit, "--", "llvm/lib/*", "llvm/include/*"]
        )
    )
    for file in patchset:
        location = hints.get_line_loc(file)
        if len(location) != 0:
            bug_location_lineno[file.path] = location
    data["hints"]["bug_location_lineno"] = bug_location_lineno
    bug_location_funcname = dict()
    for file in patchset:
        source_code = llvm_helper.git_execute(["show", f"{base_commit}:{file.path}"])
        modified_funcs_valid = hints.get_funcname_loc(file, source_code)
        if len(modified_funcs_valid) != 0:
            bug_location_funcname[file.path] = sorted(list(modified_funcs_valid))
    if len(bug_location_funcname) == 0:
        if issue.removesuffix(".json") not in ["88297", "83404"]:
            print(f"{issue} Warning: bug_location_funcname is empty")
    data["hints"]["bug_location_funcname"] = bug_location_funcname
    # Migration
    if "files" in data["hints"]:
        data["hints"].pop("files")
    bug_func_count = 0
    for item in bug_location_funcname.values():
        bug_func_count += len(item)
    is_single_file_fix = len(bug_location_funcname) == 1
    is_single_func_fix = is_single_file_fix and bug_func_count == 1
    data["properties"] = {
        "is_single_file_fix": is_single_file_fix,
        "is_single_func_fix": is_single_func_fix,
    }

    if not llvm_helper.is_valid_fix(fix_commit):
        print(f"{issue} Warning: fix_commit is invalid")
    if "main\n" not in llvm_helper.git_execute(["branch", "--contains", base_commit]):
        print(f"{issue} Warning: base_commit is not in main branch")
    if fix_commit in fix_commit_set:
        print(f"{issue} Warning: duplicated fix_commit")
    fix_commit_set.add(fix_commit)

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
