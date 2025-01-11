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

CXX_LANGUAGE = Language(tree_sitter_cpp.language())
cxx_parser = Parser(CXX_LANGUAGE)
github_token = os.environ['LAB_GITHUB_TOKEN']
session = requests.Session()
session.headers.update({'X-GitHub-Api-Version': '2022-11-28', 'Authorization': f'Bearer {github_token}', 'Accept': 'application/vnd.github+json'})

issue_id = int(sys.argv[1])
issue_url = f'https://api.github.com/repos/llvm/llvm-project/issues/{issue_id}'
print(f'Fetching {issue_url}')
issue = session.get(issue_url).json()
if issue['state'] != 'closed':
    print('The issue/PR should be closed')
    exit(1)

knowledge_cutoff = issue['created_at']
timeline = session.get(issue['timeline_url']).json()
fix_commit = None
for event in timeline:
    if event['event'] == 'closed' or event['event'] == 'referenced':
        if 'commit_id' in event:
            fix_commit = event['commit_id']
            if fix_commit is not None:
                break

issue_type = 'unknown'
pr_url = None

base_commit = llvm_helper.git_execute(['rev-parse', fix_commit+'~']).strip()
changed_files = llvm_helper.git_execute(['show', '--name-only', '--format=', fix_commit]).strip()
# Component level
components = llvm_helper.infer_related_components(changed_files.split('\n'))
# File level
files = list(filter(lambda x: not x.count('/test/'), changed_files.split('\n')))
# Extract patch
patch = llvm_helper.git_execute(['show', fix_commit, '--', 'llvm/lib/*', 'llvm/include/*'])
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
for file in files:
    print(f'Parsing {file}')
    with open(os.path.join(llvm_helper.llvm_dir, file)) as f:
        source_code = f.read()
    tree = cxx_parser.parse(bytes(source_code, 'utf-8'))
    modified_funcs = set()
    for node in traverse_tree(tree):
        if node.type == 'function_declarator':
            func_name = node.children_by_field_name('declarator')[0].text.decode('utf-8')
            if func_name in patch:
                modified_funcs.add(func_name)
    bug_location_funcname[file] = list(modified_funcs)

# Extract tests
lit_test_dir = set(map(lambda x: os.path.dirname(x), filter(lambda x: x.count('/test/'), changed_files.split('\n'))))

# Write to files
metadata = {
'bug_id': issue_id,
'bug_type': issue_type,
'fix_commit': fix_commit,
'base_commit': base_commit,
'bug_location': {
    'components': list(components),
    'files': files,
    'bug_location_lineno': bug_location_lineno,
    'bug_location_funcname': bug_location_funcname,
},
'lit_test_dir': list(lit_test_dir),
'knowledge_cutoff': knowledge_cutoff,
'issue_url': issue_url,
'patch': patch,
}
print(json.dumps(metadata, indent=4))
