# Scaling Up CocoaBench Data

This guide explains how to create **scaled variants** of existing tasks. Scaling up means producing new problem instances derived from an original task — with a new instruction, a new answer, and (optionally) new asset files — while preserving the same evaluation structure and difficulty profile.

---

## Table of Contents

1. [Prerequisites — Inspecting Original Tasks](#1-prerequisites--inspecting-original-tasks)
2. [Contributing Scaled Data — Type 1 (metadata.json tasks)](#2-contributing-scaled-data--type-1)
3. [Contributing Scaled Data — Type 2 (Dockerfile tasks)](#3-contributing-scaled-data--type-2)
4. [Reference Solutions](#4-reference-solutions)

---

## 1. Prerequisites — Inspecting Original Tasks

Before creating a scaled variant, you need to decrypt and read the original task to understand its structure, instruction format, and expected answer.

There are **two task types**, each with a different decryption workflow:

### Type 1: Tasks with `metadata.json(.enc)`

These tasks store their instruction, evaluation, metadata, and solution in separate Markdown/JSON files that are encrypted via `encrypt_tasks.py`.

```bash
cd contrib/
python decrypt_tasks.py                    # Decrypt all tasks
```

After decryption you will see the plaintext files:
- `instruction.md` — the task prompt
- `evaluation.md` — expected answer
- `metadata.json` — task metadata
- `solution.md` — step-by-step human solution

### Type 2: Tasks with `Dockerfile`

These tasks package their instruction inside `task.yaml` and their evaluation inside `test.py`, both encrypted via the top-level `encrypt.py`.

```bash
# Run from the project root (not contrib/)
python decrypt.py                          # Decrypt all tasks
```

After decryption you will see the plaintext files:
- `task.yaml` — task instruction and configuration
- `test.py` — automated test / evaluation

---

## 2. Contributing Scaled Data — Type 1

### 2.1 Naming Convention

```
<original-task-name>-<id>
```

For example, if the original task is `arrow-hunt`, your scaled variant might be named `arrow-hunt-2`, `arrow-hunt-3`, etc.

### 2.2 What to Provide

Create a new task folder under `cocoabench-head/` with the following files:

| File | Description |
|------|-------------|
| `instruction.md` | **New** problem statement (varied from the original) |
| `evaluation.md` | **New** expected answer and evaluation criteria |
| `metadata.json` | Your name, the new task name, and other metadata |
| `solution.md` | **New** step-by-step solution for the scaled variant |
| `assets/` | New asset files or links, if applicable |

> **Tip:** Keep the same overall structure and difficulty as the original task. Change the specific data, parameters, or problem so that the answer is different.

### 2.3 Encryption

Once your files are ready, encrypt them before submitting:

```bash
cd contrib/
python encrypt_tasks.py --task <your-new-task-name>
```

This will encrypt `instruction.md`, `evaluation.md`, `metadata.json`, and `solution.md` into their `.enc` counterparts, create `canary.txt`, and remove the plaintext originals.

---

## 3. Contributing Scaled Data — Type 2

### 3.1 Naming Convention

Same as Type 1:

```
<original-task-name>-<id>
```

### 3.2 What to Provide

Create a new task folder under `cocoabench-head/` with the following files:

| File | Description |
|------|-------------|
| `task.yaml` | **New** instruction and file references |
| `test.py` | **New** expected answer / evaluation test |
| `solution.md` | **New** step-by-step solution (**create this file**) |
| `Dockerfile` | Container setup (copy or adapt from the original) |
| `docker-compose.yaml` | Docker config (copy or adapt from the original) |
| Other files | Any additional assets needed by the new variant |

### 3.3 Encryption

Type 2 tasks require **two encryption steps**:

**Step 1 — Encrypt `task.yaml` and `test.py`:**

```bash
# Run from the project root (not contrib/)
python encrypt.py
```

**Step 2 — Encrypt `solution.md`:**

```bash
cd contrib/
python encrypt_tasks.py --solution
```

> This second step encrypts only the standalone `solution.md` file (producing `solution.md.enc`) without touching other files.

---

## 4. Reference Solutions

When creating scaled variants, you should always refer to the original task's solution to understand the expected methodology and answer format.

- **Type 1 tasks:** See the decrypted `solution.md` inside each task folder.
- **Type 2 tasks:** See the [Human Solutions spreadsheet](https://docs.google.com/spreadsheets/d/1129wZohEqQ-WhF6HLc2W0B1gKRdWNkqZNUUT_oQY2ps/edit?gid=0#gid=0) (column: *human solution*).
