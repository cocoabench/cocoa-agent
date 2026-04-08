# Contributing to CocoaBench


> **Notice**: We will consider all tasks submitted by March 15, 2026 for inclusion in our paper submission to COLM 2026. We also warmly welcome additional task contributions after that date, as we will continue expanding CocoaBench and hope to include new tasks in future releases.

Thank you for your interest in contributing to CocoaBench! 🎉

We'd love to have your help in building a diverse and challenging benchmark. The best tasks come from real problems you've encountered — if it challenged you, it'll likely challenge AI agents too! Contributors with **3 accepted tasks** are eligible for co-authorship on the CocoaBench paper, which we plan to submit to a top-tier ML conference. We'll work with you through iterative refinement to help get your tasks accepted and ensure they meet benchmark standards. Particularly interesting or creative tasks may count for more at the discretion of project leads.

This guide will walk you through the process of creating and submitting a new task. Don't worry if it's your first time — we've tried to make it as straightforward as possible.

> 💡 **Quick tip:** Please encrypt your task files before submitting. This keeps our benchmark data safe from being found by LLM agents that can search online, which helps ensure fair evaluation for everyone.


## Quick Start

```bash
cd contrib

# 1. Create your task using the wizard
python create_task.py

# 2. Validate your task
python validate_task.py your-task-name

# 3. Test difficulty with an AI agent
#    Recommended: Gemini 3 Pro, ChatGPT Agent, Claude 4.5
#    At least one agent should fail — that's what makes a great benchmark task!
#    Update evaluation.md with results and chat transcript link

# 4. Encrypt before submitting PR
python encrypt_tasks.py --task your-task-name

# 5. Validate encryption
python validate_task.py your-task-name --check-encrypted

# 6. Submit Pull Request
```

---

## What Makes a Good Task?

Great tasks tend to share these qualities:

- 🧩 Require **multi-step solutions** — long-horizon tasks that take at least 5 minutes for humans or agents to complete, not just a single lookup
- ✓ Have **clear, deterministic answers** — evaluated via **exact match** (see [Answer Format Requirements](#answer-format-requirements))
- 🆕 **Distinctly different from existing tasks** — avoid duplicating scenarios already covered in the benchmark

> ⭐ **Required:** New tasks should highlight **combining GUI interaction with coding abilities**. For example, tasks where the agent must interact with a web UI to gather data, and write code to process or analyze it. These tasks test the agent's ability to seamlessly switch between visual/interactive skills and programming skills, which is a key capability for real-world agentic workflows.

Feel free to browse our [example tasks](https://cocoabench.github.io/#examples) for inspiration!

### Things to Keep in Mind

- ❌ Too easy (directly solvable by ChatGPT with searching)
- ❌ Time-sensitive data that will become stale (e.g., the solution relies on a website that will likely update)
- ❌ Subjective or opinion-based answers
- ❌ Impossible to evaluate automatically
- ❌ Require excessive resources or paid APIs

---

## Step-by-Step Guide

Here's a detailed walkthrough of creating your task. Take your time — quality matters more than speed!

### Step 1: Create Your Task Files

All commands should be run from the `contrib/` directory:

```bash
cd contrib
```

**Option A: Use the Task Wizard (Recommended)**
```bash
python create_task.py
```
The wizard will guide you through creating all required files and save them to `cocoabench-head/your-task-name/`.

**Option B: Create files manually**

```bash
mkdir -p ../cocoabench-head/your-task-name
```

Then create these files in your task folder:

- `instruction.md` - Task prompt for the AI agent
- `evaluation.md` - Expected answer and evaluation criteria
- `solution.md` - Step-by-step human solution
- `metadata.json` - Task metadata

See the [File Specifications](#file-specifications) below or check `cocoabench-example-tasks/` for examples.

### Step 2: Validate Your Task

```bash
python validate_task.py your-task-name
```

### Step 3: Test Difficulty with an AI Agent (Required)

> 🎯 **Goal:** At least one AI agent should fail to solve your task correctly. This is what makes a benchmark task valuable — if all agents can easily solve it, it won't help us measure progress!

**Recommended agents:** Gemini 3 Pro, ChatGPT Agent, Claude 4.5

After testing, update `evaluation.md` with the agent's performance and **include a link to the chat transcript**. If all agents succeed, consider making the task more challenging — we're happy to help refining great task ideas!

### Step 4: Encrypt Your Task

Almost there! Just one more step before submitting — encrypting your task. This keeps our benchmark data safe and ensures fair evaluation for everyone.

```bash
python encrypt_tasks.py --task your-task-name
```

This will:
- Encrypt `instruction.md` → `instruction.md.enc`
- Encrypt `evaluation.md` → `evaluation.md.enc`
- Encrypt `solution.md` → `solution.md.enc`
- Encrypt `metadata.json` → `metadata.json.enc`
- Create `canary.txt`
- Remove the original files

### Step 5: Validate Encryption

```bash
python validate_task.py your-task-name --check-encrypted
```

### Step 6: Submit Pull Request

You're ready to share your work! 🎉

```bash
git checkout -b task/your-task-name
git add cocoabench-head/your-task-name/
git commit -m "Add task: your-task-name"
git push origin task/your-task-name
```

Then open a PR on GitHub with:
- **Title:** `[New Task] your-task-name`
- **Description:** What your task is about, what skills it tests, and any interesting challenges you encountered

---

## Best Practices

1. **Ensure tasks are deterministic** – Same input should always yield same answer
2. **Include clear success criteria** – The answer should be unambiguous
3. **Test your task thoroughly** – Solve it yourself before submission

> ⚠️ **Exact Match Evaluation:** All tasks are evaluated using exact string match. This enables fully automated evaluation, ensures consistent and reproducible results, and makes it easy for others to use and extend the benchmark. The agent's output must exactly match the expected answer, so always specify the exact format in your instruction (e.g., "Provide as an integer without commas", "Use YYYY-MM-DD format", "Round to 2 decimal places"). See examples in `cocoabench-example-tasks/`.

---

## Need Help?

We're here to help! Here are some resources:

- 📂 Check existing tasks in `cocoabench-example-tasks/` for reference
- 🔍 Run `python validate_task.py --all` to explore how other tasks are structured

If you have questions or run into issues, feel free to open an issue on GitHub. We're happy to help!

Thanks for contributing — we really appreciate it! 🙏

---

# Reference

## Task Structure

Your contributed tasks will go in the `cocoabench-head/` folder. (The `cocoabench-example-tasks/` folder contains reference examples you can learn from.)

**Before encryption:**
```
cocoabench-head/
└── your-task-name/
    ├── instruction.md        # Task instruction (required)
    ├── evaluation.md         # Evaluation criteria (required)
    ├── solution.md           # Solution walkthrough (required)
    ├── metadata.json         # Task metadata (required)
    ├── Dockerfile            # Container setup (optional)
    ├── docker-compose.yaml   # Docker config (optional)
    └── assets/               # Resource URLs or files (optional)
        └── urls.txt          # URLs to download files
```

**After encryption (ready for PR):**
```
cocoabench-head/
└── your-task-name/
    ├── instruction.md.enc    # Encrypted instruction
    ├── evaluation.md.enc     # Encrypted evaluation
    ├── solution.md.enc       # Encrypted solution
    ├── metadata.json.enc     # Encrypted metadata
    ├── canary.txt            # Encryption key
    ├── Dockerfile            # (unchanged)
    ├── docker-compose.yaml   # (unchanged)
    └── assets/               # (unchanged, e.g., urls.txt)
```

---

## File Specifications

### 1. `instruction.md` – The Task Prompt

This file contains **only** the task prompt. It should be ready to send directly to an AI agent.

**Rules:**
- ✅ Start directly with the task description
- ✅ Use clear, unambiguous language
- ✅ Include all necessary context and constraints
- ✅ Always end with an **Output Format** section using `<answer>` tags
- ✅ Specify the exact answer format to ensure the answer is unique (for exact match evaluation)

**Template:**

```markdown
[Task description - clearly explain what the agent should do, 
including all necessary context and constraints]

**Output Format:**

Submit your answer in the following format:

\`\`\`
<answer>your_answer_here</answer>
\`\`\`
```

---

### 2. `evaluation.md` – Evaluation Criteria

Contains the expected answer and initialization resources.

**Template:**

```markdown
# Evaluation for Task [ID]

## Initialization

[Required resources: "Local: assets/", "Host UI: url", or "None"]

## Evaluation Criteria

**Expected Answer (Exact Match):** [The exact string that the agent's output must match]

## Agent Output Example

[Agent name]: [result], ([Correct/Incorrect], [time])
Chat transcript: [link to chat]
```

> 🎯 **Goal:** At least one agent should fail! Test with one agent (recommended: Gemini 3 Pro, ChatGPT Agent, or Claude 4.5) that fails and include the chat transcript link.

**⚠️ Exact Match Evaluation:**

All tasks are evaluated using exact string match. The expected answer should be a single, unambiguous value. Define the exact format in your instruction.md to ensure uniqueness (e.g., specify decimal places, date format, capitalization).

- ✅ Good: `52.10`, `London`, `2024-01-15`
- ❌ Avoid: Answers with multiple valid representations or open-ended outputs

**Initialization Types:**

| Type | Format |
|------|--------|
| Google Drive file | `Image: https://drive.google.com/file/d/...` |
| Google Drive folder | `Folder: https://drive.google.com/drive/folders/...` |
| Web UI | `Host UI: https://example.com/page` |
| Local files | `Local: assets/` |
| None needed | `None` |

**Multiple Resources:**

When a task requires multiple resources, list each on a separate line with clear labels:

```markdown
## Initialization

- Image: https://drive.google.com/file/d/abc123/view
- Data: https://drive.google.com/file/d/xyz789/view
- Host UI: https://example.com/app
```

---

### 3. `solution.md` – Human Solution Walkthrough

Documents how a human would solve the task step-by-step.

**Template:**

```markdown
# Solution

### Step 1: [Step Title]
[Detailed explanation with sub-steps if needed]

### Final Answer
[The correct answer]
```

---

### 4. `metadata.json` – Task Metadata

**Template:**

```json
{
  "id": 99,
  "name": "your-task-name",
  "brainstorm_by": "Your Name",
  "stage": "Brainstorm",
  "self_checked": "no",
  "reviewers": {},
  "task_properties": {},
  "human_performance": {}
}
```

**Fields:**

| Field | Type | Description |
|-------|------|-------------|
| `id` | integer | Unique task ID (wizard auto-generates) |
| `name` | string | Matches folder name (kebab-case) |
| `brainstorm_by` | string | Your name |
| `stage` | string | `"Brainstorm"` → `"Approved"` (after review) |
| `self_checked` | string | `"yes"` after you've verified the solution |
| `reviewers` | object | Filled by reviewers: `{"reviewer_1_name": "Pass"}` |
