"""
Executor module for task execution with controllers and sandbox agents.
"""

import importlib.util
import sys
from pathlib import Path
from typing import Any, Dict

from .logger import setup_logging, get_logger
from .controller import OpenAILLM, QwenLLM, BaseLLM, Controller, Human, GeminiLLM, ClaudeLLM
from .sandbox import (
    BrowserSandboxClient,
    UnifiedSandboxClient,
)
from .utils import colorize, extract_config_info, measure_execution_time

# Import decrypt utilities for encrypted test files
try:
    from decrypt import decrypt_file_to_memory, read_canary
    DECRYPT_AVAILABLE = True
except ImportError:
    DECRYPT_AVAILABLE = False

logger = get_logger("executor")

__all__ = [
    "TaskExecutor",
    "OpenAILLM",
    "QwenLLM",
    "BaseLLM",
    "GeminiLLM",
    "ClaudeLLM",
    "Controller",
    "Human",
    "BrowserSandboxClient",
    "UnifiedSandboxClient",
    "setup_logging",
    "get_logger",
]

def is_browser_action(action: Dict[str, Any]) -> bool:
    """Check if an action is a browser-related action.
    
    Args:
        action: Action dictionary
        
    Returns:
        True if the action is a browser action, False otherwise
    """
    if not isinstance(action, dict):
        return False
    
    action_type = action.get("action_type", "")
    browser_action_types = [
        "browser_click", "browser_type", "browser_press", "browser_key_down", "browser_key_up", "browser_hotkey",
        "browser_scroll", "browser_move_to", "browser_move_rel", "browser_drag_to", "browser_drag_rel",
        "browser_wait",
        "dom_get_text", "dom_get_html", "dom_query_selector",
        "dom_extract_links", "dom_mark_elements", "dom_click", "dom_hover", "dom_type", "dom_press", "dom_scroll",
        "browser_navigate",
        "browser_screenshot", "browser_get_viewport_info",
    ]
    return action_type in browser_action_types

def normalize_action(action: Dict[str, Any]) -> Dict[str, Any]:
    """Normalize action format by flattening parameters if present.
    
    Handles both formats:
    - {"action_type": "file_list", "path": "/home/gem/"} (correct)
    - {"action_type": "file_list", "parameters": {"path": "/home/gem/"}} (needs normalization)
    
    Args:
        action: Action dictionary that may have nested parameters
        
    Returns:
        Normalized action with parameters flattened to top level
    """
    if not isinstance(action, dict):
        return action
    
    # If action has "parameters" field, flatten it
    if "parameters" in action and isinstance(action.get("parameters"), dict):
        normalized = {"action_type": action.get("action_type")}
        normalized.update(action["parameters"])
        # Preserve other top-level fields (like tool_call_id)
        for key, value in action.items():
            if key not in ["parameters", "action_type"]:
                normalized[key] = value
        return normalized
    
    return action

class TaskExecutor:
    """Executes tasks using a controller with agent feedback loop."""

    def __init__(self, config: dict, controller: Controller | None = None):
        """Initialize TaskExecutor.

        Args:
            config: Configuration dictionary with optional 'controller' section
            controller: Controller instance (LLM or Human). If None, creates controller from config.
        """
        self.config = config
        
        logger.info(f"Config: {config}")

        sandbox_config = config.get("sandbox", {})
        
        # Determine which sandbox client to use based on config
        client_type = sandbox_config.get("client_type", "shell").lower()
        
        if controller is None:
            # Get controller type and config from config dict
            controller_config = config.get("controller", {})
            controller_type = controller_config.get("type", "llm").lower()

            if controller_type == "human":
                controller = Human()
            elif controller_type == "gemini":
                llm_config = controller_config.get("args", {})
                controller = GeminiLLM(llm_config=llm_config, client_type=client_type)
            elif controller_type == "qwen":
                llm_config = controller_config.get("args", {})
                controller = QwenLLM(llm_config=llm_config, client_type=client_type)
            elif controller_type == "claude":
                llm_config = controller_config.get("args", {})
                controller = ClaudeLLM(llm_config=llm_config, client_type=client_type)
            else:  # Default to OpenAILLM (handles "gpt", "openai", "llm", etc.)
                llm_config = controller_config.get("args", {})
                controller = OpenAILLM(llm_config=llm_config, client_type=client_type)

            logger.info(f"Controller initialized: {controller_type} (Model: {llm_config.get('model', 'unknown')})")

        self.controller = controller
        if client_type == "unified":
            self.sandbox_client = UnifiedSandboxClient(sandbox_config=sandbox_config)
            logger.info("Using UnifiedSandboxClient (browser + file + code + shell)")
        elif client_type == "browser":
            self.sandbox_client = BrowserSandboxClient(sandbox_config=sandbox_config)
            logger.info("Using BrowserSandboxClient")
        else:
            # Default to UnifiedSandboxClient for "shell" or unknown types
            # UnifiedSandboxClient supports all tools including shell
            self.sandbox_client = UnifiedSandboxClient(sandbox_config=sandbox_config)
            logger.info(f"Using UnifiedSandboxClient as fallback for client_type='{client_type}'")

    def setup_environment(self, task: dict, wait_time: int = 30) -> None:
        """Initialize the sandbox environment for task execution.

        Args:
            task: Task object containing task_dir and other task metadata
            wait_time: Time to wait for server to be ready (default: 30 seconds)
        """
        if self.sandbox_client.create_docker_environment(task, wait_time):
            logger.info(f"Sandbox environment ready (Container: {self.sandbox_client.container_id})")
        else:
            raise RuntimeError("Sandbox environment failed to become ready")
        self.controller.clear_history()

    def cleanup_environment(self) -> None:
        """Clean up the sandbox environment after execution."""
        self.sandbox_client.cleanup_docker_environment()
        self.controller.clear_history()

    @measure_execution_time
    def run_task(self, task: dict) -> dict:
        """Run inference on the given task with agent loop.

        Args:
            task: Task dictionary containing task metadata including instruction

        Returns:
            Dictionary with results including status, model info, conversation history, and execution_time
        """
        task_desc = task.get("instruction", str(task))
        max_iterations = self.config.get("sandbox", {}).get("max_iterations", 10)
        # max_conversation_turns = self.config.get("sandbox", {}).get("max_conversation_turns", 5)  # Commented out - using self.messages for context instead

        logger.debug(f"Task description: {colorize(task_desc, 'YELLOW')}")

        def add_progress_note(base_message: str, current_iteration: int) -> str:
            """Append iteration progress context to controller prompts."""
            remaining = max(max_iterations - current_iteration, 0)
            note = (
                f"\n\n[Progress update: iteration {current_iteration}/{max_iterations}. "
                f"Remaining iterations: {remaining}.]"
            )
            if remaining <= 2:
                note += " You are near the maximum iteration budget. Prioritize finishing steps and produce the final boxed answer soon."
            return f"{base_message}{note}"

        # Store task description for initial prompt only
        self.task_description = task_desc

        def record_tool_feedback(action_dict: dict, feedback_dict: dict) -> None:
            """Append tool call outputs to controller history for OpenAI compliance."""
            if not isinstance(action_dict, dict):
                return
            tool_call_id = action_dict.get("tool_call_id")
            if not tool_call_id:
                return
            content = feedback_dict.get("message", "")
            if hasattr(self.controller, "add_tool_message"):
                self.controller.add_tool_message(tool_call_id, content if isinstance(content, str) else str(content))

        # Build initial prompt (only for first iteration)
        prompt = self.controller.build_prompt(task_description=task_desc)

        action = None
        final_iteration = 0
        last_feedback_with_image = None
        images_from_last_iteration = []  # Store images from the previous iteration only
        task_result = None  # Store task result if provided in task_complete
        
        # Initialize visualization data structure
        visualization_data = {
            "task_description": task_desc,
            "iterations": []
        }

        # Agent loop
        for iteration in range(1, max_iterations + 1):
            final_iteration = iteration
            logger.info(f"Iteration {iteration}/{max_iterations}")

            # Get controller response (already parsed into action dict)
            # Only include images from the previous iteration (i-1), not all historical images
            images_base64 = images_from_last_iteration.copy() if images_from_last_iteration else None
            if images_base64:
                logger.debug(f"Including {len(images_base64)} image(s) from previous iteration in next prompt")
            
            prompt_with_progress = add_progress_note(prompt, iteration)
            # Pass list of images (only from previous iteration)
            action = self.controller.call(prompt_with_progress, images_base64=images_base64)
            
            # Extract think content from controller
            think_content = None
            if hasattr(self.controller, 'get_last_think'):
                think_content = self.controller.get_last_think()

            # Handle error action (parsing errors from tool calls)
            if isinstance(action, dict) and action.get("action_type") == "error":
                error_message = action.get("error_message", "Unknown error occurred while parsing tool calls")
                logger.warning(f"Tool call parsing error: {error_message}")
                # Create feedback with error message to send back to model
                feedback = {
                    "done": False,
                    "message": f"Error: {error_message}\nPlease correct the tool call parameters and try again."
                }
                # Prepare next prompt with error feedback
                prompt = self.controller.build_prompt(
                    feedback=feedback.get("message", "Continue with the task.")
                )
                continue

            # Normalize action format
            action = normalize_action(action)

            # Handle multiple actions (from tool calling)
            if "actions" in action:
                # Execute multiple actions sequentially
                feedbacks = []
                done = False
                images_from_current_iteration = []  # Collect all images from current iteration
                browser_screenshots = [] # Collect only browser screenshots
                image_read_contents = [] # Collect only image_read contents
                iteration_actions = []  # Store actions for visualization
                
                for single_action in action["actions"]:
                    # Normalize action format
                    single_action = normalize_action(single_action)
                    single_feedback = self.sandbox_client.get_feedback(single_action)
                    record_tool_feedback(single_action, single_feedback) # TODO: optimize OpenAI Tool Calling format to avoid extra messages in the conversation history
                    feedbacks.append(single_feedback.get("message", ""))
                    
                    # For browser actions, take a screenshot after execution (unless it's already a screenshot action)
                    screenshot_base64 = None
                    if is_browser_action(single_action) and single_action.get("action_type") != "browser_screenshot":
                        if hasattr(self.sandbox_client, 'take_screenshot'):
                            try:
                                screenshot_base64, _ = self.sandbox_client.take_screenshot()
                                if screenshot_base64:
                                    browser_screenshots.append(screenshot_base64)
                            except Exception as e:
                                logger.warning(f"Failed to take screenshot after browser action: {e}")
                    
                    # Check if this action was a screenshot or image_read and has image_base64
                    if single_action.get("action_type") == "browser_screenshot" and "image_base64" in single_feedback:
                        image_base64 = single_feedback["image_base64"]
                        browser_screenshots.append(image_base64)
                    
                    if single_action.get("action_type") == "image_read" and "image_base64" in single_feedback:
                        image_base64 = single_feedback["image_base64"]
                        if image_base64 not in image_read_contents:
                            image_read_contents.append(image_base64)
                    
                    # Store action data for visualization
                    action_data = {
                        "action": single_action,
                        "observation": single_feedback.get("message", ""),
                        "screenshot": screenshot_base64 if screenshot_base64 else (single_feedback.get("image_base64") if single_action.get("action_type") in ["browser_screenshot", "image_read"] else None)
                    }
                    iteration_actions.append(action_data)
                    
                    if single_feedback.get("done"):
                        done = True
                        break
                
                # Combine all feedbacks
                combined_feedback = {
                    "done": done,
                    "message": "\n".join(feedbacks) # '/n' is used to separate each feedback
                }
                
                # Construct images list for next iteration
                # 1. Take ONLY the last browser screenshot if available
                # 2. Add ALL image_read contents
                images_from_last_iteration = []
                
                if browser_screenshots:
                    images_from_last_iteration.append(browser_screenshots[-1])
                
                # Append all manually read images
                images_from_last_iteration.extend(image_read_contents)
                
                # For backward compatibility in feedback dict (though mostly unused if images_from_last_iteration is set)
                if images_from_last_iteration:
                    combined_feedback["image_base64"] = images_from_last_iteration[-1]
                
                feedback = combined_feedback
                
                # Store iteration data for visualization
                visualization_data["iterations"].append({
                    "iteration": iteration,
                    "think": think_content,
                    "actions": iteration_actions
                })
            else:
                # Single action
                feedback = self.sandbox_client.get_feedback(action)
                record_tool_feedback(action, feedback)
                
                # For browser actions, take a screenshot after execution (unless it's already a screenshot action)
                screenshot_base64 = None
                if is_browser_action(action) and action.get("action_type") != "browser_screenshot":
                    if hasattr(self.sandbox_client, 'take_screenshot'):
                        try:
                            screenshot_base64, _ = self.sandbox_client.take_screenshot()
                        except Exception as e:
                            logger.warning(f"Failed to take screenshot after browser action: {e}")
                
                # Store images from this iteration for next iteration
                images_from_last_iteration = []  # Reset for current iteration
                if action.get("action_type") in ["browser_screenshot", "image_read"] and "image_base64" in feedback:
                    image_base64 = feedback["image_base64"]
                    images_from_last_iteration = [image_base64]  # Store single image for next iteration
                elif screenshot_base64:
                    images_from_last_iteration = [screenshot_base64]
                
                # Store iteration data for visualization
                visualization_data["iterations"].append({
                    "iteration": iteration,
                    "think": think_content,
                    "actions": [{
                        "action": action,
                        "observation": feedback.get("message", ""),
                        "screenshot": screenshot_base64 if screenshot_base64 else (feedback.get("image_base64") if action.get("action_type") in ["browser_screenshot", "image_read"] else None)
                    }]
                })

            # Store the full feedback (including image_base64) for next iteration
            last_feedback_with_image = feedback

            # Check if task is complete
            if feedback.get("done"):
                logger.info(f"Task completed at iteration {iteration}")
                # Extract task_result if present
                if "task_result" in feedback:
                    task_result = feedback.get("task_result")
                break

            # Prepare next prompt - only feedback, context is maintained in self.messages
            prompt = self.controller.build_prompt(
                feedback=feedback.get("message", "Continue with the task.")
            )

        result_dict = task | extract_config_info(self.config) | {
            "status": "success",
            "iterations": final_iteration,
            "conversation": self.controller.get_history(),
            "execution_trace": self.sandbox_client.get_history(),
            "visualization_data": visualization_data,  # Add visualization data
        }
        
        # Add task_result if it was provided in task_complete
        if task_result:
            result_dict["task_result"] = task_result
        
        # Add API cost statistics if controller supports it
        if hasattr(self.controller, "get_cost_stats"):
            result_dict["api_cost_stats"] = self.controller.get_cost_stats()
        
        return result_dict

    @measure_execution_time
    def run_eval(self, task: dict, result: dict) -> dict:
        """Load and run test function from task's test.py or test.py.enc.

        Args:
            task: Task dictionary containing test_file_path and use_encrypted flag
            result: Result dictionary from run_task

        Returns:
            Test result dictionary or None if no test file
        """
        test_file_path = task.get("test_file_path")
        task_name = task.get("task_name", "unknown")
        use_encrypted = task.get("use_encrypted", False)

        # Early return if no test file
        if test_file_path is None:
            logger.debug(f"No test file found for task '{task_name}', skipping evaluation")
            return None

        logger.info(f"Running test for task '{task_name}' with test file {test_file_path} (encrypted: {use_encrypted})")

        try:
            test_file = Path(test_file_path)
            
            # Verify file exists
            if not test_file.exists():
                logger.warning(f"Test file {test_file_path} does not exist for task '{task_name}'")
                return None

            if use_encrypted:
                # Handle encrypted test file - decrypt to memory only
                if not DECRYPT_AVAILABLE:
                    raise ImportError("decrypt module not available but use_encrypted=True")
                
                # Read canary from task directory
                task_dir = Path(task.get("task_dir"))
                canary = read_canary(task_dir)
                if canary is None:
                    raise ValueError(f"No canary.txt found in {task_dir}")
                
                # Decrypt test.py.enc to memory
                test_code = decrypt_file_to_memory(test_file, canary)
                
                # Execute the decrypted code in a new module namespace
                module = type(sys)("test")
                module.__file__ = str(test_file)  # Set a pseudo file path for debugging
                sys.modules["test"] = module
                
                # Compile and execute the code in the module's namespace
                compiled_code = compile(test_code, str(test_file), 'exec')
                exec(compiled_code, module.__dict__)
                
                logger.debug(f"Test module loaded and executed from encrypted file (in-memory)")
            else:
                # Handle plaintext test file - normal import
                spec = importlib.util.spec_from_file_location("test", test_file)
                module = importlib.util.module_from_spec(spec)
                sys.modules["test"] = module
                spec.loader.exec_module(module)
                
                logger.debug(f"Test module loaded successfully from {test_file_path}")

            if hasattr(module, "test"):
                test_fn = module.test
                test_result = test_fn(result)
                logger.info(f"Test completed for task '{task_name}': {colorize(test_result, 'YELLOW')}")
                return test_result
            else:
                logger.warning(f"No 'test' function found in {test_file_path} for task '{task_name}'")
                return None
        except Exception as e:
            logger.error(f"Failed to run test for task '{task_name}': {e}")
            raise
