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
import json
import subprocess
import llvm_helper
# import resource

GOOD = 0
BAD = 1
SKIP = 125

provider = os.environ.get("LAB_PROVIDER")


def test(commit_sha: str, issue_path: str) -> int:
    with open(issue_path) as f:
        content = f.read()
        data = json.loads(content)
    required_binaries = ["opt"]
    if "lli_expected_out" in content:
        required_binaries.append("lli")
    bin_dir = os.path.join(llvm_helper.llvm_build_dir, "bin")
    os.makedirs(bin_dir, exist_ok=True)
    bug_type = data["bug_type"]
    # _, hard = resource.getrlimit(resource.RLIMIT_AS)
    # resource.setrlimit(resource.RLIMIT_AS, (min(hard, 8 * 1024**3), hard))
    try:
        for binary in required_binaries:
            target_file = os.path.join(bin_dir, binary)
            if os.path.exists(target_file):
                os.remove(target_file)
            subprocess.check_call(
                [provider, commit_sha, binary, target_file],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            subprocess.check_output([target_file, "--version"])
        res, _ = llvm_helper.verify_test_group(
            repro=True, input=data["tests"], type=bug_type
        )
        if res:
            print(commit_sha, "BAD", file=sys.stderr)
            return BAD
        res, _ = llvm_helper.verify_test_group(
            repro=False, input=data["tests"], type=bug_type
        )
        if res:
            print(commit_sha, "GOOD", file=sys.stderr)
            return GOOD
    except Exception:
        pass
    print(commit_sha, "SKIP", file=sys.stderr)
    return SKIP


if __name__ == "__main__":
    issue_path = sys.argv[1]
    commit_sha = sys.argv[2] if len(sys.argv) == 3 else llvm_helper.git_execute(["rev-parse", "BISECT_HEAD"]).strip()
    exit(test(commit_sha, issue_path))
