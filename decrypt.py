#!/usr/bin/env python3
"""
Utility functions for decryption of encrypted task files.

This module provides functions to decrypt task.yaml.enc and test.py.enc
files either into memory or to disk.

Usage:
    python decrypt.py                           # Decrypt all tasks in cocoa-bench-v0.1/
    python decrypt.py --task my-task            # Decrypt a specific task
    python decrypt.py --tasks-dir my-tasks/     # Decrypt all tasks in directory
"""

import argparse
import base64
import hashlib
from pathlib import Path
from typing import Optional


def derive_key(password: str, length: int) -> bytes:
    """Derive a fixed-length key from the password using SHA256."""
    hasher = hashlib.sha256()
    hasher.update(password.encode())
    key = hasher.digest()
    return key * (length // len(key)) + key[: length % len(key)]


def decrypt(ciphertext_b64: str, password: str) -> str:
    """Decrypt base64-encoded ciphertext with XOR.
    
    Args:
        ciphertext_b64: Base64-encoded encrypted content
        password: Password/canary for decryption
        
    Returns:
        Decrypted plaintext string
        
    Raises:
        ValueError: If decryption fails (invalid base64, decode error, etc.)
    """
    try:
        encrypted = base64.b64decode(ciphertext_b64)
    except Exception as e:
        raise ValueError(f"Failed to decode base64: {str(e)}")
    
    key = derive_key(password, len(encrypted))
    decrypted = bytes(a ^ b for a, b in zip(encrypted, key))
    
    try:
        return decrypted.decode('utf-8')
    except UnicodeDecodeError as e:
        raise ValueError(f"Failed to decode decrypted content as UTF-8: {str(e)}")


def decrypt_file_to_memory(encrypted_file_path: Path, canary: str) -> str:
    """Decrypt an encrypted file directly to memory without writing to disk.
    
    Args:
        encrypted_file_path: Path to the .enc file
        canary: Decryption key (canary)
        
    Returns:
        Decrypted content as string
        
    Raises:
        FileNotFoundError: If the encrypted file doesn't exist
        ValueError: If decryption fails
    """
    if not encrypted_file_path.exists():
        raise FileNotFoundError(f"Encrypted file not found: {encrypted_file_path}")
    
    try:
        with open(encrypted_file_path, 'r', encoding='utf-8') as f:
            encrypted_content = f.read().strip()
    except IOError as e:
        raise ValueError(f"Failed to read encrypted file {encrypted_file_path}: {str(e)}")
    
    if not encrypted_content:
        raise ValueError(f"Encrypted file {encrypted_file_path} is empty")
    
    try:
        decrypted_content = decrypt(encrypted_content, canary)
        return decrypted_content
    except ValueError as e:
        raise ValueError(f"Failed to decrypt {encrypted_file_path}: {str(e)}")


def read_canary(task_dir: Path) -> Optional[str]:
    """Read canary from canary.txt file.
    
    Args:
        task_dir: Path to task directory
        
    Returns:
        Canary string, or None if file doesn't exist
        
    Raises:
        ValueError: If canary file exists but cannot be read or is empty
    """
    canary_file = task_dir / "canary.txt"
    if not canary_file.exists():
        return None
    
    try:
        with open(canary_file, 'r', encoding='utf-8') as f:
            canary = f.read().strip()
        
        if not canary:
            raise ValueError(f"Canary file {canary_file} is empty")
        
        return canary
    except IOError as e:
        raise ValueError(f"Failed to read canary file {canary_file}: {str(e)}")


def decrypt_file_to_disk(enc_path: Path, canary: str) -> bool:
    """Decrypt a .enc file and write to disk (removing .enc extension).
    
    Args:
        enc_path: Path to the encrypted file
        canary: Decryption key
        
    Returns:
        True if decrypted successfully, False if file doesn't exist
    """
    if not enc_path.exists():
        return False
    
    content = enc_path.read_text().strip()
    decrypted = decrypt(content, canary)
    
    original_path = enc_path.parent / enc_path.stem
    original_path.write_text(decrypted, encoding='utf-8')
    
    # Delete the encrypted file after successful decryption
    enc_path.unlink()
    
    return True


def decrypt_task(task_dir: Path) -> bool:
    """Decrypt all task files in a task directory.
    
    Args:
        task_dir: Path to task directory containing canary.txt and .enc files
        
    Returns:
        True if decryption succeeded, False otherwise
    """
    task_name = task_dir.name
    canary_file = task_dir / "canary.txt"
    
    if not canary_file.exists():
        print(f"⚠ canary.txt not found, skipping task {task_name}")
        return False
    
    if (task_dir / "task.yaml").exists() and (task_dir / "test.py").exists():
        print(f"⚠ Task {task_name} appears to be already decrypted, skipping")
        return False
    
    task_enc = task_dir / "task.yaml.enc"
    test_enc = task_dir / "test.py.enc"
    
    if not task_enc.exists():
        print(f"⚠ task.yaml.enc not found, skipping task {task_name}")
        return False
    
    if not test_enc.exists():
        print(f"⚠ test.py.enc not found, skipping task {task_name}")
        return False
    
    canary = canary_file.read_text().strip()
    
    print(f"✓ Decrypting task: {task_name}")
    
    decrypt_file_to_disk(task_enc, canary)
    print(f"  - task.yaml.enc -> task.yaml")
    
    decrypt_file_to_disk(test_enc, canary)
    print(f"  - test.py.enc -> test.py")
    
    return True


def main():
    parser = argparse.ArgumentParser(
        description="Decrypt CocoaBench task files for local use"
    )
    parser.add_argument(
        "--task",
        type=str,
        help="Name of a specific task to decrypt (must be in --tasks-dir)"
    )
    parser.add_argument(
        "--tasks-dir",
        type=str,
        default="cocoa-bench-v0.1",
        help="Directory containing task subdirectories (default: cocoa-bench-v0.1/)"
    )
    
    args = parser.parse_args()
    tasks_dir = Path(args.tasks_dir)
    
    if not tasks_dir.exists():
        print(f"❌ Error: Tasks directory '{tasks_dir}' does not exist")
        print(f"\n💡 Tip: Download the dataset first:")
        print(f"   curl -LO https://cocoabench.github.io/assets/data/cocoa-bench-v0.1.zip")
        print(f"   unzip cocoa-bench-v0.1.zip")
        return
    
    print(f"🔓 Decrypting tasks in: {tasks_dir}")
    print("=" * 60)
    
    success_count = 0
    
    if args.task:
        task_path = tasks_dir / args.task
        if not task_path.exists():
            print(f"❌ Error: Task '{args.task}' not found in {tasks_dir}")
            return
        if decrypt_task(task_path):
            success_count += 1
    else:
        for task_path in sorted(tasks_dir.iterdir()):
            if task_path.is_dir() and not task_path.name.startswith('.'):
                if decrypt_task(task_path):
                    success_count += 1
                print()
    
    print("=" * 60)
    print(f"✅ Successfully decrypted {success_count} task(s)")
    print(f"📝 Original .enc files are kept for reference")


if __name__ == "__main__":
    main()

