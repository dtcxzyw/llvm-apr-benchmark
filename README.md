# LLVM APR Benchmark: A Large-Scale Automated Program Repair Benchmark of Real-World LLVM Middle-End Bugs

## Motivation

The compiler is a critical infrastructure in the software development. The LLVM compiler infrastructure is widely used in both academia and industry. However, due to its inherent complexity, the LLVM compiler still contains many bugs that can be triggered in edge cases. As one of the LLVM maintainers, my job is to provide the minimal reproducible test cases for issues from fuzzers/ downstream users, and fix these bugs (or assign them to the right person). However, the process is time-consuming and boring. Thanks to the recent advances in compiler testing, we can automatically generate interesting test cases that trigger bugs and automatically reduce the tests to minimal ones. If we can also perform bug localization and repair automatically, it will significantly reduce the workload of us maintainers! Recently, LLM-based automated program repair (APR) techniques have been proposed. We have seen some successful cases in APR benchmarks like Defects4J and SWE-bench. But I believe that fixing LLVM bugs is more challenging than existing benchmarks due to its large C/C++ codebase, complex logic, long history, and the need for domain-specific knowledge. Therefore, I build this benchmark to see if we can automatically repair real-world LLVM bugs with the help of large language models and APR techniques. I hope this benchmark can help both SE researchers and LLVM community to understand how APR techniques work on a large-scale, real-world C/C++ project.

## Dataset Description

In this benchmark, we only focus on three kinds of bugs in the LLVM middle-end:
+ Crash: the compiler terminates exceptionally or hits an assertion failure (LLVM is built with `-DLLVM_ENABLE_ASSERTIONS=ON -DLLVM_ABI_BREAKING_CHECKS=WITH_ASSERTS`).
+ Miscompilation: the compiler generates incorrect program from a well-defined source code.
+ Hang: the compiler runs into an infinite loop or fails to reach a fixpoint.

All bugs can be triggered with an `opt` command and a small piece of LLVM textual IR.

This dataset collects some fixed LLVM middle-end bugs from GitHub issues since 2024-01-01. Each issue contains issue description, test cases, a reference patch, and some hints. All issues are checked against the following criteria:

+ At least one of the given test cases can be used to reproduce the bug at a specific commit (`base_commit`). For most of the miscompilation bugs, the `src` and `tgt` functions will be checked with alive2, an automatic refinement verification tool for LLVM. If miscompilation happens, `alive-tv` will provide a counterexample. The remaining miscompilation bugs will be checked by `lli`.
+ `opt` passes all the given tests after fixing the bug with the given reference patch (`patch`).
+ `opt` passes all regression tests at a specific commit (`hints.fix_commit`).

Take [Issue121459](https://github.com/llvm/llvm-project/issues/121459) as an example:
```jsonc
{
  // Identifier of the bug. It can be an issue number, a pull request number,
  // or a commit hash.
  "bug_id": "121459",
  // Points to issue/PR/commit url
  "issue_url": "https://github.com/llvm/llvm-project/issues/121459",
  // Bug type: crash/miscompilation/hang
  "bug_type": "miscompilation",
  // Fixes should be applied at the base commit
  "base_commit": "68d265666e708bad1c63b419b6275aaba1a7dcd2",
  // Knowledge cutoff date. It is not allowed to use the web knowledge base
  // after this date or use a large language model trained with newer
  // information. Please check the "Rules" section for exemptions.
  "knowledge_cutoff": "2025-01-02T09:03:32Z",
  // Regression test directories
  "lit_test_dir": [
    "llvm/test/Transforms/InstCombine"
  ],
  // Bug localization hints at different granularity levels.
  // Note that this information is provided in a best-effort way.
  // They are not guaranteed to be available or accurate.
  "hints": {
    "fix_commit": "a4d92400a6db9566d84cb4b900149e36e117f452",
    "components": [
      "InstCombine"
    ],
    "bug_location_lineno": {
      "llvm/lib/Transforms/InstCombine/InstructionCombining.cpp": [
        [
          2782,
          2787
        ],
        [
          2838,
          2843
        ],
        [
          2847,
          2852
        ]
      ]
    },
    "bug_location_funcname": {
      "llvm/lib/Transforms/InstCombine/InstructionCombining.cpp": [
        "foldGEPOfPhi"
      ]
    }
  },
  // A reference patch extracted from hints.fix_commit
  "patch": "<omitted>",
  // Minimal reproducible tests
  "tests": [
    {
      "file": "llvm/test/Transforms/InstCombine/opaque-ptr.ll",
      "commands": [
        "opt -S -passes='instcombine<no-verify-fixpoint>' < %s"
      ],
      "tests": [
        {
          "test_name": "gep_of_phi_of_gep_different_type",
          "test_body": "<omitted>"
        },
        {
          "test_name": "gep_of_phi_of_gep_flags2",
          "test_body": "<omitted>"
        },
        {
          "test_name": "gep_of_phi_of_gep_flags1",
          "test_body": "<omitted>"
        }
      ]
    }
  ],
  // Issue description
  "issue": {
    "title": "[InstCombine] GEPNoWrapFlags is propagated incorrectly",
    "body": "<omitted>",
    "author": "dtcxzyw",
    "labels": [
      "miscompilation",
      "llvm:instcombine"
    ],
    "comments": []
  },
  "verified": true
}
```

As of January 20, 2025, this benchmark contains 226 issues. You can run `python3 scripts/dataset_summary.py` locally to obtain the latest statistics.
```
Total issues: 226
Verified issues: 226 (100.00%)

Bug type summary:
  miscompilation: 84
  crash: 135
  hang: 7

Bug component summary (Total = 43):
  LoopVectorize: 60
  SLPVectorizer: 50
  InstCombine: 47
  ScalarEvolution: 10
  VectorCombine: 7
  ValueTracking: 5
  IR: 5
  ConstraintElimination: 4
  InstructionSimplify: 4
  Local: 3
  MemCpyOptimizer: 3
  ...

Label summary:
  miscompilation: 86
  crash: 82
  vectorizers: 67
  llvm:instcombine: 50
  llvm:SLPVectorizer: 50
  crash-on-valid: 44
  llvm:transforms: 31
  llvm:analysis: 14
  llvm:SCEV: 11
  release:backport: 9
  confirmed: 9
  llvm:crash: 8
  regression: 6
  llvm:hang: 6
  floating-point: 4
  ...

Changed files count summary:
  Average: 1.15
  Max: 4
  Min: 1
  Median: 1

Inserted lines summary:
  Average: 11.04
  Max: 164
  Min: 0
  Median: 6

Deleted lines summary:
  Average: 5.64
  Max: 169
  Min: 0
  Median: 2

Test count summary:
  Average: 3.73
  Max: 107
  Min: 1
  Median: 1

Patch summary:
  Single file fix: 201 (88.94%)
  Single func fix: 173 (76.55%)
  Single hunk fix: 129 (57.08%)
```

You can see from the statistics that more than half of the bugs can be fixed with a single hunk. So I believe most of bugs can be fixed with the aid of LLM-based APR techniques :)

## Getting Started

### Prerequisites

+ A C++17 compatible compiler
+ ninja
+ ccache
+ Pre-built LLVM core libraries
+ [alive-tv](https://github.com/AliveToolkit/alive2)

You can follow the [Dockerfile](./Dockerfile) to setup the environment.

### Installation

```bash
git clone https://github.com/dtcxzyw/llvm-apr-benchmark.git
cd llvm-apr-benchmark
pip3 install -r requirements.txt
mkdir -p work && cd work
git clone https://github.com/llvm/llvm-project.git
```

Please set the following environment variables:
```bash
export LAB_LLVM_DIR=<path-to-llvm-src>
export LAB_LLVM_BUILD_DIR=<path-to-llvm-build-dir>
export LAB_LLVM_ALIVE_TV=<path-to-alive-tv>
export LAB_DATASET_DIR=<path-to-llvm-apr-benchmark>/dataset
export LAB_FIX_DIR=<path-to-llvm-apr-benchmark>/examples/fixes
```

### Usage

This benchmark provides two helper modules to allow researchers to easily interact with LLVM and this benchmark.

To use these two helpers:
```python
sys.path.append(os.path.join(os.path.dirname(os.environ["LAB_DATASET_DIR"]), "scripts"))
import llvm_helper
from lab_env import Environment as Env
```

[llvm_helper](./scripts/llvm_helper.py)
```python
# Environment variables
llvm_helper.llvm_dir # os.environ["LAB_LLVM_DIR"]
llvm_helper.llvm_build_dir # os.environ["LAB_LLVM_BUILD_DIR"]
llvm_helper.llvm_alive_tv # os.environ["LAB_LLVM_ALIVE_TV"]
llvm_helper.dataset_dir # os.environ["LAB_DATASET_DIR"]

# Execute git commands on the llvm source tree
source_code = llvm_helper.git_execute(['show', f'{commit}:{file_path}'])

# Get information of first failed test from the result of Environment.check_fast/check_full
res, log = env.check_fast()
if isinstance(log, list):
  test = llvm_helper.get_first_failed_test(log)
```
[lab_env](./scripts/lab_env.py)
```python
env = Env(
    # Load an issue from dataset/{issue_id}.json
    issue_id,
    # The knowledge cutoff date of LLM
    base_model_knowledge_cutoff = "2024-01-01Z",
    # Max concurrent jobs for build/test
    max_build_jobs=None,
    max_test_jobs=None,
  )

# If any external knowledge is used, please call this function.
env.use_knowledge(url = "<url>", date = "<date>")
# Reset the source tree to the base commit. Please call it before each attempt.
env.reset()
# Build llvm
res, log = env.build()
# Provide a certificate with the patch and verification result
certificate = env.dump()
# Perform build + test
res, log = env.check_fast()
# Perform build + test + lit regression test
res, log = env.check_full()
# Issue information (always available)
bug_type = env.get_bug_type()
base_commit = env.get_base_commit()
tests = env.get_tests()
# Hints (optional)
fix_commit = env.get_hint_fix_commit()
components = env.get_hint_components()
files = env.get_hint_files()
functions = env.get_hint_bug_functions()
linenos = env.get_hint_line_level_bug_locations()
# Issue description (optional)
issue = env.get_hint_issue()
# Collect instructions and intrinsics from the given LLVM IR.
# Then it will retrieve descriptions from llvm/docs/LangRef.dst.
# It is useful for LLMs to understand new flags/attributes/metadata.
keywords = env.get_ir_keywords(llvm_ir)
desc = env.get_langref_desc(keywords)
```

Here is a simple repair loop:
```python
env = Env(...)
# System prompts and user prompts
messages = []
while True:
  # Reset the LLVM source code tree
  env.reset()
  # Get information from env
  ...
  # Chat with LLM
  ...
  # Modify the source code in place
  ...
  res, log = env.check_full()
  if res:
    # The bug is fixed successfully
    cert = json.dumps(env.dump(log = messages), indent=2)
    print(cert)
    break
  # Append the feedback into user prompts for the next iteration
  messages.append(construct_user_prompt_from_feedback(log))
```

I have drafted a poor [baseline](./examples/baseline.py) which is powered by [DeepSeek-R1](https://www.deepseek.com). This baseline implementation is only for reference purposes since I am neither an expert in LLM nor APR.

### Rules

To claim that your APR tool successfully fixes a bug, please obey the following rules:
+ Knowledge allowed to use:
  + Any static content/ dynamic feedback provided by `lab_env.Environment`
  + Any content in the LLVM source tree before the base commit
  + Large language model trained with dataset before the knowledge cutoff date
  + Any other content on the web created before the knowledge cutoff date
+ `opt` with this patch passes both the given tests and the regression testsuite.

## License

This project is licensed under the Apache License 2.0. Please see the [LICENSE](./LICENSE) for details.

Please cite this work with the following BibTex entry:
```bibtex
@misc{llvm-apr-benchmark,
  title = {LLVM APR Benchmark: A Large-Scale Automated Program Repair Benchmark of Real-World LLVM Middle-End Bugs},
  url = {https://github.com/dtcxzyw/llvm-apr-benchmark},
  author = {Yingwei Zheng},
  year = {2025},
}
```
