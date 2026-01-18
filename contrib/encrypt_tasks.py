#!/usr/bin/env python3
"""
Encrypt task files for safe contribution.

Usage:
    python encrypt_tasks.py                    # Encrypt all tasks in cocoabench-head/
    python encrypt_tasks.py --task my-task     # Encrypt a specific task
    
This will encrypt:
- instruction.md -> instruction.md.enc
- evaluation.md -> evaluation.md.enc
- metadata.json -> metadata.json.enc
- solution.md -> solution.md.enc
- Create canary.txt with the encryption key
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


def encrypt(plaintext: str, password: str) -> str:
    """Encrypt plaintext with XOR and return base64-encoded ciphertext."""
    plaintext_bytes = plaintext.encode()
    key = derive_key(password, len(plaintext_bytes))
    encrypted = bytes(a ^ b for a, b in zip(plaintext_bytes, key))
    return base64.b64encode(encrypted).decode()


def generate_canary(task_name: str) -> str:
    """Generate a unique canary for each task based on task name."""
    hasher = hashlib.sha256()
    hasher.update(task_name.encode())
    return hasher.hexdigest()[:16]  # Use first 16 chars as canary


def encrypt_file(file_path: Path, canary: str) -> bool:
    """Encrypt a single file and remove the original.
    
    Returns True if encrypted, False if file doesn't exist.
    """
    if not file_path.exists():
        return False
    
    content = file_path.read_text(encoding='utf-8')
    encrypted = encrypt(content, canary)
    
    enc_path = file_path.parent / f"{file_path.name}.enc"
    enc_path.write_text(encrypted)
    file_path.unlink()
    
    return True


def encrypt_task(task_dir: Path) -> bool:
    """Encrypt task files in place."""
    task_name = task_dir.name
    
    # Check required files exist
    instruction_path = task_dir / "instruction.md"
    evaluation_path = task_dir / "evaluation.md"
    
    if not instruction_path.exists():
        print(f"⚠ instruction.md not found, skipping task {task_name}")
        return False
    
    if not evaluation_path.exists():
        print(f"⚠ evaluation.md not found, skipping task {task_name}")
        return False
    
    # Generate canary for this task
    canary = generate_canary(task_name)
    
    print(f"✓ Encrypting task: {task_name}")
    
    # Encrypt required files
    encrypt_file(instruction_path, canary)
    print(f"  - instruction.md -> instruction.md.enc")
    
    encrypt_file(evaluation_path, canary)
    print(f"  - evaluation.md -> evaluation.md.enc")
    
    # Encrypt optional files
    metadata_path = task_dir / "metadata.json"
    if encrypt_file(metadata_path, canary):
        print(f"  - metadata.json -> metadata.json.enc")
    
    solution_path = task_dir / "solution.md"
    if encrypt_file(solution_path, canary):
        print(f"  - solution.md -> solution.md.enc")
    
    # Write canary
    (task_dir / "canary.txt").write_text(canary)
    print(f"  - Created canary.txt")
    
    return True


def main():
    parser = argparse.ArgumentParser(
        description="Encrypt task files for safe contribution"
    )
    parser.add_argument(
        "--task",
        type=str,
        help="Name of a specific task to encrypt (optional, encrypts all if not specified)"
    )
    
    args = parser.parse_args()
    
    if not tasks_dir.exists():
        print(f"❌ Error: Tasks directory '{tasks_dir}' does not exist")
        print(f"   Run 'python create_task.py' first to create a task.")
        return
    
    print(f"🔐 Encrypting tasks in: {tasks_dir}")
    print("=" * 60)
    
    # Process specific task or all tasks
    success_count = 0
    
    if args.task:
        # Encrypt specific task
        task_path = tasks_dir / args.task
        if not task_path.exists():
            print(f"❌ Error: Task '{args.task}' not found in {tasks_dir}")
            return
        if encrypt_task(task_path):
            success_count += 1
    else:
        # Encrypt all tasks
        for task_path in sorted(tasks_dir.iterdir()):
            if task_path.is_dir():
                if encrypt_task(task_path):
                    success_count += 1
                print()
    
    print("=" * 60)
    print(f"✅ Successfully encrypted {success_count} task(s)")
    print(f"📁 Original files have been removed")
    print(f"📤 You can now submit your Pull Request!")


if __name__ == "__main__":
    main()
