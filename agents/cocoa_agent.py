"""
Cocoa Agent implementation (wrapper around existing TaskExecutor).
"""

from typing import Dict, Any
from .base import BaseAgent
from executor import TaskExecutor


class CocoaAgent(BaseAgent):
    """Cocoa Agent using the existing TaskExecutor."""
    
    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)
        self.executor = TaskExecutor(config)
    
    def setup_environment(self, task: Dict[str, Any]) -> None:
        """Setup Docker sandbox environment."""
        self.executor.setup_environment(task)
    
    def run_task(self, task: Dict[str, Any]) -> Dict[str, Any]:
        """Execute task using TaskExecutor."""
        result = self.executor.run_task(task)
        result["agent_type"] = "cocoa"
        
        # Extract answer from task_result if available
        if "task_result" in result:
            result["answer"] = result["task_result"]
        else:
            result["answer"] = ""
        
        # Map execution_trace to trajectory
        result["trajectory"] = {
            "conversation": result.get("conversation", []),
            "execution_trace": result.get("execution_trace", []),
            "visualization_data": result.get("visualization_data", {})
        }
        
        return result
    
    def run_eval(self, task: Dict[str, Any], result: Dict[str, Any]) -> Dict[str, Any]:
        """Run evaluation using TaskExecutor."""
        return self.executor.run_eval(task, result)
    
    def cleanup_environment(self) -> None:
        """Cleanup Docker sandbox."""
        self.executor.cleanup_environment()

