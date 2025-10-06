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
import re
import string
from unidiff import PatchSet

sys.path.append(os.path.join(os.path.dirname(os.environ["LAB_DATASET_DIR"]), "scripts"))
import llvm_helper
from lab_env import Environment as Env
from openai import OpenAI
from openai import NOT_GIVEN

token = os.environ["LAB_LLM_TOKEN"]
url = os.environ.get("LAB_LLM_URL", "https://api.deepseek.com")
model = os.environ.get("LAB_LLM_MODEL", "deepseek-reasoner")
basemodel_cutoff = os.environ.get("LAB_LLM_BASEMODEL_CUTOFF", "2023-12-31Z")
client = OpenAI(api_key=token, base_url=url)
temperature = float(os.environ.get("LAB_LLM_TEMP", "0.8"))
# Seems not working, sad :(
enable_tooling = os.environ.get("LAB_LLM_ENABLE_TOOLING", "OFF") == "ON"
enable_streaming = os.environ.get("LAB_LLM_ENABLE_STREAMING", "OFF") == "ON"
max_log_size = int(os.environ.get("LAB_LLM_MAX_LOG_SIZE", 1000000000))
max_sample_count = int(os.environ.get("LAB_LLM_MAX_SAMPLE_COUNT", 4))
omit_issue_body = os.environ.get("LAB_LLM_OMIT_ISSUE_BODY", "ON") == "ON"
use_bisection = os.environ.get("LAB_USE_BISECTION", "ON") == "ON"
max_build_jobs = int(os.environ.get("LAB_MAX_BUILD_JOBS", os.cpu_count()))
fix_dir = os.environ["LAB_FIX_DIR"]
os.makedirs(fix_dir, exist_ok=True)

tools = []
tool_get_source_prompt = "If you need to view the source code, please call the `get_source` function. It is very helpful to address compilation errors by inspecting the latest LLVM API."
tool_get_source_desc = {
    "type": "function",
    "function": {
        "name": "get_source",
        "description": "Get the first 10 lines of the source code starting from the specified line number.",
        "parameters": {
            "type": "object",
            "properties": {
                "file": {
                    "type": "string",
                    "description": "Relative path to the source file. Must start with 'llvm/'",
                },
                "lineno": {
                    "type": "number",
                    "description": "The line number to start from. The first line is 1.",
                },
            },
            "required": ["file", "lineno"],
        },
    },
}


def tool_get_source(env, args):
    file = args["file"]
    if not file.startswith("llvm/") or file.contains(".."):
        return "Invalid file path"
    lineno = int(args["lineno"])
    path = os.path.join(llvm_helper.llvm_dir, file)
    env.reset()
    env.use_knowledge(f"source file: {file}:{lineno}", env.knowledge_cutoff)
    with open(path) as f:
        source = f.readlines()
    return "```cpp\n" + "".join(source[lineno - 1 : lineno + 9]) + "```\n"


tools.append((tool_get_source_prompt, tool_get_source_desc, tool_get_source))

tool_get_instruction_docs_prompt = "If you need the definition of an LLVM instruction or an intrinsic, please call the `get_instruction_docs` function. It is useful to understand new poison-generating flags."
tool_get_instruction_docs_desc = {
    "type": "function",
    "function": {
        "name": "get_instruction_docs",
        "description": "Get the documentation of an LLVM instruction or an intrinsic.",
        "parameters": {
            "type": "object",
            "properties": {
                "inst": {
                    "type": "string",
                    "description": "The name of the instruction or intrinsic (e.g., 'add', 'llvm.ctpop'). Do not include the suffix for type mangling.",
                }
            },
            "required": ["inst"],
        },
    },
}


def tool_get_instruction_docs(env, args):
    inst = args["inst"]
    return env.get_langref_desc([inst])[inst]


tools.append(
    (
        tool_get_instruction_docs_prompt,
        tool_get_instruction_docs_desc,
        tool_get_instruction_docs,
    )
)


tool_check_refinement_prompt = "If you want to check if an optimization is correct, please call the `check_refinement` function. If the optimization is incorrect, the function will provide a counterexample."
tool_check_refinement_desc = {
    "type": "function",
    "function": {
        "name": "check_refinement",
        "description": "Check if an optimization is correct. If the optimization is incorrect, the function will provide a counterexample.",
        "parameters": {
            "type": "object",
            "properties": {
                "src": {
                    "type": "string",
                    "description": "The original LLVM function.",
                },
                "tgt": {
                    "type": "string",
                    "description": "The optimized LLVM function. The name of target function should be the same as the original function.",
                },
            },
            "required": ["src", "tgt"],
        },
    },
}


def tool_check_refinement(env, args):
    src = args["src"]
    tgt = args["tgt"]
    env.use_knowledge("alive2", env.knowledge_cutoff)
    if "ptr" in src and "target datalayout" not in src:
        src = f'target datalayout = "p:8:8:8"\n{src}'
    if "ptr" in tgt and "target datalayout" not in tgt:
        tgt = f'target datalayout = "p:8:8:8"\n{tgt}'

    res, log = llvm_helper.alive2_check(src, tgt, "-src-unroll=8 -tgt-unroll=8")
    if res:
        return "The optimization is correct."
    return log


tools.append(
    (tool_check_refinement_prompt, tool_check_refinement_desc, tool_check_refinement)
)


def get_tooling_prompt():
    if not enable_tooling:
        return ""
    prompt = "You are allowed to use the following functions when fixing this bug:\n"
    for x in tools:
        prompt += x[0] + "\n"
    return prompt


def get_available_tools():
    if not enable_tooling:
        return NOT_GIVEN
    return [x[1] for x in tools]


def dispatch_tool_call(env, name, args):
    assert enable_tooling

    try:
        args = json.loads(args)
        for tool in tools:
            if tool[1]["function"]["name"] == name:
                return tool[2](env, args)
    except Exception as e:
        return str(e)


def append_message(messages, full_messages, message, dump=True):
    role = message["role"]
    content = message["content"]
    if dump:
        print(f"{role}: {content}")
    messages.append({"role": role, "content": content})
    full_messages.append(message)


def chat_with_tooling(env, messages, full_messages):
    reasoning_content = ""
    content = ""
    try:
        while True:
            response = (
                client.chat.completions.create(
                    model=model,
                    messages=messages,
                    timeout=300,
                    temperature=temperature,
                    tools=get_available_tools(),
                )
                .choices[0]
                .message
            )
            if response.tool_calls is None or len(response.tool_calls) == 0:
                break

            if hasattr(response, "reasoning_content"):
                reasoning_content += response.reasoning_content
                print("Thinking:")
                print(response.reasoning_content)

            messages.append(response)

            for tool_call in response.tool_calls:
                name = tool_call.function.name
                args = tool_call.function.arguments
                res = dispatch_tool_call(env, name, args)
                print(f"Call tool {name} with")
                print(args)
                print("Result: ", res)
                full_messages.append(
                    {
                        "role": "assistant - funccall",
                        "tool_name": name,
                        "tool_args": args,
                        "tool_res": res,
                    }
                )
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "content": str(res),
                    }
                )

        print("assistant:")
        if hasattr(response, "reasoning_content"):
            reasoning_content += response.reasoning_content
            print("Thinking:")
            print(response.reasoning_content)
        content = response.content
        print("Answer:")
        print(content)
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
    append_message(messages, full_messages, answer, dump=False)
    return content


def chat_with_streaming(env, messages, full_messages):
    reasoning_content = ""
    content = ""
    try:
        completion = client.chat.completions.create(
            model=model,
            messages=messages,
            timeout=300,
            temperature=temperature,
            stream=True,
        )
        is_thinking = False
        is_answering = False
        for chunk in completion:
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
    append_message(messages, full_messages, answer, dump=False)
    return content


def chat(env, messages, full_messages):
    if enable_streaming:
        assert not enable_tooling
        return chat_with_streaming(env, messages, full_messages)
    return chat_with_tooling(env, messages, full_messages)


format_requirement = """
Please answer with the code directly. Do not include any additional information in the output.
Please answer with the complete code snippet (including the unmodified part) that replaces the original code. Do not answer with a diff.
"""


def get_system_prompt() -> str:
    return (
        """You are an LLVM maintainer.
You are fixing a middle-end bug in the LLVM project."""
        + format_requirement
        + get_tooling_prompt()
    )


def get_hunk(env: Env) -> str:
    lineno = env.get_hint_line_level_bug_locations()
    bug_file = next(iter(lineno.keys()))
    bug_hunks = next(iter(lineno.values()))
    min_lineno = 1e9
    max_lineno = 0
    for range in bug_hunks:
        min_lineno = min(min_lineno, range[0])
        max_lineno = max(max_lineno, range[1])
    margin = 30
    base_commit = env.get_base_commit()
    source_code = str(
        llvm_helper.git_execute(["show", f"{base_commit}:{bug_file}"])
    ).splitlines()
    min_lineno = max(min_lineno - margin, 1)
    max_lineno = min(max_lineno + margin, len(source_code))
    hunk = "\n".join(source_code[min_lineno - 1 : max_lineno])
    return bug_file, hunk


def extract_code_from_reply(tgt: str):
    if tgt.startswith("```"):
        tgt = tgt.strip().removeprefix("```cpp").removeprefix("```").removesuffix("```")
        return tgt
    # Match the last code block
    re1 = re.compile("```cpp([\s\S]+)```")
    matches = re.findall(re1, tgt)
    if len(matches) > 0:
        return matches[-1]
    re2 = re.compile("```([\s\S]+)```")
    matches = re.findall(re2, tgt)
    if len(matches) > 0:
        return matches[-1]
    return tgt


def modify_inplace(file, src, tgt):
    tgt = extract_code_from_reply(tgt)
    path = os.path.join(llvm_helper.llvm_dir, file)
    with open(path) as f:
        code = f.read()
    code = code.replace(src, tgt)
    with open(path, "w") as f:
        f.write(code)


def get_issue_desc(env: Env) -> str:
    issue = env.get_hint_issue()
    if issue is None:
        return ""
    title = issue["title"]
    body = "<omitted>" if omit_issue_body else issue["body"]
    return f"Issue title: {title}\nIssue body: {body}\n"


def normalize_feedback(log) -> str:
    if not isinstance(log, list):
        if len(log) > max_log_size:
            return log[:max_log_size] + "\n<Truncated>..."
        return str(log)
    return json.dumps(llvm_helper.get_first_failed_test(log), indent=2)


def issue_fixing_iter(
    env: Env, file, src, messages, full_messages, context_requirement
):
    env.reset()
    tgt = chat(env, messages, full_messages)
    modify_inplace(file, src, tgt)
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
            + "\nPlease adjust code according to the feedback."
            + format_requirement
            + context_requirement,
        },
    )
    return False


def normalize_messages(messages):
    return {"model": model, "messages": messages}


override = False


def fix_issue(issue_id):
    fix_log_path = os.path.join(fix_dir, f"{issue_id}.json")
    if not override and os.path.exists(fix_log_path):
        print(f"Skip {issue_id}")
        return
    print(f"Fixing {issue_id}")
    env = Env(issue_id, basemodel_cutoff, max_build_jobs=max_build_jobs)
    bug_funcs = env.get_hint_bug_functions()
    if not env.is_single_func_fix():
        print("Multi-func bug is not supported")
        return
    messages = []
    full_messages = []  # Log with COT tokens
    append_message(
        messages, full_messages, {"role": "system", "content": get_system_prompt()}
    )
    bug_type = env.get_bug_type()
    bug_func_name = next(iter(bug_funcs.values()))[0]
    component = next(iter(env.get_hint_components()))
    desc = f"This is a {bug_type} bug in {component}.\n"
    desc += get_issue_desc(env)
    env.reset()
    res, log = env.check_fast()
    assert not res
    desc += "Detailed information:\n"
    desc += normalize_feedback(log) + "\n"
    file, hunk = get_hunk(env)
    desc += f"Please modify the following code in {file}:{bug_func_name} to fix the bug:\n```cpp\n{hunk}\n```\n"
    prefix = "\n".join(hunk.splitlines()[:5])
    suffix = "\n".join(hunk.splitlines()[-5:])
    context_requirement = f"Please make sure the answer includes the prefix:\n```cpp\n{prefix}\n```\nand the suffix:\n```cpp\n{suffix}\n```\n"
    desc += format_requirement + context_requirement
    append_message(messages, full_messages, {"role": "user", "content": desc})
    try:
        for idx in range(max_sample_count):
            print(f"Round {idx + 1}")
            if issue_fixing_iter(
                env, file, hunk, messages, full_messages, context_requirement
            ):
                cert = env.dump(normalize_messages(full_messages))
                print(cert)
                with open(fix_log_path, "w") as f:
                    f.write(json.dumps(cert, indent=2))
                return
    except Exception:
        pass
    cert = env.dump(normalize_messages(full_messages))
    with open(fix_log_path, "w") as f:
        f.write(json.dumps(cert, indent=2))

def canonicalize_line(line: str) -> str:
    special_chars = set(string.punctuation + string.whitespace)
    canonicalized = line.strip()
    canonicalized = "".join(
        [" " if c in special_chars else c for c in canonicalized]
    )
    return canonicalized

def get_hunk_from_patch(base_commit: str, patch: str):
    patch_set = PatchSet(patch)
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
    lines = dict()
    llvm_helper.git_execute(["checkout", base_commit, "--", file_path])
    with open(os.path.join(llvm_helper.llvm_dir, file_path)) as f:
        source_lines = f.readlines()
        for lineno, line in enumerate(source_lines):
            canonicalized = canonicalize_line(line)
            if canonicalized in lines:
                lines[canonicalized].append(lineno)
            else:
                lines[canonicalized] = [lineno]

    min_pos = 1e9
    max_pos = 0
    mapping_hint = []
    for hunk in valid_file:
        for line in hunk:
            if line.is_removed:
                continue
            pos = line.target_line_no
            min_pos = min(min_pos, pos)
            max_pos = max(max_pos, pos)
            content = canonicalize_line(line.value)
            if content in lines and len(lines[content]) == 1:
                source_pos = lines[content][0]
                mapping_hint.append((pos, source_pos))
    if min_pos > max_pos:
        raise Exception("No valid change")
    if len(mapping_hint) == 0:
        raise Exception("No valid line mapping found")
    start_pos = 1e9
    end_pos = 0
    for src_pos, tgt_pos in mapping_hint:
        start = tgt_pos - (src_pos - min_pos)
        end = tgt_pos + (max_pos - src_pos)
        start_pos = min(start_pos, start)
        end_pos = max(end_pos, end)
    if start_pos > end_pos:
        raise Exception("Invalid line mapping")
    if end_pos - start_pos > 100:
        raise Exception("The hunk is too large")
    margin = 30
    start_pos = max(start_pos - margin, 0)
    end_pos = min(end_pos + margin, len(source_lines) - 1)
    hunk_lines = "".join(source_lines[start_pos : end_pos + 1])
    return file_path, hunk_lines


def fix_issue_without_hint(issue_id):
    fix_log_path = os.path.join(fix_dir, f"{issue_id}.json")
    if not override and os.path.exists(fix_log_path):
        print(f"Skip {issue_id}")
        return
    print(f"Fixing {issue_id}")
    env = Env(issue_id, basemodel_cutoff, max_build_jobs=max_build_jobs)
    bisect_commit = env.get_bisect_commit()
    if bisect_commit is None:
        print("Bisection info is unavailable")
        return
    if not env.is_single_func_fix():
        print("Multi-func bug is not supported")
        return
    buggy_patch = llvm_helper.git_execute(
        ["show", bisect_commit, "--", "llvm/lib/*", "llvm/include/*"]
    )
    try:
        file, hunk = get_hunk_from_patch(env.get_base_commit(), buggy_patch)
    except Exception as e:
        print(e)
        return
    env.reset()
    messages = []
    full_messages = []  # Log with COT tokens
    append_message(
        messages, full_messages, {"role": "system", "content": get_system_prompt()}
    )
    bug_type = env.get_bug_type()
    desc = f"This is a {bug_type} bug.\n"
    desc += "The bisection result shows that the bug is introduced in the following commit:\n"
    desc += buggy_patch + "\n"
    res, log = env.check_fast()
    assert not res
    desc += "Detailed information:\n"
    desc += normalize_feedback(log) + "\n"
    desc += f"Please modify the following code in {file} to fix the bug:\n```cpp\n{hunk}\n```\n"
    prefix = "\n".join(hunk.splitlines()[:5])
    suffix = "\n".join(hunk.splitlines()[-5:])
    context_requirement = f"Please make sure the answer includes the prefix:\n```cpp\n{prefix}\n```\nand the suffix:\n```cpp\n{suffix}\n```\n"
    desc += format_requirement + context_requirement
    append_message(messages, full_messages, {"role": "user", "content": desc})
    try:
        for idx in range(max_sample_count):
            print(f"Round {idx + 1}")
            if issue_fixing_iter(
                env, file, hunk, messages, full_messages, context_requirement
            ):
                cert = env.dump(normalize_messages(full_messages))
                print(cert)
                with open(fix_log_path, "w") as f:
                    f.write(json.dumps(cert, indent=2))
                return
    except Exception:
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
        if use_bisection:
            fix_issue_without_hint(task)
        else:
            fix_issue(task)
    except Exception as e:
        print(e)
        exit(-1)
