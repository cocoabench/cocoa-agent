# 🔌 Sandbox API for Host-Side Scripts

Sometimes the agent's output and conversation history alone aren't enough to evaluate a task. For tasks where the agent creates files or modifies the environment, you can call Sandbox APIs from `test.py` to inspect container state.

## 🛠️ Connecting to the Sandbox

The sandbox client allows you to interact with the Docker container where the agent ran.

```python
from pathlib import Path
import sys

# 1. Locate and import the Sandbox SDK
sandbox_sdk_path = Path(__file__).parent.parent / "sandbox" / "sdk" / "python"
if sandbox_sdk_path.exists():
    sys.path.insert(0, str(sandbox_sdk_path))
    from agent_sandbox import Sandbox

# 2. Initialize the client
# The port is available in result["sandbox"]["docker_port"]
docker_port = result.get("sandbox", {}).get("docker_port", 8080)
sandbox = Sandbox(base_url=f"http://localhost:{docker_port}")

# 3. Use the client
# Read a file
content = sandbox.file.read_file(file="/home/gem/output.txt").data.content
print(f"File content: {content}")
```

---

## 📂 Common File APIs

Use these APIs to inspect the filesystem state inside the container.

| Capability | API Call | Return Value | File Types |
|------------|----------|--------------|------------|
| **Read file** | `sandbox.file.read_file(file=path)` | `.data.content` (str) | Text files (`.txt`, `.md`, `.py`) |
| **List directory** | `sandbox.file.list_path(path=dir)` | `.data.entries` (list) | Directories |
| **Download file** | `sandbox.file.download_file(path=path)` | Binary Stream | Binary files (`.png`, `.pdf`, `.zip`) |

### Usage Examples

#### Reading Text Files

> [!NOTE]
> Use this for configuration files, code, logs, or any text-based output.

```python
# Returns the full string content of the file
response = sandbox.file.read_file(file="/home/gem/solution.py")
code_content = response.data.content
```

#### Listing Directory Contents

> [!TIP]
> Useful for checking if expected files were created.

```python
# Returns a list of file entries
response = sandbox.file.list_path(path="/home/gem")
files = [entry.name for entry in response.data.entries]

if "output.json" in files:
    print("Found output file!")
```

#### Downloading Binary Files

> [!WARNING]
> Do not use `read_file` for images or PDFs. It will try to decode them as UTF-8 and fail.

```python
# Returns binary data stream
binary_data = sandbox.file.download_file(path="/home/gem/plot.png")

# Save locally to inspect
with open("local_plot.png", "wb") as f:
    f.write(binary_data)
```
