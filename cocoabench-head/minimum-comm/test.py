"""
Test function for minimum communication puzzle.

Evaluates the code that solves the minimum communication puzzle where Alice
needs to send a list of different positive integers to Bob using a keyboard
with N different symbols.
"""

import json
import re
from typing import List

# Expected minimum number of symbols
EXPECTED_N = 1

# Test cases: various lists of different positive integers
TEST_CASES = [
    [1],
    [1, 2],
    [2, 1],
    [1, 2, 3],
    [1, 2, 3, 4, 5]
]


def _extract_from_tags(text: str, tag: str) -> str | None:
    """Extract content from <tag>...</tag>."""
    pattern = re.compile(rf'<{tag}>(.*?)</{tag}>', re.IGNORECASE | re.DOTALL)
    match = pattern.search(text)
    if match:
        return match.group(1).strip()
    return None


def _extract_response_from_conversation(conversation: list) -> str | None:
    """Extract the full response text from conversation history."""
    # First, check assistant messages with tool_calls for task_complete with result parameter
    for message in reversed(conversation or []):
        if not isinstance(message, dict):
            continue
        if message.get("role") == "assistant" and message.get("tool_calls"):
            # Check if any tool call is task_complete with result
            for tc in message.get("tool_calls", []):
                if not isinstance(tc, dict):
                    continue
                func = tc.get("function", {})
                if func.get("name") == "task_complete":
                    # Extract result from tool call arguments
                    try:
                        args_str = func.get("arguments", "{}")
                        args = json.loads(args_str) if isinstance(args_str, str) else args_str
                        if "result" in args:
                            return args["result"]
                    except (json.JSONDecodeError, Exception):
                        pass
    
    # Search through assistant messages in reverse order for content
    for message in reversed(conversation or []):
        if not isinstance(message, dict):
            continue
        if message.get("role") != "assistant":
            continue
        content = message.get("content") or ""
        if content:
            return content
    return None


def test(result: dict) -> dict:
    """
    Test executor result.

    Args:
        result: Result dict from TaskExecutor.run_task()

    Returns:
        Test dict with metrics and pass/fail status
    """
    conversation = result.get("conversation") or []
    task_completed = result.get("status") == "success"

    # Extract the full response text
    task_result = result.get("task_result")
    if not task_result:
        task_result = _extract_response_from_conversation(conversation)
    
    if not task_result:
        return {
            "passed": False,
            "feedback": "No valid response found in assistant messages.",
            "details": {
                "task_completed": task_completed,
                "conversation_length": len(conversation),
            },
        }

    # Extract N, encode function, and decode function
    n_str = _extract_from_tags(task_result, "answer")
    encode_func_str = _extract_from_tags(task_result, "encode_function")
    decode_func_str = _extract_from_tags(task_result, "decode_function")

    feedback_parts = []
    all_checks_passed = True

    # Check 1: N should be extracted and equal to 1
    if not n_str:
        feedback_parts.append("✗ No <answer>N</answer> found in response.")
        all_checks_passed = False
    else:
        try:
            n_value = int(n_str.strip())
            if n_value == EXPECTED_N:
                feedback_parts.append(f"✓ N = {n_value} (correct)")
            else:
                feedback_parts.append(f"✗ N = {n_value}, expected {EXPECTED_N}")
                all_checks_passed = False
        except ValueError:
            feedback_parts.append(f"✗ Could not parse N from '{n_str}'")
            all_checks_passed = False

    # Check 2 & 3: Extract and test encode/decode functions
    if not encode_func_str:
        feedback_parts.append("✗ No <encode_function>...</encode_function> found in response.")
        all_checks_passed = False
    if not decode_func_str:
        feedback_parts.append("✗ No <decode_function>...</decode_function> found in response.")
        all_checks_passed = False

    if encode_func_str and decode_func_str:
        try:
            # Execute the function definitions in a namespace
            namespace = {}
            exec(encode_func_str, namespace)
            exec(decode_func_str, namespace)
            
            encode = namespace.get("encode")
            decode = namespace.get("decode")
            
            if not encode:
                feedback_parts.append("✗ encode function not defined correctly.")
                all_checks_passed = False
            if not decode:
                feedback_parts.append("✗ decode function not defined correctly.")
                all_checks_passed = False
            
            if encode and decode:
                # Run test cases
                test_results = []
                unique_char_check_passed = True
                encode_decode_check_passed = True
                
                for i, test_list in enumerate(TEST_CASES):
                    try:
                        # Encode the list
                        encoded = encode(test_list)
                        
                        # Check that encoded string has only 1 unique character
                        unique_chars = len(set(encoded))
                        if unique_chars != 1:
                            test_results.append(
                                f"  Test {i+1} {test_list}: encoded '{encoded[:50]}...' has {unique_chars} unique chars (expected 1)"
                            )
                            unique_char_check_passed = False
                            all_checks_passed = False
                        
                        # Decode the string
                        decoded = decode(encoded)
                        
                        # Check if decoded matches original
                        if decoded != test_list:
                            test_results.append(
                                f"  Test {i+1} {test_list}: decoded as {decoded} (mismatch)"
                            )
                            encode_decode_check_passed = False
                            all_checks_passed = False
                    except Exception as e:
                        test_results.append(f"  Test {i+1} {test_list}: error - {str(e)}")
                        encode_decode_check_passed = False
                        all_checks_passed = False
                
                if unique_char_check_passed:
                    feedback_parts.append("✓ All encoded strings use exactly 1 unique character")
                else:
                    feedback_parts.append("✗ Some encoded strings do not use exactly 1 unique character")
                
                if encode_decode_check_passed:
                    feedback_parts.append(f"✓ All {len(TEST_CASES)} test cases passed encode/decode correctly")
                else:
                    feedback_parts.append("✗ Some test cases failed:")
                    feedback_parts.extend(test_results)
                    
        except Exception as e:
            feedback_parts.append(f"✗ Error executing functions: {str(e)}")
            all_checks_passed = False

    passed = task_completed and all_checks_passed

    if not task_completed:
        feedback_parts.append("✗ Task status is not success.")

    return {
        "passed": passed,
        "feedback": "\n".join(feedback_parts),
        "details": {
            "task_completed": task_completed,
            "n_correct": n_str == str(EXPECTED_N) if n_str else False,
            "has_encode_function": encode_func_str is not None,
            "has_decode_function": decode_func_str is not None,
        },
    }

