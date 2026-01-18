"""
OpenAI Deep Research Agent implementation.
"""

import sys
import importlib.util
import time
from pathlib import Path
from typing import Dict, Any, List, Optional
from openai import OpenAI
from executor.utils import get_logger, measure_execution_time
from .base import BaseAgent

# Import decrypt utilities for encrypted test files
try:
    from decrypt_utils import decrypt_file_to_memory, read_canary
    DECRYPT_AVAILABLE = True
except ImportError:
    DECRYPT_AVAILABLE = False

logger = get_logger("openai_deep_research")


class OpenAIDeepResearchAgent(BaseAgent):
    """Agent using OpenAI Deep Research API."""
    
    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)
        dr_config = config.get("openai_deep_research", {})
        
        self.model = dr_config.get("model", "o4-mini-deep-research-2025-06-26")
        self.api_key = dr_config.get("api_key")
        self.background = dr_config.get("background", True)
        self.timeout = dr_config.get("timeout", 3600)
        self.max_tool_calls = dr_config.get("max_tool_calls")
        self.reasoning_summary = dr_config.get("reasoning", {}).get("summary", "detailed")
        
        self.client = OpenAI(api_key=self.api_key, timeout=self.timeout)
        self.vector_store_id = None
        self.uploaded_file_ids = []
    
    def setup_environment(self, task: Dict[str, Any]) -> None:
        """Upload task files to OpenAI if needed."""
        task_dir = Path(task.get("task_dir", ""))
        assets_dir = task_dir / "assets"
        
        if not assets_dir.exists():
            logger.info("No assets directory found, skipping file upload")
            return
        
        logger.info(f"Uploading files from {assets_dir}")
        
        # Upload all files in assets directory
        for file_path in assets_dir.rglob("*"):
            if file_path.is_file():
                try:
                    with open(file_path, "rb") as f:
                        uploaded_file = self.client.files.create(
                            file=f,
                            purpose="assistants"
                        )
                        self.uploaded_file_ids.append(uploaded_file.id)
                        logger.info(f"Uploaded {file_path.name} -> {uploaded_file.id}")
                except Exception as e:
                    logger.error(f"Failed to upload {file_path}: {e}")
        
        # Create vector store if files were uploaded
        if self.uploaded_file_ids:
            try:
                # Check if beta.vector_stores is available
                if not hasattr(self.client.beta, 'vector_stores'):
                    logger.warning("vector_stores API not available in this SDK version, skipping file search")
                    return
                
                # Create vector store with files
                vector_store = self.client.beta.vector_stores.create(
                    name=f"task_{task.get('task_name', 'unknown')}",
                    file_ids=self.uploaded_file_ids
                )
                
                self.vector_store_id = vector_store.id
                logger.info(f"Created vector store: {self.vector_store_id} with {len(self.uploaded_file_ids)} files")
            except AttributeError as e:
                logger.error(f"Vector stores API not available: {e}")
                logger.warning("Continuing without file search capability - files uploaded but not indexed")
            except Exception as e:
                logger.error(f"Failed to create vector store: {e}")
                logger.warning("Continuing without file search capability")
    
    @measure_execution_time
    def run_task(self, task: Dict[str, Any]) -> Dict[str, Any]:
        """Execute task using Deep Research API."""
        instruction = task.get("instruction", "")
        task_name = task.get("task_name", "unknown")
        
        logger.info(f"Starting Deep Research for task: {task_name}")
        logger.info(f"Instruction: {instruction[:200]}...")
        
        # Build tools configuration
        tools = [
            {"type": "web_search_preview"},
            {
                "type": "code_interpreter",
                "container": {"type": "auto"}
            }
        ]
        
        # Add file search if we have a vector store
        if self.vector_store_id:
            tools.append({
                "type": "file_search",
                "vector_store_ids": [self.vector_store_id]
            })
            logger.info(f"Using file search with vector store: {self.vector_store_id}")
        
        # Create response
        try:
            response = self.client.responses.create(
                model=self.model,
                input=instruction,
                background=self.background,
                tools=tools,
                reasoning={"summary": self.reasoning_summary},
                max_tool_calls=self.max_tool_calls,
                include=[
                    "web_search_call.action.sources",
                    "code_interpreter_call.outputs",
                    "file_search_call.results"
                ]
            )
            
            response_id = response.id
            logger.info(f"Created response: {response_id}")
            
            # Poll for completion if in background mode
            if self.background:
                response = self._poll_for_completion(response_id)
            
            # Extract results
            result = self._build_result(task, response)
            logger.info(f"Task completed with status: {result['status']}")
            
            return result
            
        except Exception as e:
            logger.error(f"Deep Research failed: {e}")
            return {
                "agent_type": "openai_deep_research",
                "task_name": task_name,
                "instruction": instruction,
                "status": "failed",
                "answer": "",
                "trajectory": {"error": str(e)},
                "execution_time": 0.0,
                "metadata": {"error": str(e)}
            }
    
    def _poll_for_completion(self, response_id: str) -> Any:
        """Poll for response completion."""
        start_time = time.time()
        poll_interval = 10  # seconds
        
        # Include parameters to get full details
        include_params = [
            "web_search_call.action.sources",
            "code_interpreter_call.outputs",
            "file_search_call.results"
        ]
        
        while True:
            elapsed = time.time() - start_time
            if elapsed > self.timeout:
                raise TimeoutError(f"Response {response_id} timed out after {self.timeout}s")
            
            # Retrieve with include parameters to get full output details
            response = self.client.responses.retrieve(response_id, include=include_params)
            status = response.status
            
            logger.debug(f"Response status: {status} (elapsed: {elapsed:.1f}s)")
            
            if status == "completed":
                logger.info(f"Response completed in {elapsed:.1f}s")
                return response
            elif status == "failed":
                error = response.error
                raise RuntimeError(f"Response failed: {error}")
            elif status == "cancelled":
                raise RuntimeError("Response was cancelled")
            
            time.sleep(poll_interval)
    
    def _build_result(self, task: Dict[str, Any], response: Any) -> Dict[str, Any]:
        """Build standardized result from API response."""
        # Extract final answer
        final_answer = ""
        final_message = None
        
        for item in response.output:
            if item.type == "message" and item.role == "assistant":
                final_message = item
        
        if final_message and final_message.content:
            final_answer = final_message.content[0].text
        
        # Extract trajectory
        trajectory = self._extract_trajectory(response)
        
        # Build result
        result = {
            "agent_type": "openai_deep_research",
            "task_name": task.get("task_name", "unknown"),
            "instruction": task.get("instruction", ""),
            "status": "success" if response.status == "completed" else "failed",
            "answer": final_answer,
            "trajectory": trajectory,
            "execution_time": 0.0,  # Will be set by @measure_execution_time
            "metadata": {
                "model": response.model,
                "response_id": response.id,
                "usage": {
                    "input_tokens": response.usage.input_tokens if response.usage else 0,
                    "output_tokens": response.usage.output_tokens if response.usage else 0,
                    "total_tokens": response.usage.total_tokens if response.usage else 0
                }
            }
        }
        
        # Add task_result for compatibility
        if final_answer:
            result["task_result"] = final_answer
        
        return result
    
    def _extract_trajectory(self, response: Any) -> Dict[str, Any]:
        """Extract trajectory from response output."""
        trajectory = {
            "steps": [],
            "summary": {},
            "final_answer": {}
        }
        
        web_search_count = 0
        code_count = 0
        file_search_count = 0
        mcp_count = 0
        
        for item in response.output:
            step = {
                "type": item.type,
                "id": getattr(item, "id", None)
            }
            
            if item.type == "web_search_call":
                web_search_count += 1
                step["status"] = getattr(item, "status", None)
                
                # Fix: Correctly access action attribute (may be dict or object)
                if hasattr(item, "action"):
                    action = item.action
                    if isinstance(action, dict):
                        step["action"] = {
                            "type": action.get("type"),
                            "query": action.get("query")
                        }
                    else:
                        # action is an object, use getattr
                        # Try multiple possible attribute names
                        action_type = getattr(action, "type", None) or getattr(action, "action_type", None)
                        action_query = getattr(action, "query", None) or getattr(action, "search", None)
                        
                        # If still None, try accessing as dict-like
                        if action_query is None and hasattr(action, "__dict__"):
                            action_dict = action.__dict__
                            action_query = action_dict.get("query") or action_dict.get("search")
                            action_type = action_dict.get("type") or action_dict.get("action_type")
                        
                        step["action"] = {
                            "type": action_type,
                            "query": action_query
                        }
                else:
                    step["action"] = {"type": None, "query": None}
                
                # Add sources if available (from include parameter)
                if hasattr(item, "sources"):
                    step["sources"] = item.sources
            
            elif item.type == "code_interpreter_call":
                code_count += 1
                step["status"] = getattr(item, "status", None)
                
                # According to docs, code_interpreter_call should have input and output
                # Try direct attribute access first
                step["input"] = getattr(item, "input", None)
                step["output"] = getattr(item, "output", None)
                
                # If None, try accessing via different attribute names or methods
                if step["input"] is None:
                    # Try alternative attribute names
                    step["input"] = (
                        getattr(item, "code", None) or
                        getattr(item, "code_input", None) or
                        getattr(item, "input_code", None)
                    )
                
                if step["output"] is None:
                    # Try alternative attribute names
                    step["output"] = (
                        getattr(item, "result", None) or
                        getattr(item, "code_output", None) or
                        getattr(item, "output_result", None)
                    )
                
                # Try accessing via __dict__ if still None
                if (step["input"] is None or step["output"] is None) and hasattr(item, "__dict__"):
                    item_dict = item.__dict__
                    if step["input"] is None:
                        step["input"] = (
                            item_dict.get("input") or
                            item_dict.get("code") or
                            item_dict.get("code_input")
                        )
                    if step["output"] is None:
                        step["output"] = (
                            item_dict.get("output") or
                            item_dict.get("result") or
                            item_dict.get("code_output")
                        )
                
                # Access outputs (requires include parameter)
                # outputs is a list of output items from code execution
                if hasattr(item, "outputs") and item.outputs is not None:
                    # outputs is a list, convert to a more readable format
                    outputs_list = []
                    for out in item.outputs:
                        if hasattr(out, "type"):
                            out_dict = {"type": out.type}
                            if hasattr(out, "text"):
                                out_dict["text"] = out.text
                            if hasattr(out, "image"):
                                out_dict["image"] = getattr(out.image, "file_id", None) if hasattr(out, "image") else None
                            if hasattr(out, "log"):
                                out_dict["log"] = out.log
                            outputs_list.append(out_dict)
                        elif isinstance(out, dict):
                            outputs_list.append(out)
                        else:
                            # Try to convert to dict if possible
                            try:
                                if hasattr(out, "__dict__"):
                                    outputs_list.append(out.__dict__)
                                else:
                                    outputs_list.append(str(out))
                            except:
                                outputs_list.append(str(out))
                    step["outputs"] = outputs_list if outputs_list else None
                else:
                    step["outputs"] = None
                
                # Try to extract output from outputs if output is None
                # Sometimes API only returns outputs array, not single output field
                if step["output"] is None and step["outputs"]:
                    # Extract text output from outputs array
                    text_outputs = []
                    for out in step["outputs"]:
                        if isinstance(out, dict):
                            if out.get("type") == "text" and "text" in out:
                                text_outputs.append(out["text"])
                            elif "text" in out:
                                text_outputs.append(out["text"])
                            elif "log" in out:
                                text_outputs.append(str(out["log"]))
                        elif hasattr(out, "text"):
                            text_outputs.append(out.text)
                        elif hasattr(out, "log"):
                            text_outputs.append(str(out.log))
                    if text_outputs:
                        step["output"] = "\n".join(text_outputs)
                
                # If still no output, check if there's a result or error field
                if step["output"] is None:
                    # Try to get error or result message
                    error_msg = getattr(item, "error", None)
                    if error_msg:
                        step["output"] = f"Error: {error_msg}"
                    else:
                        # Check for result field
                        result = getattr(item, "result", None)
                        if result:
                            step["output"] = str(result)
            
            elif item.type == "file_search_call":
                file_search_count += 1
                step["status"] = getattr(item, "status", None)
                step["queries"] = getattr(item, "queries", [])
                if hasattr(item, "results"):
                    step["results"] = item.results
            
            elif item.type == "mcp_call":
                mcp_count += 1
                step["name"] = getattr(item, "name", None)
                step["server_label"] = getattr(item, "server_label", None)
                step["arguments"] = getattr(item, "arguments", None)
                step["status"] = getattr(item, "status", None)
            
            elif item.type == "reasoning":
                summaries = []
                if hasattr(item, "summary") and item.summary:
                    summaries = [s.text for s in item.summary]
                step["summary"] = summaries
            
            elif item.type == "message":
                step["role"] = getattr(item, "role", None)
                step["status"] = getattr(item, "status", None)
                
                if hasattr(item, "content") and item.content:
                    content = item.content[0]
                    text = getattr(content, "text", "")
                    annotations = getattr(content, "annotations", [])
                    
                    step["content"] = {
                        "text": text,
                        "annotations": [
                            {
                                "type": getattr(ann, "type", None),
                                "title": getattr(ann, "title", None),
                                "url": getattr(ann, "url", None),
                                "start_index": getattr(ann, "start_index", None),
                                "end_index": getattr(ann, "end_index", None)
                            }
                            for ann in annotations
                        ]
                    }
                    
                    # Store final answer
                    if item.role == "assistant":
                        trajectory["final_answer"] = {
                            "text": text,
                            "citations": step["content"]["annotations"]
                        }
            
            trajectory["steps"].append(step)
        
        # Add summary statistics
        trajectory["summary"] = {
            "total_steps": len(trajectory["steps"]),
            "web_search_calls": web_search_count,
            "code_interpreter_calls": code_count,
            "file_search_calls": file_search_count,
            "mcp_calls": mcp_count
        }
        
        return trajectory
    
    def run_eval(self, task: Dict[str, Any], result: Dict[str, Any]) -> Dict[str, Any]:
        """Run evaluation using test.py file."""
        test_file_path = task.get("test_file_path")
        task_name = task.get("task_name", "unknown")
        use_encrypted = task.get("use_encrypted", False)
        
        if not test_file_path:
            logger.debug(f"No test file for task '{task_name}'")
            return None
        
        logger.info(f"Running test for task '{task_name}' with test file {test_file_path} (encrypted: {use_encrypted})")
        
        try:
            test_file = Path(test_file_path)
            if not test_file.exists():
                logger.warning(f"Test file {test_file_path} does not exist")
                return None
            
            if use_encrypted:
                if not DECRYPT_AVAILABLE:
                    raise ImportError("decrypt_utils not available but use_encrypted=True")
                
                task_dir = Path(task.get("task_dir"))
                canary = read_canary(task_dir)
                if canary is None:
                    raise ValueError(f"No canary.txt found in {task_dir}")
                
                test_code = decrypt_file_to_memory(test_file, canary)
                module = type(sys)("test")
                module.__file__ = str(test_file)
                sys.modules["test"] = module
                compiled_code = compile(test_code, str(test_file), 'exec')
                exec(compiled_code, module.__dict__)
                logger.debug(f"Test module loaded from encrypted file")
            else:
                spec = importlib.util.spec_from_file_location("test", test_file)
                module = importlib.util.module_from_spec(spec)
                sys.modules["test"] = module
                spec.loader.exec_module(module)
                logger.debug(f"Test module loaded from {test_file_path}")
            
            if hasattr(module, "test"):
                test_result = module.test(result)
                logger.info(f"Test result: {test_result}")
                return test_result
            else:
                logger.warning(f"No test() function found in {test_file_path}")
                return None
                
        except Exception as e:
            logger.error(f"Failed to run evaluation: {e}")
            return None
    
    def cleanup_environment(self) -> None:
        """Cleanup uploaded files and vector store."""
        # Delete vector store
        if self.vector_store_id:
            try:
                self.client.beta.vector_stores.delete(self.vector_store_id)
                logger.info(f"Deleted vector store: {self.vector_store_id}")
            except Exception as e:
                logger.warning(f"Failed to delete vector store: {e}")
        
        # Delete uploaded files
        for file_id in self.uploaded_file_ids:
            try:
                self.client.files.delete(file_id)
                logger.debug(f"Deleted file: {file_id}")
            except Exception as e:
                logger.warning(f"Failed to delete file {file_id}: {e}")
        
        self.vector_store_id = None
        self.uploaded_file_ids = []

