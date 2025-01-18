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
import requests
import json
import llvm_helper
import sys
import hints
from unidiff import PatchSet
import re
import subprocess

github_token = os.environ["LAB_GITHUB_TOKEN"]
session = requests.Session()
session.headers.update(
    {
        "X-GitHub-Api-Version": "2022-11-28",
        "Authorization": f"Bearer {github_token}",
        "Accept": "application/vnd.github+json",
    }
)
subprocess.check_output(["llvm-extract", "--version"])

issue_id = sys.argv[1]
override = False
if len(sys.argv) == 3 and sys.argv[2] == "-f":
    print("Force override")
    override = True

data_json_path = os.path.join(llvm_helper.dataset_dir, f"{issue_id}.json")
if not override and os.path.exists(data_json_path):
    print(f"Item {issue_id}.json already exists")
    exit(0)

issue_url = f"https://api.github.com/repos/llvm/llvm-project/issues/{issue_id}"
print(f"Fetching {issue_url}")
issue = session.get(issue_url).json()
if issue["state"] != "closed" or issue["state_reason"] != "completed":
    print("The issue/PR should be closed")
    exit(1)

knowledge_cutoff = issue["created_at"]
timeline = session.get(issue["timeline_url"]).json()
fix_commit = None
fix_commit_map = {
    "76789": None,  # Cannot reproduce with alive2
    "78024": None,  # Reverted
    "79137": None,  # Cannot reproduce with alive2
    "80836": "1c10821022f1799452065fb57474e894e2562b7f",
    "81561": "97088b2ab2184ad4bd64f59fba0b92b70468b10d",
    "81793": None,  # Cannot reproduce with alive2
    "81872": None,  # Multi-commit fix
    "85568": None,  # Object bug
    "86280": None,  # Object bug
    "87534": None,  # IPO miscompilation
    "88640": None,  # Invalid reproducer
    "88804": None,  # Duplicate of #88297
    "91417": "645fb04a3389e69801d401e669eae9ee42d70217",  # Use the second fix
    "92217": None,  # See also https://github.com/AliveToolkit/alive2/issues/1037
    "93017": None,  # Constant expr
    "96857": None,  # miscompilation:undef
    "97702": None,  # uninit mem
    "97837": None,  # Alive2 bug e4508ba85747eb3a5e002915e544d2e08e751425
    "98133": None,  # Invalid reproducer
    "99436": None,   # Complicated fix
    "102784": None,  # Multi-commit fix
    "104397": None,  # Invalid reproducer
    "104718": None,  # Test change
    "105713": None,  # Duplicate of #104714
    "106909": None,  # Cannot reproduce with alive2
    "107037": None,  # Multi-commit fix
    "107501": None,  # Complicated fix
    "108618": None,  # Multi-commit fix
    "108854": None,  # Multi-commit fix
    "109581": None,  # Too many unrelated changes
    "110819": None,  # Outdated issue
    "111585": None,  # Cannot reproduce with alive2
    "111709": None,  # Cannot reproduce with alive2
    "112633": None,  # Multi-commit fix
    "113301": None,  # miscompilation:undef
    "113425": None,  # miscompilation:undef
    "114905": "889215a30ed60474e573f9632d1fa362dfa1b04e",  # Use the second fix
    "116668": None,  # Cannot reproduce with alive2
    "117170": None,  # Cannot reproduce with alive2
    "122166": None,  # Duplicate of #117308
    "122324": None,  # Cannot confirm fix with alive2
    "122430": None,  # Cannot confirm fix with alive2
    "122602": None,  # Duplicate of #122496
}


def is_valid_fix(commit):
    if commit is None:
        return False
    try:
        branches = llvm_helper.git_execute(["branch", "--contains", commit])
        if "main\n" not in branches:
            return False
        changed_files = (
            subprocess.check_output(
                [
                    "git",
                    "-C",
                    llvm_helper.llvm_dir,
                    "show",
                    "--name-only",
                    "--format=",
                    commit,
                ],
                stderr=subprocess.DEVNULL,
            )
            .decode()
            .strip()
        )
        if "llvm/test/" in changed_files and (
            "llvm/lib/" in changed_files or "llvm/include/" in changed_files
        ):
            return True
    except subprocess.CalledProcessError:
        pass
    return False


if issue_id in fix_commit_map:
    fix_commit = fix_commit_map[issue_id]
    if fix_commit is None:
        print("This issue is marked as invalid")
        exit(0)
else:
    for event in timeline:
        if event["event"] == "closed":
            commit_id = event["commit_id"]
            if commit_id is not None:
                fix_commit = commit_id
                break
        if event["event"] == "referenced" and fix_commit is None:
            commit = event["commit_id"]
            if is_valid_fix(commit):
                fix_commit = commit

if fix_commit is None:
    print("Cannot find the fix commit")
    exit(0)

issue_type = "unknown"
for label in issue["labels"]:
    label_name = label["name"]
    if label_name == "miscompilation":
        issue_type = "miscompilation"
    if "crash" in label_name:
        issue_type = "crash"
    if "hang" in label_name:
        issue_type = "hang"
    if label_name in [
        "invalid",
        "wontfix",
        "duplicate",
        "undefined behavior",
        "miscompilation:undef",
    ]:
        print("This issue is marked as invalid")
        exit(1)

base_commit = llvm_helper.git_execute(["rev-parse", fix_commit + "~"]).strip()
changed_files = llvm_helper.git_execute(
    ["show", "--name-only", "--format=", fix_commit]
).strip()
if "/AsmParser/" in changed_files or "/Bitcode/" in changed_files:
    print("This issue is marked as invalid")
    exit(0)

# Component level
components = llvm_helper.infer_related_components(changed_files.split("\n"))
# Extract patch
patch = llvm_helper.git_execute(
    ["show", fix_commit, "--", "llvm/lib/*", "llvm/include/*"]
)
patchset = PatchSet(patch)
# Line level
bug_location_lineno = {}
for file in patchset:
    location = hints.get_line_loc(file)
    if len(location) != 0:
        bug_location_lineno[file.path] = location


# Function level

bug_location_funcname = {}
for file in patchset.modified_files:
    print(f"Parsing {file.path}")
    source_code = llvm_helper.git_execute(["show", f"{base_commit}:{file.path}"])
    modified_funcs_valid = hints.get_funcname_loc(file, source_code)
    if len(modified_funcs_valid) != 0:
        bug_location_funcname[file.path] = list(modified_funcs_valid)

# Extract tests
test_patchset = PatchSet(
    llvm_helper.git_execute(["show", fix_commit, "--", "llvm/test/*"])
)


def remove_target_suffix(path):
    targets = [
        "X86",
        "AArch64",
        "ARM",
        "Mips",
        "RISCV",
        "PowerPC",
        "LoongArch",
        "AMDGPU",
        "SystemZ",
        "Hexagon",
    ]
    for target in targets:
        path = path.removesuffix("/" + target)
    return path


lit_test_dir = set(
    map(
        lambda x: remove_target_suffix(os.path.dirname(x)),
        filter(lambda x: x.count("llvm/test/"), changed_files.split("\n")),
    )
)
tests = []
runline_pattern = re.compile(r"; RUN: (.+)\| FileCheck")
testname_pattern = re.compile(r"define .+ @([.\w]+)\(")
# Workaround for invalid IR (constant expr/x86_mmx)
retrieve_test_from_main = {
    "77553",
    "81793",
    "82052",
    "83127",
    "83931",
    "89500",
    "91178",
}
test_commit = "origin/main" if issue_id in retrieve_test_from_main else fix_commit
for file in test_patchset:
    test_file = llvm_helper.git_execute(["show", f"{test_commit}:{file.path}"])
    commands = []
    for match in re.findall(runline_pattern, test_file):
        commands.append(match.strip())
    if issue_type != "miscompilation" and file.is_added_file:
        print(file.path, "full")

        def is_valid_test_line(line: str):
            line = line.strip()
            if (
                line.startswith("; NOTE")
                or line.startswith("; RUN")
                or line.startswith("; CHECK")
            ):
                return False
            return True

        normalized_body = "\n".join(filter(is_valid_test_line, test_file.splitlines()))
        tests.append(
            {
                "file": file.path,
                "commands": commands,
                "tests": [{"test_name": "<module>", "test_body": normalized_body}],
            }
        )
        continue
    test_names = set()
    for hunk in file:
        matched = re.search(testname_pattern, hunk.section_header)
        if matched:
            test_names.add(matched.group(1))
        for line in hunk.target:
            for match in re.findall(testname_pattern, line):
                test_names.add(match.strip())
    print(file.path, test_names)
    subtests = []
    for test_name in test_names:
        try:
            test_body = subprocess.check_output(
                ["llvm-extract", f"--func={test_name}", "-S", "-"],
                input=test_file.encode(),
            ).decode()
            test_body = test_body.removeprefix(
                "; ModuleID = '<stdin>'\nsource_filename = \"<stdin>\"\n"
            ).removeprefix("\n")
            subtests.append(
                {
                    "test_name": test_name,
                    "test_body": test_body,
                }
            )
        except Exception:
            pass
    if len(subtests) != 0:
        tests.append({"file": file.path, "commands": commands, "tests": subtests})

# Extract full issue context
issue_comments = []
comments = session.get(issue["comments_url"]).json()
for comment in comments:
    comment_obj = {
        "author": comment["user"]["login"],
        "body": comment["body"],
    }
    if llvm_helper.is_valid_comment(comment_obj):
        issue_comments.append(comment_obj)
normalized_issue = {
    "title": issue["title"],
    "body": issue["body"],
    "author": issue["user"]["login"],
    "labels": list(map(lambda x: x["name"], issue["labels"])),
    "comments": issue_comments,
}

# Write to file
metadata = {
    "bug_id": issue_id,
    "issue_url": issue["html_url"],
    "bug_type": issue_type,
    "base_commit": base_commit,
    "knowledge_cutoff": knowledge_cutoff,
    "lit_test_dir": sorted(lit_test_dir),
    "hints": {
        "fix_commit": fix_commit,
        "components": sorted(components),
        "bug_location_lineno": bug_location_lineno,
        "bug_location_funcname": bug_location_funcname,
    },
    "patch": patch,
    "tests": tests,
    "issue": normalized_issue,
}
print(json.dumps(metadata, indent=2))
with open(data_json_path, "w") as f:
    json.dump(metadata, f, indent=2)
print(f"Saved to {data_json_path}")
