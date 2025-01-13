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
import subprocess

llvm_dir = os.environ['LAB_LLVM_DIR']
llvm_build_dir = os.environ['LAB_LLVM_BUILD_DIR']
llvm_alive_tv = os.environ['LAB_LLVM_ALIVE_TV']
dataset_dir = os.environ['LAB_DATASET_DIR']

def git_execute(args):
    return subprocess.check_output(['git', '-C', llvm_dir] + args, cwd=llvm_dir).decode('utf-8')

def infer_related_components(diff_files):
    prefixes = [
    'llvm/lib/Analysis/',
    'llvm/lib/Transforms/Scalar/',
    'llvm/lib/Transforms/Vectorize/',
    'llvm/lib/Transforms/Utils/',
    'llvm/lib/Transforms/IPO/',
    'llvm/lib/Transforms/',
    'llvm/lib/IR/',
    ]
    components = set()
    for file in diff_files:
        for prefix in prefixes:
            if file.startswith(prefix):
                component_name = file.removeprefix(prefix).split('/')[0].removesuffix('.cpp').removesuffix('.h')
                if component_name != '':
                    if component_name.startswith('VPlan'):
                        component_name = 'LoopVectorize'
                    components.add(component_name)
                    break
        if file.startswith('llvm/lib/IR/Operator'):
            components.add(component_name)
    return components
