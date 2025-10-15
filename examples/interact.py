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

import sys
import os
import json
from unidiff import PatchSet
import subprocess
import time

sys.path.append(os.path.join(os.path.dirname(os.environ["LAB_DATASET_DIR"]), "scripts"))
import llvm_helper
from lab_env import Environment as Env
from openai import OpenAI, RateLimitError, OpenAIError

token = os.environ["LAB_LLM_TOKEN"]
url = os.environ.get("LAB_LLM_URL", "https://api.deepseek.com")
model = os.environ.get("LAB_LLM_MODEL", "deepseek-reasoner")
basemodel_cutoff = os.environ.get("LAB_LLM_BASEMODEL_CUTOFF", "2023-12-31Z")
client = OpenAI(api_key=token, base_url=url)
temperature = float(os.environ.get("LAB_LLM_TEMP", "0.8"))
max_log_size = int(os.environ.get("LAB_LLM_MAX_LOG_SIZE", 1000000000))
max_chat_round = int(os.environ.get("LAB_LLM_MAX_CHAT_ROUND", 500))
max_test_count = int(os.environ.get("LAB_LLM_MAX_TEST_COUNT", 4))
max_other_tools_count = int(os.environ.get("LAB_LLM_MAX_OTHER_TOOLS_COUNT", 100))
max_tokens = int(os.environ.get("LAB_LLM_MAX_TOKENS", 5_000_000))
use_bisection = os.environ.get("LAB_USE_BISECTION", "ON") == "ON"
max_build_jobs = int(os.environ.get("LAB_MAX_BUILD_JOBS", os.cpu_count()))
fix_dir = os.environ["LAB_FIX_DIR"]
os.makedirs(fix_dir, exist_ok=True)


def append_message(messages, full_messages, message, dump=True):
    role = message["role"]
    content = message["content"]
    if dump:
        print(f"{role}: {content}")
    messages.append({"role": role, "content": content})
    full_messages.append(message)


def chat(messages, full_messages, chat_stats):
    reasoning_content = ""
    content = ""
    try:
        completion = client.chat.completions.create(
            model=model,
            messages=messages,
            timeout=300,
            temperature=temperature,
            stream=True,
            response_format={"type": "json_object"},
            stream_options={"include_usage": True},
            max_tokens=4000,
        )
        is_thinking = False
        is_answering = False
        for chunk in completion:
            if chunk.usage:
                if chunk.usage.prompt_tokens:
                    chat_stats["input_tokens"] += chunk.usage.prompt_tokens
                if (
                    chunk.usage.prompt_tokens_details
                    and chunk.usage.prompt_tokens_details.cached_tokens
                ):
                    chat_stats[
                        "cached_tokens"
                    ] += chunk.usage.prompt_tokens_details.cached_tokens
                if chunk.usage.completion_tokens:
                    chat_stats["output_tokens"] += chunk.usage.completion_tokens
                if chunk.usage.total_tokens:
                    chat_stats["total_tokens"] += chunk.usage.total_tokens
            delta = chunk.choices[0].delta
            if (
                hasattr(delta, "reasoning_content")
                and delta.reasoning_content is not None
            ):
                if not is_thinking:
                    print("Thinking:")
                    is_thinking = True
                print(delta.reasoning_content, end="", flush=True)
                reasoning_content += delta.reasoning_content
            elif delta.content is not None:
                if delta.content != "" and is_answering is False:
                    print("\nAnswer:")
                    is_answering = True
                print(delta.content, end="", flush=True)
                content += delta.content
            if len(content) > 200 and content.strip() == "":
                print("Aborting due to empty content")
                raise OpenAIError("Empty content")
        print("")
    except RateLimitError as e:
        print("Rate limit error, wait and retry")
        raise e
    except OpenAIError as e:
        print(e)
        append_message(
            messages,
            full_messages,
            {"role": "assistant", "content": f"Exception: {e}"},
            dump=False,
        )
        raise e
    except Exception as e:
        print(e)
        append_message(
            messages,
            full_messages,
            {"role": "assistant", "content": f"Exception: {e}"},
            dump=False,
        )
        return ""
    answer = {"role": "assistant", "content": content}
    if len(reasoning_content) > 0:
        answer["reasoning_content"] = reasoning_content
    if (
        len(messages) > 8
        and messages[-2]["role"] == "assistant"
        and messages[-2]["content"] == content
        and messages[-4]["role"] == "assistant"
        and messages[-4]["content"] == content
        and messages[-6]["role"] == "assistant"
        and messages[-6]["content"] == content
        and messages[-8]["role"] == "assistant"
        and messages[-8]["content"] == content
    ):
        append_message(
            messages,
            full_messages,
            {
                "role": "assistant",
                "content": "Infinite loop detected, aborting.",
            },
            dump=False,
        )
        raise OpenAIError("Infinite loop detected")
    append_message(messages, full_messages, answer, dump=False)
    return content


def get_system_prompt() -> str:
    return """You are an LLVM maintainer.
You are fixing a middle-end bug in the LLVM project.
You are given a description of the bug, including the stack trace and the failed test case.
You are also given the potential buggy code suggested by other maintainers.
Now you need to modify the code to fix the bug.
The bug fixing process is iterative. You can read, edit, and test the code multiple rounds.
All responses must be in JSON format as described below.

1. Read code
```json
{
  "action": "read",
  "start": 123,
  "end": 128,
}
```
It reads the code from line 123 to line 128 in the buggy file.
Note that the line numbers are 1-based and inclusive.
You are only allowed to read at most 250 lines of code each time.
2. Edit code
```json
{
    "action": "edit",
    "start": 123,
    "end": 128,
    "content": "new code",
}
It replaces the code from line 123 to line 128 in the buggy file with the new content.
Note that the line numbers are 1-based and inclusive.
3. Search
```
{
    "action": "search",
    "pattern": <search pattern>,
}
```
It returns the search results for the given pattern in the buggy file.
Actually, it returns the result of executing the following command:
```bash
grep -n <search pattern> <buggy file>
```
4. Preview
```json
{
    "action": "preview",
}
It previews the code changes you have made so far.
5. Reset
```json
{
    "action": "reset",
}
It resets all the code changes you have made so far.
6. Test
```json
{
    "action": "test",
}
After you think you have fixed the bug, you can run the test to check if the bug is fixed.
If the test passes, the bug fixing process ends. Otherwise, you will get some feedback from the test.
"""


def decorate_code_snippet(lines, start_lineno: int) -> str:
    decorated = []
    for i, line in enumerate(lines, start=start_lineno):
        decorated.append(f"{i:<5}{line}")
    return "\n".join(decorated)


def get_bug_info_use_bisection(env: Env):
    bisect_commit = env.get_bisect_commit()
    if bisect_commit is None:
        raise RuntimeError("Bisection info is unavailable")
    buggy_patch = llvm_helper.git_execute(
        ["show", bisect_commit, "--", "llvm/lib/*", "llvm/include/*"]
    )
    patch_set = PatchSet(buggy_patch)
    valid_file = None
    for file in patch_set:
        if not file.is_modified_file:
            continue
        if valid_file is None:
            valid_file = file
        else:
            raise Exception("Multiple modified files in the patch")
    if valid_file is None:
        raise Exception("No modified file in the patch")
    file_path = valid_file.path
    hint = "The bisection result shows that the following code changes may be relevant to the bug:\n"
    hint += buggy_patch
    hint += "\nNote that the code in the diff may vary from the current code in the repository, as the bisection commit may be old.\n"
    hint += "Please use the search action to locate the relevant code in the current version.\n"
    return file_path, hint


def get_bug_info(env: Env):
    lineno = env.get_hint_line_level_bug_locations()
    bug_file = next(iter(lineno.keys()))
    bug_hunks = next(iter(lineno.values()))
    base_commit = env.get_base_commit()
    source_code = str(
        llvm_helper.git_execute(["show", f"{base_commit}:{bug_file}"])
    ).splitlines()
    hint = "The following code snippets may be relevant to the bug:\n"
    separate = "============================================\n"
    for range in bug_hunks:
        start = range[0]
        end = range[1]
        hint += separate + decorate_code_snippet(source_code[start - 1 : end], start)
    hint += separate
    return bug_file, hint


def normalize_feedback(log) -> str:
    if not isinstance(log, list):
        if len(log) > max_log_size:
            return log[:max_log_size] + "\n<Truncated>..."
        return str(log)
    return json.dumps(llvm_helper.get_first_failed_test(log), indent=2)


def issue_fixing_iter(env: Env, file, messages, full_messages, chat_stats):
    while True:
        try:
            tgt = chat(messages, full_messages, chat_stats)
            break
        except RateLimitError:
            time.sleep(20)
            continue

    file_full_path = os.path.join(llvm_helper.llvm_dir, file)
    try:
        action = json.loads(tgt)
        action_name = action["action"]
        chat_stats[action_name + "_count"] = (
            chat_stats.get(action_name + "_count", 0) + 1
        )
        if action_name == "read":
            start = int(action["start"])
            end = int(action["end"])
            if end - start + 1 > 250:
                raise RuntimeError("Can only read at most 250 lines of code each time")
            with open(file_full_path, "r") as f:
                lines = f.read().splitlines()
                if start < 1 or end > len(lines) or start > end:
                    raise RuntimeError(
                        f"Invalid line range, the valid range is [1, {len(lines)}]"
                    )
                snippet = decorate_code_snippet(lines[start - 1 : end], start)
                append_message(
                    messages,
                    full_messages,
                    {"role": "user", "content": snippet},
                )
        elif action_name == "edit":
            start = int(action["start"])
            end = int(action["end"])
            with open(file_full_path, "r") as f:
                lines = f.read().splitlines()
            if start < 1 or end > len(lines) or start > end:
                raise RuntimeError(
                    f"Invalid line range, the valid range is [1, {len(lines)}]"
                )
            new_content = (
                "\n".join(lines[: start - 1])
                + action["content"]
                + "\n".join(lines[end:])
            )
            with open(file_full_path, "w") as f:
                f.write(new_content)
            append_message(
                messages,
                full_messages,
                {
                    "role": "user",
                    "content": "Success",
                },
            )
        elif action_name == "search":
            pattern = action["pattern"]
            try:
                grep_res = subprocess.check_output(
                    ["grep", "-n", pattern, file_full_path]
                ).decode("utf-8")
                append_message(
                    messages,
                    full_messages,
                    {
                        "role": "user",
                        "content": (
                            grep_res if grep_res.strip() != 0 else "No matches found"
                        ),
                    },
                )
            except subprocess.CalledProcessError:
                append_message(
                    messages,
                    full_messages,
                    {
                        "role": "user",
                        "content": "No matches found",
                    },
                )
        elif action_name == "preview":
            diff = llvm_helper.git_execute(["diff", "--", file])
            append_message(
                messages,
                full_messages,
                {
                    "role": "user",
                    "content": diff,
                },
            )
        elif action_name == "reset":
            env.reset()
            append_message(
                messages,
                full_messages,
                {"role": "user", "content": "Success"},
            )
        elif action_name == "test":
            res, log = env.check_full()
            if res:
                return True
            append_message(
                messages,
                full_messages,
                {
                    "role": "user",
                    "content": "Feedback:\n"
                    + normalize_feedback(log)
                    + "\nPlease adjust code according to the feedback.",
                },
            )
        else:
            append_message(
                messages,
                full_messages,
                {
                    "role": "user",
                    "content": f"Unrecognized action {action_name}",
                },
            )

    except Exception as e:
        append_message(
            messages,
            full_messages,
            {"role": "user", "content": f"Exception: {e}"},
        )
    return False


def normalize_messages(messages):
    return {"model": model, "messages": messages}


override = False


def fix_issue(issue_id):
    fix_log_path = os.path.join(fix_dir, f"{issue_id}.json")
    if not override and (
        os.path.exists(fix_log_path) or os.path.exists(fix_log_path + ".fail")
    ):
        print(f"Skip {issue_id}")
        return
    print(f"Fixing {issue_id}")
    env = Env(issue_id, basemodel_cutoff, max_build_jobs=max_build_jobs)
    if not env.is_single_file_fix():
        print("Multi-file bug is not supported")
        return
    messages = []
    full_messages = []  # Log with COT tokens
    append_message(
        messages, full_messages, {"role": "system", "content": get_system_prompt()}
    )
    bug_type = env.get_bug_type()
    desc = f"This is a {bug_type} bug.\n"
    env.reset()
    res, log = env.check_fast()
    assert not res
    desc += "Detailed information:\n"
    desc += normalize_feedback(log) + "\n"
    if use_bisection:
        try:
            file, info = get_bug_info_use_bisection(env)
        except Exception as e:
            print(str(e))
            with open(fix_log_path + ".fail", "w") as f:
                f.write(str(e))
            return
    else:
        file, info = get_bug_info(env)
    desc += f"Please modify the code in {file} to fix the bug.\n" + info
    append_message(messages, full_messages, {"role": "user", "content": desc})
    chat_stats = {
        "input_tokens": 0,
        "output_tokens": 0,
        "total_tokens": 0,
        "cached_tokens": 0,
        "test_count": 0,
    }
    try:
        for idx in range(max_chat_round):
            print(f"Round {idx + 1}")
            if issue_fixing_iter(env, file, messages, full_messages, chat_stats):
                cert = env.dump(normalize_messages(full_messages))
                print(cert)
                with open(fix_log_path, "w") as f:
                    f.write(json.dumps(cert, indent=2))
                return
            print(chat_stats)
            if chat_stats["total_tokens"] > max_tokens:
                print("Exceed max tokens")
                break
            if chat_stats["test_count"] >= max_test_count:
                print("Exceed max test count")
                break
            excceed_other_tools_count = False
            for key in chat_stats:
                if key.endswith("_count") and chat_stats[key] >= max_other_tools_count:
                    print(f"Exceed max {key}")
                    excceed_other_tools_count = True
                    break
            if excceed_other_tools_count:
                break
    except OpenAIError:
        pass
    cert = env.dump(normalize_messages(full_messages))
    with open(fix_log_path, "w") as f:
        f.write(json.dumps(cert, indent=2))


if len(sys.argv) == 1:
    task_list = sorted(
        map(lambda x: x.removesuffix(".json"), os.listdir(llvm_helper.dataset_dir))
    )
else:
    task_list = [sys.argv[1]]
    if len(sys.argv) == 3 and sys.argv[2] == "-f":
        override = True

for task in task_list:
    try:
        fix_issue(task)
    except Exception as e:
        print(e)
        exit(-1)
