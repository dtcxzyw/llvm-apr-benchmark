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
import re

llvm_dir = os.environ["LAB_LLVM_DIR"]
llvm_build_dir = os.environ["LAB_LLVM_BUILD_DIR"]
llvm_alive_tv = os.environ["LAB_LLVM_ALIVE_TV"]
dataset_dir = os.environ["LAB_DATASET_DIR"]


def git_execute(args):
    return subprocess.check_output(
        ["git", "-C", llvm_dir] + args, cwd=llvm_dir, stderr=subprocess.DEVNULL
    ).decode("utf-8")


def reset(commit):
    git_execute(["restore", "--staged", "."])
    git_execute(["clean", "-fdx"])
    git_execute(["checkout", "."])
    git_execute(["checkout", commit])


def infer_related_components(diff_files):
    prefixes = [
        "llvm/lib/Analysis/",
        "llvm/lib/Transforms/Scalar/",
        "llvm/lib/Transforms/Vectorize/",
        "llvm/lib/Transforms/Utils/",
        "llvm/lib/Transforms/IPO/",
        "llvm/lib/Transforms/",
        "llvm/lib/IR/",
    ]
    components = set()
    for file in diff_files:
        for prefix in prefixes:
            if file.startswith(prefix):
                component_name = (
                    file.removeprefix(prefix)
                    .split("/")[0]
                    .removesuffix(".cpp")
                    .removesuffix(".h")
                )
                if component_name != "":
                    if component_name.startswith("VPlan") or component_name.startswith(
                        "LoopVectoriz"
                    ):
                        component_name = "LoopVectorize"
                    if component_name.startswith("ScalarEvolution"):
                        component_name = "ScalarEvolution"
                    if component_name.startswith("ConstantFold"):
                        component_name = "ConstantFold"
                    if file.startswith("llvm/lib/IR"):
                        component_name = "IR"
                    components.add(component_name)
                    break
    return components


def get_langref_desc(keywords, commit):
    langref = str(git_execute(["show", f"{commit}:llvm/docs/LangRef.rst"]))
    desc = dict()
    sep = ".. _"
    for keyword in keywords:
        matched = re.search(f"\n'``{keyword}.+\n\\^", langref)
        if matched is None:
            continue
        beg, end = matched.span()
        beg = langref.rfind(sep, None, beg)
        end = langref.find(sep, end)
        desc[keyword] = langref[beg:end]
    return desc


def build(max_build_jobs: int):
    os.makedirs(llvm_build_dir, exist_ok=True)
    log = ""
    try:
        log += subprocess.check_output(
            [
                "cmake",
                "-S",
                llvm_dir + "/llvm",
                "-G",
                "Ninja",
                "-DCMAKE_BUILD_TYPE=RelWithDebInfo",
                "-DCMAKE_BUILD_SHARED_LIBS=ON",
                "-DCMAKE_C_COMPILER_LAUNCHER=ccache",
                "-DCMAKE_CXX_COMPILER_LAUNCHER=ccache",
                "-DLLVM_ENABLE_ASSERTIONS=ON",
                "-DLLVM_ABI_BREAKING_CHECKS=WITH_ASSERTS",
                "-DLLVM_ENABLE_WARNINGS=OFF",
                "-DLLVM_APPEND_VC_REV=OFF",
                "-DLLVM_TARGETS_TO_BUILD='X86;RISCV;AArch64;SystemZ'",
                "-DLLVM_PARALLEL_LINK_JOBS=4",
            ],
            stderr=subprocess.STDOUT,
            cwd=llvm_build_dir,
        ).decode()
        log += subprocess.check_output(
            ["cmake", "--build", ".", "-j", str(max_build_jobs), "-t", "opt"],
            stderr=subprocess.STDOUT,
            cwd=llvm_build_dir,
        ).decode()
        return (True, log)
    except subprocess.CalledProcessError as e:
        return (False, log + "\n" + e.output.decode())


def is_valid_comment(comment):
    if comment["author"] == "llvmbot":
        return False
    if comment["body"].startswith("/cherry-pick"):
        return False
    return True
