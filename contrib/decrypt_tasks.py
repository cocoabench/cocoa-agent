#!/usr/bin/env python3
"""
Decrypt task files for local viewing/editing.

Usage:
    python decrypt_tasks.py --task my-task     # Decrypt a specific task
    python decrypt_tasks.py                    # Decrypt all tasks in cocoabench-head/
    python decrypt_tasks.py --solution        # Only decrypt solution.md.enc in each task

By default this will decrypt:
- instruction.md.enc -> instruction.md
- evaluation.md.enc -> evaluation.md
- metadata.json.enc -> metadata.json
- solution.md.enc -> solution.md

With --solution, only solution.md.enc is decrypted (no requirement for other files).
Note: Original .enc files will be removed after decryption.
"""

import argparse
import base64
import hashlib
from pathlib import Path

# Get paths relative to this script
script_dir = Path(__file__).parent
project_root = script_dir.parent
tasks_dir = project_root / "cocoabench-head"


def derive_key(password: str, length: int) -> bytes:
    """Derive a fixed-length key from the password using SHA256."""
    hasher = hashlib.sha256()
    hasher.update(password.encode())
    key = hasher.digest()
    return key * (length // len(key)) + key[: length % len(key)]


def decrypt(ciphertext_b64: str, password: str) -> str:
    """Decrypt base64-encoded ciphertext with XOR."""
    encrypted = base64.b64decode(ciphertext_b64)
    key = derive_key(password, len(encrypted))
    decrypted = bytes(a ^ b for a, b in zip(encrypted, key))
    return decrypted.decode('utf-8')


def decrypt_file(enc_path: Path, canary: str) -> bool:
    """Decrypt a single .enc file to its original form and remove the encrypted file.
    
    Returns True if decrypted, False if file doesn't exist.
    """
    if not enc_path.exists():
        return False
    
    content = enc_path.read_text().strip()
    decrypted = decrypt(content, canary)
    
    # Remove .enc extension to get original filename
    original_path = enc_path.parent / enc_path.stem
    original_path.write_text(decrypted, encoding='utf-8')
    enc_path.unlink()
    
    return True


def decrypt_task(task_dir: Path, solution_only: bool = False) -> bool:
    """Decrypt task files in place.
    
    If solution_only is True, only decrypt solution.md.enc (no requirement for other files).
    Otherwise decrypt instruction, evaluation, metadata, and solution.
    """
    task_name = task_dir.name
    canary_file = task_dir / "canary.txt"

    if not canary_file.exists():
        print(f"⚠ canary.txt not found, skipping task {task_name}")
        return False

    canary = canary_file.read_text(encoding="utf-8").strip()

    if solution_only:
        # Only decrypt solution.md.enc
        solution_enc = task_dir / "solution.md.enc"
        if not solution_enc.exists():
            return False
        print(f"✓ Decrypting solution: {task_name}")
        decrypt_file(solution_enc, canary)
        print(f"  - solution.md.enc -> solution.md")
        return True

    # Default: require instruction + evaluation, decrypt all
    instruction_enc = task_dir / "instruction.md.enc"
    evaluation_enc = task_dir / "evaluation.md.enc"
    if not instruction_enc.exists():
        print(f"⚠ instruction.md.enc not found, skipping task {task_name}")
        return False
    if not evaluation_enc.exists():
        print(f"⚠ evaluation.md.enc not found, skipping task {task_name}")
        return False

    print(f"✓ Decrypting task: {task_name}")
    decrypt_file(instruction_enc, canary)
    print(f"  - instruction.md.enc -> instruction.md")
    decrypt_file(evaluation_enc, canary)
    print(f"  - evaluation.md.enc -> evaluation.md")
    metadata_enc = task_dir / "metadata.json.enc"
    if decrypt_file(metadata_enc, canary):
        print(f"  - metadata.json.enc -> metadata.json")
    solution_enc = task_dir / "solution.md.enc"
    if decrypt_file(solution_enc, canary):
        print(f"  - solution.md.enc -> solution.md")
    return True


def main():
    parser = argparse.ArgumentParser(
        description="Decrypt task files for local viewing/editing"
    )
    parser.add_argument(
        "--task",
        type=str,
        help="Name of a specific task to decrypt (optional, decrypts all if not specified)"
    )
    parser.add_argument(
        "--solution",
        action="store_true",
        help="Only decrypt solution.md.enc in each task (ignore other files)"
    )

    args = parser.parse_args()
    
    if not tasks_dir.exists():
        print(f"❌ Error: Tasks directory '{tasks_dir}' does not exist")
        return
    
    print(f"🔓 Decrypting tasks in: {tasks_dir}")
    print("=" * 60)
    
    # Process specific task or all tasks
    success_count = 0
    
    if args.task:
        # Decrypt specific task
        task_path = tasks_dir / args.task
        if not task_path.exists():
            print(f"❌ Error: Task '{args.task}' not found in {tasks_dir}")
            return
        if decrypt_task(task_path, solution_only=args.solution):
            success_count += 1
    else:
        # Decrypt all tasks
        for task_path in sorted(tasks_dir.iterdir()):
            if task_path.is_dir():
                if decrypt_task(task_path, solution_only=args.solution):
                    success_count += 1
                print()
    
    print("=" * 60)
    print(f"✅ Successfully decrypted {success_count} task(s)")
    print(f"📁 Encrypted .enc files have been removed")


if __name__ == "__main__":
    main()

