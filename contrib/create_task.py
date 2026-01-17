#!/usr/bin/env python3
"""
Task Wizard - Interactive tool to create new benchmark tasks.

Usage:
    cd contrib
    python create_task.py

The wizard will guide you through creating all required files for a new task.
Inspired by Terminal-Bench's task creation workflow.
Reference: https://cocoabench.github.io/
"""

import json
import os
import re
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple


# ANSI colors for terminal output
class Colors:
    HEADER = '\033[95m'
    BLUE = '\033[94m'
    CYAN = '\033[96m'
    GREEN = '\033[92m'
    YELLOW = '\033[93m'
    RED = '\033[91m'
    BOLD = '\033[1m'
    UNDERLINE = '\033[4m'
    END = '\033[0m'


def print_header(text: str):
    """Print a styled header."""
    print(f"\n{Colors.BOLD}{Colors.CYAN}{'=' * 60}{Colors.END}")
    print(f"{Colors.BOLD}{Colors.CYAN}{text:^60}{Colors.END}")
    print(f"{Colors.BOLD}{Colors.CYAN}{'=' * 60}{Colors.END}\n")


def print_step(step: int, total: int, text: str):
    """Print a step indicator."""
    print(f"\n{Colors.BOLD}{Colors.BLUE}[Step {step}/{total}] {text}{Colors.END}")


def print_success(text: str):
    """Print a success message."""
    print(f"{Colors.GREEN}✓ {text}{Colors.END}")


def print_warning(text: str):
    """Print a warning message."""
    print(f"{Colors.YELLOW}⚠ {text}{Colors.END}")


def print_error(text: str):
    """Print an error message."""
    print(f"{Colors.RED}✗ {text}{Colors.END}")


def print_info(text: str):
    """Print an info message."""
    print(f"{Colors.CYAN}ℹ {text}{Colors.END}")


def get_input(prompt: str, default: str = "", required: bool = True) -> str:
    """Get user input with optional default value."""
    if default:
        full_prompt = f"{prompt} [{default}]: "
    else:
        full_prompt = f"{prompt}: "
    
    while True:
        value = input(full_prompt).strip()
        if not value and default:
            return default
        if not value and required:
            print_error("This field is required. Please enter a value.")
            continue
        return value


def get_multiline_input(prompt: str, hint: str = "") -> str:
    """Get multi-line input from user. Type --- on a line by itself to finish."""
    print(f"{prompt}")
    if hint:
        print(f"{Colors.CYAN}{hint}{Colors.END}")
    print(f"{Colors.CYAN}(Type --- on a new line when done){Colors.END}")
    lines = []
    while True:
        line = input()
        if line.strip() == "---":
            break
        lines.append(line)
    # Remove trailing empty lines
    while lines and lines[-1].strip() == "":
        lines.pop()
    return '\n'.join(lines)


def get_yes_no(prompt: str, default: bool = True) -> bool:
    """Get a yes/no response."""
    default_str = "Y/n" if default else "y/N"
    while True:
        response = input(f"{prompt} [{default_str}]: ").strip().lower()
        if not response:
            return default
        if response in ('y', 'yes'):
            return True
        if response in ('n', 'no'):
            return False
        print_error("Please enter 'y' or 'n'")


def get_choice(prompt: str, options: List[str], allow_multiple: bool = False) -> List[str]:
    """Get a choice from a list of options."""
    print(f"\n{prompt}")
    for i, option in enumerate(options, 1):
        print(f"  {i}. {option}")
    
    if allow_multiple:
        print(f"\n{Colors.CYAN}Enter numbers separated by commas (e.g., 1,3,5){Colors.END}")
    
    while True:
        response = input("Your choice: ").strip()
        try:
            if allow_multiple:
                indices = [int(x.strip()) for x in response.split(',')]
            else:
                indices = [int(response)]
            
            selected = []
            for idx in indices:
                if 1 <= idx <= len(options):
                    selected.append(options[idx - 1])
                else:
                    raise ValueError(f"Invalid option: {idx}")
            return selected
        except (ValueError, IndexError):
            print_error(f"Please enter valid number(s) between 1 and {len(options)}")


def validate_task_id(task_id: str) -> Tuple[bool, str]:
    """Validate task ID format."""
    if not task_id:
        return False, "Task ID cannot be empty"
    if not re.match(r'^[a-z0-9-]+$', task_id):
        return False, "Task ID must contain only lowercase letters, numbers, and hyphens"
    if task_id.startswith('-') or task_id.endswith('-'):
        return False, "Task ID cannot start or end with a hyphen"
    if '--' in task_id:
        return False, "Task ID cannot contain consecutive hyphens"
    return True, ""


def get_next_task_number(tasks_dir: Path) -> int:
    """Get the next available task number."""
    max_id = 0
    if not tasks_dir.exists():
        return 1
    for task_folder in tasks_dir.iterdir():
        if task_folder.is_dir():
            metadata_file = task_folder / 'metadata.json'
            if metadata_file.exists():
                try:
                    with open(metadata_file) as f:
                        metadata = json.load(f)
                        task_id = metadata.get('id', 0)
                        if isinstance(task_id, int) and task_id > max_id:
                            max_id = task_id
                except (json.JSONDecodeError, IOError):
                    pass
    return max_id + 1


def create_instruction_md(task_data: Dict) -> str:
    """Generate instruction.md content."""
    # Always start with **Task:** header to pass validation
    content = "**Task:**\n\n" + task_data['description']
    
    # Only add requirements if there are any
    if task_data.get('requirements'):
        content += "\n\n**Requirements:**\n"
        for req in task_data['requirements']:
            content += f"- {req}\n"
    
    content += f"""
    
**Output Format:**

Submit your answer in the following format:

```
<answer>{task_data['answer_format']}</answer>
```
"""
    return content


def create_evaluation_md(task_data: Dict) -> str:
    """Generate evaluation.md content."""
    agent_output = task_data.get('agent_output', '[Agent name]: [result], ([Correct/Incorrect], [time])\nChat transcript: [link to chat]')
    content = f"""# Evaluation for Task {task_data['id']}

## Initialization

{task_data['initialization']}

## Evaluation Criteria

{task_data['expected_answer']}

## Agent Output Example

{agent_output}
"""
    return content


def create_solution_md(task_data: Dict) -> str:
    """Generate solution.md content."""
    content = """# Solution

"""
    for i, step in enumerate(task_data['solution_steps'], 1):
        content += f"""### Step {i}: {step['title']}
{step['content']}

"""
    
    content += f"""### Final Answer
{task_data['final_answer']}
"""
    return content


def create_metadata_json(task_data: Dict) -> Dict:
    """Generate metadata.json content."""
    return {
        "id": task_data['id'],
        "name": task_data['name'],
        "brainstorm_by": task_data['author'],
        "stage": "Brainstorm",
        "self_checked": "no",
        "reviewers": {},
        "task_properties": {},
        "human_performance": {}
    }


def run_wizard():
    """Run the interactive task creation wizard."""
    print_header("CocoaBench - Task Wizard")
    
    print(f"""Welcome! This wizard helps you create a benchmark task in a few simple steps.

{Colors.BOLD}What makes a good task?{Colors.END}
{Colors.GREEN}✓{Colors.END} Multi-step tasks requiring various skills
{Colors.GREEN}✓{Colors.END} Clear answers with unique format (evaluated via exact match)
{Colors.GREEN}✓{Colors.END} Realistic challenges based on real-world problems
{Colors.GREEN}✓{Colors.END} Tasks that test web browsing, visual perception, coding, or reasoning

{Colors.BOLD}What to avoid:{Colors.END}
{Colors.RED}✗{Colors.END} Answers with multiple valid representations (e.g., "1000" vs "1,000")
{Colors.RED}✗{Colors.END} Tasks with subjective or opinion-based answers
{Colors.RED}✗{Colors.END} Time-sensitive data that will become stale
{Colors.RED}✗{Colors.END} Trivial single-step tasks
{Colors.RED}✗{Colors.END} Tasks requiring real-time API access that may change

Reference: https://cocoabench.github.io/#examples
""")
    
    if not get_yes_no("Ready to start?"):
        print("\nNo problem! Run again when ready.")
        return
    
    # Determine paths
    script_dir = Path(__file__).parent.resolve()
    project_root = script_dir.parent
    tasks_dir = project_root / 'cocoabench-head'
    
    task_data = {}
    total_steps = 7
    
    # =====================
    # Step 1: Basic Info
    # =====================
    print_step(1, total_steps, "Basic Info")
    print(f"""
{Colors.CYAN}Let's start with the basics.{Colors.END}
""")
    
    next_id = get_next_task_number(tasks_dir)
    
    while True:
        task_name = get_input("Task name (e.g., 'find-paper-citations', 'solve-puzzle')")
        valid, error = validate_task_id(task_name)
        if valid:
            task_folder = tasks_dir / task_name
            if task_folder.exists():
                print_error(f"Task '{task_name}' already exists. Try another name.")
                continue
            break
        print_error(error)
    
    task_data['id'] = next_id
    task_data['name'] = task_name
    task_data['author'] = get_input("Your name (for attribution)")
    
    print_success(f"Creating task: {task_name}")
    
    # =====================
    # Step 2: Task Instruction
    # =====================
    print_step(2, total_steps, "Task Instruction")
    print(f"""
{Colors.CYAN}Write the instruction that will be sent to the AI agent.
Be specific about what the agent should do and what context it needs.{Colors.END}

Example:
  "You are given a CSV file with sales data. Find the month with 
   the highest total revenue and identify the top-selling product."
""")
    
    task_data['description'] = get_multiline_input(
        "Task instruction:",
        "Describe the task clearly. What should the agent do?"
    )
    
    # =====================
    # Step 3: Expected Answer
    # =====================
    print_step(3, total_steps, "Expected Answer")
    print(f"""
{Colors.CYAN}What is the correct answer? This is used for automatic evaluation.{Colors.END}

{Colors.YELLOW} Exact Match:{Colors.END} Answers are evaluated using exact string match.
Make sure your answer has ONE unique representation (specify format in instruction).

Examples:
  • "42"
  • "Paris, France"  
  • "John Smith, 1985"
""")
    
    task_data['expected_answer'] = get_input("Expected answer (exact string to match)")
    task_data['final_answer'] = task_data['expected_answer']
    
    # Answer format
    print(f"""
{Colors.CYAN}Describe the format so the agent produces the exact answer above if correct.{Colors.END}
{Colors.YELLOW}Tip: Be as specific as possible (e.g., "integer without commas", "YYYY-MM-DD", "2 decimal places"){Colors.END}
""")
    format_example = get_input("Answer format description", "your_answer")
    task_data['answer_format'] = format_example
    
    # Simplified - no separate requirements/task_detail needed
    task_data['requirements'] = []
    task_data['task_detail'] = ""
    
    # =====================
    # Step 4: Solution (How to solve it)
    # =====================
    print_step(4, total_steps, "Solution")
    print(f"""
{Colors.CYAN}Briefly describe how to solve this task. 
This helps us verify the task is solvable and document the approach.{Colors.END}
""")
    
    solution_text = get_multiline_input(
        "How would you solve this task?",
        "Describe the key steps (doesn't need to be super detailed)"
    )
    
    # Convert to solution steps format
    task_data['solution_steps'] = [{'title': 'Solution', 'content': solution_text}]
    
    # =====================
    # Step 5: Resources
    # =====================
    print_step(5, total_steps, "Resources")
    print(f"""
{Colors.CYAN}Does this task need any files or resources?{Colors.END}
""")
    
    init_types = [
        "No - agent only needs web access",
        "Yes - I have files to include (images, data, etc.)",
        "Yes - agent needs to access a specific website/UI"
    ]
    init_choice = get_choice("What does the agent need?", init_types)[0]
    
    task_data['downloaded_assets'] = []
    
    if init_choice == "No - agent only needs web access":
        task_data['initialization'] = "None (web browsing only)"
    
    elif init_choice == "Yes - I have files to include (images, data, etc.)":
        print(f"""
{Colors.CYAN}Enter the URLs of the files/resources needed for this task.
The URLs will be saved to assets/urls.txt{Colors.END}
""")
        
        asset_urls = []
        while True:
            url = get_input("URL (or Enter to finish)", "", required=False)
            if not url:
                if len(asset_urls) == 0:
                    print_error("Please add at least one URL.")
                    continue
                break
            
            asset_urls.append(url)
            print_success(f"Added URL #{len(asset_urls)}")
        
        task_data['asset_urls'] = asset_urls
        task_data['initialization'] = "Local: assets/"
    
    else:  # Website/UI
        print(f"""
{Colors.CYAN}Enter the URL the agent should access.{Colors.END}
""")
        url = get_input("Website/UI URL")
        task_data['initialization'] = f"Host UI: {url}"
    
    # =====================
    # Step 6: Agent Testing
    # =====================
    print_step(6, total_steps, "Test Difficulty with an AI Agent")
    print(f"""
{Colors.CYAN}Have you tested this task with an AI agent?{Colors.END}

{Colors.YELLOW}Goal: At least one agent should fail to solve your task correctly.{Colors.END}
This is what makes a benchmark task valuable! If all agents succeed easily,
consider making it more challenging.

Recommended agents: Gemini 3 Pro, ChatGPT Agent, Claude 4.5
Please include the chat transcript link when you test.
""")
    
    has_tested = get_yes_no("Have you already tested with an agent?", default=False)
    
    if has_tested:
        agent_name = get_input("Agent name (e.g., 'ChatGPT Agent')")
        agent_result = get_input("Agent result")
        is_correct = get_yes_no("Did the agent get the correct answer?", default=False)
        time_taken = get_input("Time taken (e.g., '5min')", required=False) or "N/A"
        chat_link = get_input("Chat transcript link")
        
        correctness = "Correct" if is_correct else "Incorrect"
        task_data['agent_output'] = f"{agent_name}: {agent_result}, ({correctness}, {time_taken})\nChat transcript: {chat_link}"
        print_success("Agent test results recorded!")
    else:
        task_data['agent_output'] = "[Agent name]: [result], ([Correct/Incorrect], [time])\nChat transcript: [link to chat]"
        print_warning("Remember to test with an agent before submitting!")
        print_info("You can edit evaluation.md later to add test results.")
    
    # =====================
    # Step 7: Review & Create
    # =====================
    print_step(7, total_steps, "Review & Create")
    print(f"""
{Colors.CYAN}Here's a summary of your task:{Colors.END}

  Name: {task_name}
  Author: {task_data['author']}
  Expected Answer: {task_data['expected_answer']}
  Resources: {task_data['initialization']}
""")
    
    if not get_yes_no("Create this task?"):
        print("\nTask creation cancelled.")
        return
    
    # Create files
    print_header("Creating Task Files")
    
    task_folder = tasks_dir / task_name
    task_folder.mkdir(parents=True, exist_ok=True)
    
    files_created = []
    
    # instruction.md
    instruction_content = create_instruction_md(task_data)
    (task_folder / 'instruction.md').write_text(instruction_content)
    files_created.append('instruction.md')
    print_success("Created instruction.md")
    
    # evaluation.md
    evaluation_content = create_evaluation_md(task_data)
    (task_folder / 'evaluation.md').write_text(evaluation_content)
    files_created.append('evaluation.md')
    print_success("Created evaluation.md")
    
    # solution.md
    solution_content = create_solution_md(task_data)
    (task_folder / 'solution.md').write_text(solution_content)
    files_created.append('solution.md')
    print_success("Created solution.md")
    
    # metadata.json
    metadata = create_metadata_json(task_data)
    with open(task_folder / 'metadata.json', 'w') as f:
        json.dump(metadata, f, indent=2)
    files_created.append('metadata.json')
    print_success("Created metadata.json")
    
    # Save asset URLs if specified
    if task_data.get('asset_urls'):
        assets_folder = task_folder / 'assets'
        assets_folder.mkdir(exist_ok=True)
        
        # Write URLs to file
        urls_file = assets_folder / 'urls.txt'
        urls_file.write_text('\n'.join(task_data['asset_urls']))
        files_created.append('assets/urls.txt')
        print_success("Created assets/urls.txt")
    
    # Summary
    print_header("Task Created Successfully!")
    
    print(f"""
{Colors.BOLD}Task Location:{Colors.END} {task_folder}

{Colors.BOLD}Files Created:{Colors.END}
""")
    for f in files_created:
        print(f"  • {f}")
    
    # Show different next steps based on whether agent testing is done
    if task_data.get('agent_output', '').startswith('[Agent name]'):
        # Not tested yet
        print(f"""
{Colors.BOLD}What's next?{Colors.END}

1. {Colors.CYAN}Review{Colors.END} the generated files in {task_folder}

2. {Colors.CYAN}Validate{Colors.END} your task:
   python validate_task.py {task_name}

3. {Colors.YELLOW}Test Difficulty with an AI Agent (Required){Colors.END}
   Goal: At least one agent should fail!
   Recommended: Gemini 3 Pro, ChatGPT Agent, Claude 4.5
   Edit {task_folder}/evaluation.md to add results and chat transcript link

4. {Colors.CYAN}Encrypt{Colors.END} before submitting:
   python encrypt_tasks.py --task {task_name}

5. {Colors.CYAN}Submit{Colors.END} a Pull Request on GitHub

{Colors.BOLD}Need help?{Colors.END} See CONTRIBUTING.md for detailed instructions.
""")
    else:
        # Already tested
        print(f"""
{Colors.BOLD}What's next?{Colors.END}

1. {Colors.CYAN}Review{Colors.END} the generated files in {task_folder}

2. {Colors.CYAN}Validate{Colors.END} your task:
   python validate_task.py {task_name}

3. {Colors.GREEN}Agent Testing{Colors.END} ✓ Already recorded in evaluation.md

4. {Colors.CYAN}Encrypt{Colors.END} before submitting:
   python encrypt_tasks.py --task {task_name}

5. {Colors.CYAN}Submit{Colors.END} a Pull Request on GitHub

{Colors.BOLD}Need help?{Colors.END} See CONTRIBUTING.md for detailed instructions.
""")
    
    print_success("Happy contributing! 🚀")


def main():
    """Main entry point."""
    try:
        run_wizard()
    except KeyboardInterrupt:
        print(f"\n\n{Colors.YELLOW}Wizard cancelled by user.{Colors.END}")
        sys.exit(0)
    except Exception as e:
        print_error(f"An error occurred: {e}")
        sys.exit(1)


if __name__ == '__main__':
    main()

