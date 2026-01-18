"""
Base agent interface.
"""

from abc import ABC, abstractmethod
from typing import Dict, Any


class BaseAgent(ABC):
    """Abstract base class for all agents."""
    
    def __init__(self, config: Dict[str, Any]):
        """Initialize agent with configuration.
        
        Args:
            config: Configuration dictionary
        """
        self.config = config
    
    def setup_environment(self, task: Dict[str, Any]) -> None:
        """Setup environment for task execution (optional).
        
        Args:
            task: Task dictionary
        """
        pass
    
    @abstractmethod
    def run_task(self, task: Dict[str, Any]) -> Dict[str, Any]:
        """Execute task and return results.
        
        Args:
            task: Task dictionary with 'instruction' and other metadata
            
        Returns:
            Result dictionary with standardized format:
            {
                "agent_type": str,
                "task_name": str,
                "instruction": str,
                "status": "success" | "failed",
                "answer": str,
                "trajectory": dict,
                "execution_time": float,
                "metadata": dict
            }
        """
        raise NotImplementedError
    
    def run_eval(self, task: Dict[str, Any], result: Dict[str, Any]) -> Dict[str, Any]:
        """Run evaluation on task results (optional).
        
        Args:
            task: Task dictionary
            result: Result from run_task
            
        Returns:
            Evaluation result dictionary or None
        """
        return None
    
    def cleanup_environment(self) -> None:
        """Cleanup environment after execution (optional)."""
        pass

