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
import tree_sitter_cpp
from tree_sitter import Language, Parser
from unidiff import PatchSet
import re
import subprocess

CXX_LANGUAGE = Language(tree_sitter_cpp.language())
cxx_parser = Parser(CXX_LANGUAGE)
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
    "108618": None,
    "109581": None,
    "110819": None,
    "112633": None,
}

def is_valid_fix(commit):
    if commit is None:
        return False
    try:
        branches = llvm_helper.git_execute(['branch', '--contains', commit])
        if 'main\n' not in branches:
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
    if label_name in ["invalid", "wontfix", "duplicate", "undefined behavior"]:
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
# File level
files = []
# Extract patch
patch = llvm_helper.git_execute(
    ["show", fix_commit, "--", "llvm/lib/*", "llvm/include/*"]
)
patchset = PatchSet(patch)
# Line level
bug_location_lineno = {}
for file in patchset:
    location = []
    for hunk in file:
        min_lineno = min(x.source_line_no for x in hunk.source_lines())
        max_lineno = max(x.source_line_no for x in hunk.source_lines())
        location.append([min_lineno, max_lineno])
    bug_location_lineno[file.path] = location
    files.append(file.path)


# Function level
def traverse_tree(tree):
    cursor = tree.walk()

    reached_root = False
    while reached_root == False:
        yield cursor.node

        if cursor.goto_first_child():
            continue

        if cursor.goto_next_sibling():
            continue

        retracing = True
        while retracing:
            if not cursor.goto_parent():
                retracing = False
                reached_root = True

            if cursor.goto_next_sibling():
                retracing = False


bug_location_funcname = {}
for file in patchset.modified_files:
    print(f"Parsing {file.path}")
    source_code = llvm_helper.git_execute(["show", f"{base_commit}:{file.path}"])
    tree = cxx_parser.parse(bytes(source_code, "utf-8"))
    modified_funcs = set()
    for node in traverse_tree(tree):
        if node.type == "function_definition":
            func_name_node = node.children_by_field_name("declarator")[0]
            while True:
                decl = func_name_node.children_by_field_name("declarator")
                if len(decl) == 0:
                    break
                func_name_node = decl[0]
            func_name = func_name_node.text.decode("utf-8")
            if func_name in patch:
                modified_funcs.add(func_name)
    modified_funcs_valid = list()
    for func in modified_funcs:
        substr = False
        for rhs in modified_funcs:
            if func != rhs and func in rhs:
                substr = True
                break
        if not substr:
            modified_funcs_valid.append(func)
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
    ]
    for target in targets:
        path = path.removesuffix("/" + target)
    return path


lit_test_dir = set(
    map(
        lambda x: remove_target_suffix(os.path.dirname(x)),
        filter(lambda x: x.count("/test/"), changed_files.split("\n")),
    )
)
tests = []
runline_pattern = re.compile(r"; RUN: (.+)\| FileCheck")
testname_pattern = re.compile(r"define .+ @(\w+)\(")
for file in test_patchset:
    test_names = set()
    test_file = llvm_helper.git_execute(["show", f"{fix_commit}:{file.path}"])
    for hunk in file:
        matched = re.search(testname_pattern, hunk.section_header)
        if not matched:
            continue
        test_names.add(matched.group(1))
    if len(test_names) == 0:
        for match in re.findall(testname_pattern, test_file):
            test_names.add(match.strip())
    commands = []
    for match in re.findall(runline_pattern, test_file):
        commands.append(match.strip())
    subtests = []
    for test_name in test_names:
        test_body = subprocess.check_output(
            ["llvm-extract", f"--func={test_name}", "-S", "-"], input=test_file.encode()
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
    tests.append({"file": file.path, "commands": commands, "tests": subtests})

# Extract full issue context
issue_comments = []
comments = session.get(issue["comments_url"]).json()
for comment in comments:
    issue_comments.append(
        {
            "author": comment["user"]["login"],
            "body": comment["body"],
        }
    )
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
    "lit_test_dir": list(lit_test_dir),
    "hints": {
        "fix_commit": fix_commit,
        "components": list(components),
        "files": files,
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
    f.write("\n")
print(f"Saved to {data_json_path}")
