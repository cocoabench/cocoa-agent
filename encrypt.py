#!/usr/bin/env python3
"""
Encrypt task.yaml and test.py files in place for all tasks in a directory.

Usage:
    python encrypt.py --tasks-dir releasing-tasks/
    
This will:
- Encrypt task.yaml -> task.yaml.enc (and remove task.yaml)
- Encrypt test.py -> test.py.enc (and remove test.py)
- Create canary.txt with the encryption key
- Keep all other files (assets/, Dockerfile, docker-compose.yaml, etc.) unchanged
"""

import argparse
import base64
import hashlib
import os
from pathlib import Path


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


def encrypt_task(task_dir: Path) -> bool:
    """Encrypt task.yaml and test.py in place."""
    task_name = task_dir.name
    task_yaml_path = task_dir / "task.yaml"
    test_py_path = task_dir / "test.py"
    
    # Check if files are already encrypted
    if (task_dir / "task.yaml.enc").exists() or (task_dir / "test.py.enc").exists():
        print(f"⚠ Task {task_name} appears to be already encrypted, skipping")
        return False
    
    # Check if required files exist
    if not task_yaml_path.exists():
        print(f"⚠ {task_yaml_path} not found, skipping task {task_name}")
        return False
    
    if not test_py_path.exists():
        print(f"⚠ {test_py_path} not found, skipping task {task_name}")
        return False
    
    # Read file contents
    with open(task_yaml_path, 'r', encoding='utf-8') as f:
        task_yaml_content = f.read()
    
    with open(test_py_path, 'r', encoding='utf-8') as f:
        test_py_content = f.read()
    
    # Generate canary for this task
    canary = generate_canary(task_name)
    
    # Encrypt both files
    encrypted_task = encrypt(task_yaml_content, canary)
    encrypted_test = encrypt(test_py_content, canary)
    
    # Write encrypted files
    with open(task_dir / "task.yaml.enc", 'w') as f:
        f.write(encrypted_task)
    
    with open(task_dir / "test.py.enc", 'w') as f:
        f.write(encrypted_test)
    
    # Write canary
    with open(task_dir / "canary.txt", 'w') as f:
        f.write(canary)
    
    # Remove original files
    task_yaml_path.unlink()
    test_py_path.unlink()
    
    print(f"✓ Encrypted task: {task_name}")
    print(f"  - task.yaml -> task.yaml.enc")
    print(f"  - test.py -> test.py.enc")
    print(f"  - Created canary.txt")
    
    return True


def main():
    parser = argparse.ArgumentParser(
        description="Encrypt task.yaml and test.py files in place"
    )
    parser.add_argument(
        "--tasks-dir",
        type=str,
        default="cocoabench-head",
        help="Path to the tasks directory containing task subdirectories"
    )
    
    args = parser.parse_args()
    
    tasks_dir = Path(args.tasks_dir)
    
    if not tasks_dir.exists():
        print(f"❌ Error: Tasks directory '{tasks_dir}' does not exist")
        return
    
    print(f"🔐 Encrypting tasks in: {tasks_dir}")
    print("=" * 60)
    
    # Process each task subdirectory
    success_count = 0
    for task_path in sorted(tasks_dir.iterdir()):
        if task_path.is_dir():
            if encrypt_task(task_path):
                success_count += 1
            print()
    
    print("=" * 60)
    print(f"✅ Successfully encrypted {success_count} tasks")
    print(f"📁 Original task.yaml and test.py files have been removed")
    print(f"📤 You can now upload to GitHub safely")


if __name__ == "__main__":
    main()