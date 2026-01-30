import argparse
import json
from pathlib import Path

def main():
    parser = argparse.ArgumentParser(description="Calculate success rate statistics from output JSON files")
    parser.add_argument("output_dir", type=str, help="Directory containing the output JSON files")
    args = parser.parse_args()

    output_path = Path(args.output_dir)
    if not output_path.exists() or not output_path.is_dir():
        print(f"Error: Directory not found: {args.output_dir}")
        return

    total_tasks = 0
    passed_tasks = 0
    failed_tasks = 0
    error_tasks = 0
    passed_list = []
    error_list = []

    print(f"Scanning directory: {output_path}")

    for json_file in output_path.glob("*.json"):
        try:
            with open(json_file, 'r') as f:
                data = json.load(f)
                total_tasks += 1
                if data.get("status") == "error":
                    error_tasks += 1
                    error_list.append(json_file.stem)
                elif data.get("eval", {}).get("passed", False) is True:
                    passed_tasks += 1
                    passed_list.append(json_file.stem)
                else:
                    failed_tasks += 1
        except Exception as e:
            print(f"Error reading {json_file}: {e}")

    success_rate = (passed_tasks / total_tasks * 100) if total_tasks > 0 else 0.0

    print("-" * 30)
    print(f"Total Tasks: {total_tasks}")
    print(f"Passed:      {passed_tasks}")
    print(f"Failed:      {failed_tasks}")
    print(f"Errors:      {error_tasks}")
    print("-" * 30)
    print(f"Success Rate: {success_rate:.2f}%")
    print("-" * 30)
    
    if passed_list:
        print("\nPassed Tasks:")
        for task_name in sorted(passed_list):
            print(f"  - {task_name}")
        print("-" * 30)

    if error_list:
        print("\nError Tasks:")
        for task_name in sorted(error_list):
            print(f"  - {task_name}")
        print("-" * 30)


if __name__ == "__main__":
    main()
