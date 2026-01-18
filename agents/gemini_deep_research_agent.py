"""
Gemini Deep Research Agent implementation.

This agent uses Google's Gemini Deep Research API to perform complex research tasks
with web search and code execution capabilities.
"""

import importlib.util
import sys
import time
from pathlib import Path
from typing import Dict, Any, List, Optional

from google import genai

from .base import BaseAgent
from executor.utils import get_logger
from decrypt_utils import decrypt_file_to_memory, read_canary


logger = get_logger("gemini_deep_research_agent")


class GeminiDeepResearchAgent(BaseAgent):
    """Agent that uses Gemini Deep Research API for complex research tasks."""
    
    def __init__(self, config: Dict[str, Any]):
        """
        Initialize Gemini Deep Research Agent.
        
        Args:
            config: Configuration dictionary containing gemini_deep_research settings
        """
        super().__init__(config)
        
        # Get Gemini-specific config
        gemini_config = config.get("gemini_deep_research", {})
        
        # Initialize Gemini client
        api_key = gemini_config.get("api_key")
        if not api_key:
            raise ValueError("Gemini API key not found in config")
        
        self.client = genai.Client(api_key=api_key)
        
        # Agent name
        self.agent = gemini_config.get("agent", "deep-research-pro-preview-12-2025")
        
        # Execution settings
        self.background = gemini_config.get("background", True)
        self.timeout = gemini_config.get("timeout", 3600)  # 60 minutes default
        self.poll_interval = gemini_config.get("poll_interval", 10)
        
        # Agent config settings
        self.agent_config = gemini_config.get("agent_config", {
            "type": "deep-research",
            "thinking_summaries": "auto"  # Get detailed thinking process
        })
        
        # Streaming settings
        self.stream = gemini_config.get("stream", True)
        
        # Tools configuration
        self.use_file_search = gemini_config.get("use_file_search", True)
        
        # Track uploaded resources
        self.uploaded_files = []
        self.file_search_store = None
        
        logger.info(f"Initialized Gemini Deep Research Agent with agent={self.agent}")
    
    def setup_environment(self, task: Dict[str, Any]) -> None:
        """
        Set up environment for the task, including file uploads if needed.
        
        Args:
            task: Task dictionary containing task information
        """
        logger.info(f"Setting up environment for task: {task.get('task_name', 'unknown')}")
        
        # Reset state
        self.uploaded_files = []
        self.file_search_store = None
        
        # Check if task has assets directory
        task_dir = Path(task.get("task_dir", ""))
        assets_dir = task_dir / "assets"
        
        if not assets_dir.exists() or not self.use_file_search:
            logger.info("No assets directory or file search disabled, skipping file upload")
            return
        
        # Upload files to Gemini File Search Store
        try:
            files_to_upload = list(assets_dir.glob("*"))
            if not files_to_upload:
                logger.info("No files found in assets directory")
                return
            
            logger.info(f"Creating file search store for {len(files_to_upload)} files...")
            
            # Create file search store
            task_name = task.get('task_name', 'unknown')
            store_display_name = f"cocoa-task-{task_name}-{int(time.time())}"
            self.file_search_store = self.client.file_search_stores.create(
                config={'display_name': store_display_name}
            )
            logger.info(f"Created file search store: {self.file_search_store.name}")
            
            # Upload files directly to file search store
            for file_path in files_to_upload:
                if file_path.is_file():
                    try:
                        logger.info(f"Uploading file: {file_path.name} to file search store...")
                        
                        # Upload directly to file search store
                        operation = self.client.file_search_stores.upload_to_file_search_store(
                            file=str(file_path),
                            file_search_store_name=self.file_search_store.name,
                            config={
                                'display_name': file_path.name,
                            }
                        )
                        
                        # Wait for operation to complete
                        while not operation.done:
                            time.sleep(2)
                            operation = self.client.operations.get(operation)
                        
                        logger.info(f"Successfully uploaded and indexed: {file_path.name}")
                        self.uploaded_files.append(file_path.name)
                        
                    except Exception as e:
                        logger.warning(f"Failed to upload file {file_path.name}: {e}")
            
            logger.info(f"Successfully uploaded {len(self.uploaded_files)} files to file search store")
            
        except Exception as e:
            logger.error(f"Error during file upload: {e}", exc_info=True)
            logger.warning("Continuing without file search capability")
            self.file_search_store = None
            self.uploaded_files = []
    
    def run_task(self, task: Dict[str, Any]) -> Dict[str, Any]:
        """
        Run the task using Gemini Deep Research Agent.
        
        Args:
            task: Task dictionary containing instruction and metadata
            
        Returns:
            Dictionary containing task result and trajectory
        """
        task_name = task.get("task_name", "unknown")
        instruction = task.get("instruction", "")
        
        logger.info(f"Running task: {task_name}")
        logger.info(f"Instruction: {instruction[:100]}...")
        
        # Build tools list
        tools = []
        
        # Add file_search tool if we have a file search store
        if self.file_search_store:
            logger.info(f"Adding file_search tool with store: {self.file_search_store.name}")
            tools.append({
                "type": "file_search",
                "file_search_store_names": [self.file_search_store.name]
            })
        
        try:
            # Create interaction with Deep Research agent
            logger.info(f"Creating interaction with agent={self.agent}, background={self.background}, stream={self.stream}")
            
            if self.stream and self.background:
                # Use streaming mode to get real-time updates
                result = self._run_with_streaming(instruction, tools)
            else:
                # Use polling mode
                result = self._run_with_polling(instruction, tools)
            
            return result
            
        except Exception as e:
            logger.error(f"Error running task: {e}", exc_info=True)
            return {
                "agent_type": "gemini_deep_research",
                "task_name": task_name,
                "answer": "",
                "error": str(e),
                "trajectory": [],
                "success": False
            }
    
    def _run_with_streaming(self, instruction: str, tools: List[Dict]) -> Dict[str, Any]:
        """
        Run task with streaming to get real-time updates.
        
        Args:
            instruction: Task instruction
            tools: List of tools to use
            
        Returns:
            Dictionary containing result and trajectory
        """
        logger.info("Starting streaming interaction...")
        
        # Prepare request parameters
        request_params = {
            "input": instruction,
            "agent": self.agent,
            "background": True,
            "stream": True,
            "agent_config": self.agent_config
        }
        
        if tools:
            request_params["tools"] = tools
        
        # Start streaming
        stream = self.client.interactions.create(**request_params)
        
        interaction_id = None
        last_event_id = None
        trajectory = []
        final_text = ""
        status = None
        
        start_time = time.time()
        
        try:
            for chunk in stream:
                # Check timeout
                if time.time() - start_time > self.timeout:
                    raise TimeoutError(f"Streaming timed out after {self.timeout}s")
                
                # Capture interaction ID
                if chunk.event_type == "interaction.start":
                    interaction_id = chunk.interaction.id
                    logger.info(f"Interaction started: {interaction_id}")
                
                # Capture event ID
                if hasattr(chunk, "event_id") and chunk.event_id:
                    last_event_id = chunk.event_id
                
                # Process content deltas
                if chunk.event_type == "content.delta":
                    if chunk.delta.type == "text":
                        final_text += chunk.delta.text
                        print(chunk.delta.text, end="", flush=True)
                    elif chunk.delta.type == "thought_summary":
                        # Capture thinking process
                        thought = chunk.delta.content.text if hasattr(chunk.delta, "content") else str(chunk.delta)
                        trajectory.append({
                            "type": "thought",
                            "content": thought
                        })
                        logger.debug(f"Thought: {thought[:100]}...")
                
                # Check completion
                if chunk.event_type == "interaction.complete":
                    status = "completed"
                    logger.info("Interaction completed")
                    print("\n")  # New line after streaming
                    break
                
                elif chunk.event_type == "error":
                    status = "failed"
                    logger.error(f"Interaction failed: {chunk}")
                    break
        
        except Exception as e:
            logger.warning(f"Streaming interrupted: {e}")
            # If we have an interaction_id, we can try to resume or poll
            if interaction_id:
                logger.info("Attempting to retrieve final result via polling...")
                return self._poll_for_completion(interaction_id, trajectory)
            else:
                raise
        
        # If streaming completed successfully
        if status == "completed":
            return {
                "agent_type": "gemini_deep_research",
                "answer": final_text,
                "trajectory": trajectory,
                "interaction_id": interaction_id,
                "success": True
            }
        else:
            raise Exception(f"Interaction ended with status: {status}")
    
    def _run_with_polling(self, instruction: str, tools: List[Dict]) -> Dict[str, Any]:
        """
        Run task with polling mode (no streaming).
        
        Args:
            instruction: Task instruction
            tools: List of tools to use
            
        Returns:
            Dictionary containing result and trajectory
        """
        logger.info("Starting polling interaction...")
        
        # Prepare request parameters
        request_params = {
            "input": instruction,
            "agent": self.agent,
            "background": True
        }
        
        if tools:
            request_params["tools"] = tools
        
        # Create interaction
        initial_interaction = self.client.interactions.create(**request_params)
        interaction_id = initial_interaction.id
        
        logger.info(f"Interaction created: {interaction_id}")
        
        # Poll for completion
        return self._poll_for_completion(interaction_id, [])
    
    def _poll_for_completion(self, interaction_id: str, initial_trajectory: List[Dict]) -> Dict[str, Any]:
        """
        Poll for interaction completion.
        
        Args:
            interaction_id: ID of the interaction to poll
            initial_trajectory: Any trajectory data already collected
            
        Returns:
            Dictionary containing result and trajectory
        """
        start_time = time.time()
        
        while True:
            elapsed = time.time() - start_time
            
            if elapsed > self.timeout:
                raise TimeoutError(f"Interaction {interaction_id} timed out after {self.timeout}s")
            
            # Get interaction status
            interaction = self.client.interactions.get(interaction_id)
            status = interaction.status
            
            logger.info(f"Status: {status} (elapsed: {elapsed:.1f}s)")
            
            if status == "completed":
                logger.info(f"Interaction completed in {elapsed:.1f}s")
                
                # Extract final answer
                final_text = ""
                if interaction.outputs:
                    for output in interaction.outputs:
                        if output.type == "text":
                            final_text += output.text
                
                # Extract trajectory if available
                trajectory = initial_trajectory.copy()
                trajectory.extend(self._extract_trajectory(interaction))
                
                return {
                    "agent_type": "gemini_deep_research",
                    "answer": final_text,
                    "trajectory": trajectory,
                    "interaction_id": interaction_id,
                    "usage": getattr(interaction, "usage", None),
                    "success": True
                }
            
            elif status in ["failed", "cancelled"]:
                error_msg = getattr(interaction, "error", "Unknown error")
                logger.error(f"Interaction failed with status {status}: {error_msg}")
                raise Exception(f"Interaction failed: {error_msg}")
            
            # Still in progress, wait before polling again
            time.sleep(self.poll_interval)
    
    def _extract_trajectory(self, interaction) -> List[Dict[str, Any]]:
        """
        Extract trajectory information from completed interaction.
        
        Args:
            interaction: Completed interaction object
            
        Returns:
            List of trajectory steps
        """
        trajectory = []
        
        # Gemini interactions may include outputs with different types
        if hasattr(interaction, "outputs") and interaction.outputs:
            for i, output in enumerate(interaction.outputs):
                step = {
                    "type": output.type,
                    "index": i
                }
                
                if output.type == "text":
                    step["text"] = output.text
                
                elif output.type == "thought":
                    step["thought"] = getattr(output, "thought", None)
                
                elif output.type == "function_call":
                    step["function_name"] = getattr(output, "name", None)
                    step["arguments"] = getattr(output, "arguments", None)
                
                elif output.type == "function_result":
                    step["function_name"] = getattr(output, "name", None)
                    step["result"] = getattr(output, "result", None)
                
                # Add any other attributes
                if hasattr(output, "__dict__"):
                    for key, value in output.__dict__.items():
                        if key not in step and not key.startswith("_"):
                            try:
                                step[key] = value
                            except:
                                pass
                
                trajectory.append(step)
        
        logger.info(f"Extracted {len(trajectory)} trajectory steps")
        return trajectory
    
    def run_eval(self, task: Dict[str, Any], result: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """
        Run evaluation for the task using test.py if available.
        
        Args:
            task: Task dictionary
            result: Result dictionary from run_task
            
        Returns:
            Evaluation result dictionary or None if no test file
        """
        test_file_path = task.get("test_file_path")
        if not test_file_path:
            logger.info("No test file specified, skipping evaluation")
            return None
        
        test_file_path = Path(test_file_path)
        if not test_file_path.exists():
            logger.warning(f"Test file not found: {test_file_path}")
            return None
        
        logger.info(f"Running evaluation with test file: {test_file_path}")
        
        try:
            # Check if we need to decrypt
            use_encrypted = task.get("use_encrypted", False)
            
            if use_encrypted and test_file_path.suffix == ".enc":
                # Decrypt test file to memory
                task_dir = Path(task.get("task_dir", ""))
                canary = read_canary(task_dir)
                if canary is None:
                    logger.error("Cannot decrypt test file: no canary found")
                    return {"success": False, "error": "No canary found for decryption"}
                
                test_code = decrypt_file_to_memory(test_file_path, canary)
            else:
                # Read plaintext test file
                with open(test_file_path, 'r', encoding='utf-8') as f:
                    test_code = f.read()
            
            # Load and execute test module
            spec = importlib.util.spec_from_loader("test_module", loader=None)
            test_module = importlib.util.module_from_spec(spec)
            sys.modules["test_module"] = test_module
            
            # Execute test code
            exec(test_code, test_module.__dict__)
            
            # Call test function
            if hasattr(test_module, "test"):
                test_result = test_module.test(result)
                logger.info(f"Test completed: {test_result}")
                return test_result
            else:
                logger.warning("Test module does not have a 'test' function")
                return {"success": False, "error": "No test function found"}
        
        except Exception as e:
            logger.error(f"Error running evaluation: {e}", exc_info=True)
            return {"success": False, "error": str(e)}
        finally:
            # Clean up module
            if "test_module" in sys.modules:
                del sys.modules["test_module"]
    
    def cleanup_environment(self) -> None:
        """Clean up resources after task completion."""
        logger.info("Cleaning up environment...")
        
        # Delete file search store (this will delete all associated files)
        if self.file_search_store:
            logger.info(f"Deleting file search store: {self.file_search_store.name}")
            try:
                self.client.file_search_stores.delete(
                    name=self.file_search_store.name,
                    config={'force': True}
                )
                logger.info("File search store deleted successfully")
            except Exception as e:
                logger.warning(f"Failed to delete file search store: {e}")
        
        # Reset state
        self.uploaded_files = []
        self.file_search_store = None
        
        logger.info("Cleanup completed")


