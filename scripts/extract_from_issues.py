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
import requests
import subprocess
from pathlib import Path
import tqdm
import llvm_helper

github_token = os.environ['LAB_GITHUB_TOKEN']
cache_dir = os.environ['LAB_ISSUE_CACHE']
postfix_extract = os.path.join(os.path.dirname(__file__), 'postfix_extract.py')
session = requests.Session()
session.headers.update({'X-GitHub-Api-Version': '2022-11-28', 'Authorization': f'Bearer {github_token}', 'Accept': 'application/vnd.github+json'})

issue_id_begin = 76663 # Since 2024-01-01
issue_id_end = int(sys.argv[1])

def fetch(issue_id):
    data_json_path = os.path.join(llvm_helper.dataset_dir, f'{issue_id}.json')
    if os.path.exists(data_json_path):
        return False

    issue_url = f'https://api.github.com/repos/llvm/llvm-project/issues/{issue_id}'
    issue = session.get(issue_url).json()
    if issue['state'] != 'closed' or issue['state_reason'] != 'completed':
        return False
    if 'issue' not in issue['html_url']:
        return False
    has_valid_label = False
    is_llvm_middleend = False
    for label in issue['labels']:
        label_name = label['name']
        if label_name == 'miscompilation':
            has_valid_label = True
        if 'crash' in label_name:
            has_valid_label = True
        if 'hang' in label_name:
            has_valid_label = True
        if 'llvm' in label_name or label_name == 'vectorizers':
            is_llvm_middleend = True
        if 'backend' in label_name or 'clang:' in label_name or 'clangd' in label_name or 'clang-tidy' in label_name:
            return False
        if label_name in ['invalid', 'wontfix', 'duplicate', 'undefined behavior', 'llvm:SelectionDAG', 'llvm:globalisel', 'llvm:regalloc']:
            return False
    if not has_valid_label:
        return False
    if not is_llvm_middleend:
        return False
    
    subprocess.check_output(['python3', postfix_extract, str(issue_id)],stderr=subprocess.DEVNULL)
    return True

os.makedirs(cache_dir, exist_ok=True)
success = 0
progress = tqdm.tqdm(range(issue_id_begin, issue_id_end + 1))
for issue_id in progress:
    cache_file = os.path.join(cache_dir, str(issue_id))
    if os.path.exists(cache_file):
        continue
    while True:
        try:
            if fetch(issue_id):
                success += 1
                progress.display(f'Success {success}')
            else:
                Path(cache_file).touch()
            break
        except Exception as e:
            print(e)
