"""
Tool definitions for browser actions.
"""

from typing import Dict, List, Any


def get_browser_tools() -> List[Dict[str, Any]]:
    """Get OpenAI tool definitions for browser actions.
    
    Returns:
        List of tool definitions in OpenAI format
    """
    tools = [
        {
            "type": "function",
            "function": {
                "name": "browser_click",
                "description": "Click at a specific position on the screen or at the current cursor position",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "x": {
                            "type": "number",
                            "description": "X coordinate to click (optional, if not provided clicks at current position)"
                        },
                        "y": {
                            "type": "number",
                            "description": "Y coordinate to click (optional, if not provided clicks at current position)"
                        },
                        "button": {
                            "type": "string",
                            "enum": ["left", "right", "middle"],
                            "default": "left",
                            "description": "Mouse button to click"
                        },
                        "num_clicks": {
                            "type": "integer",
                            "enum": [1, 2, 3],
                            "default": 1,
                            "description": "Number of clicks"
                        }
                    }
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "browser_type",
                "description": "Type text into the currently focused element",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "text": {
                            "type": "string",
                            "description": "Text to type"
                        },
                        "use_clipboard": {
                            "type": "boolean",
                            "default": True,
                            "description": "Use clipboard for better character support"
                        }
                    },
                    "required": ["text"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "browser_press",
                "description": "Press a keyboard key",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "key": {
                            "type": "string",
                            "description": "Key to press (e.g., 'Enter', 'Tab', 'Escape', 'ArrowDown', etc.)"
                        }
                    },
                    "required": ["key"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "browser_scroll",
                "description": "Scroll the page",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "dx": {
                            "type": "integer",
                            "default": 0,
                            "description": "Horizontal scroll amount in pixels"
                        },
                        "dy": {
                            "type": "integer",
                            "default": 0,
                            "description": "Vertical scroll amount in pixels (positive = down, negative = up)"
                        }
                    }
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "browser_move_to",
                "description": "Move the mouse cursor to a specific position",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "x": {
                            "type": "number",
                            "description": "Target X coordinate"
                        },
                        "y": {
                            "type": "number",
                            "description": "Target Y coordinate"
                        }
                    },
                    "required": ["x", "y"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "browser_move_rel",
                "description": "Move the mouse cursor relative to current position",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "x_offset": {
                            "type": "number",
                            "description": "Relative X offset from current position"
                        },
                        "y_offset": {
                            "type": "number",
                            "description": "Relative Y offset from current position"
                        }
                    },
                    "required": ["x_offset", "y_offset"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "browser_drag_to",
                "description": "Drag from current position to target coordinates",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "x": {
                            "type": "number",
                            "description": "Target X coordinate to drag to"
                        },
                        "y": {
                            "type": "number",
                            "description": "Target Y coordinate to drag to"
                        }
                    },
                    "required": ["x", "y"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "browser_drag_rel",
                "description": "Drag relative to current mouse position",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "x_offset": {
                            "type": "number",
                            "description": "Relative X offset for drag"
                        },
                        "y_offset": {
                            "type": "number",
                            "description": "Relative Y offset for drag"
                        }
                    },
                    "required": ["x_offset", "y_offset"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "browser_hotkey",
                "description": "Press a keyboard hotkey combination",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "keys": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Array of keys to press together (e.g., ['ctrl', 'c'])"
                        }
                    },
                    "required": ["keys"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "browser_key_down",
                "description": "Press down a keyboard key (without releasing)",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "key": {
                            "type": "string",
                            "description": "Key to press down"
                        }
                    },
                    "required": ["key"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "browser_key_up",
                "description": "Release a keyboard key",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "key": {
                            "type": "string",
                            "description": "Key to release"
                        }
                    },
                    "required": ["key"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "browser_wait",
                "description": "Wait for a specified duration",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "duration": {
                            "type": "number",
                            "description": "Duration to wait in seconds"
                        }
                    },
                    "required": ["duration"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "browser_screenshot",
                "description": "Take a screenshot of the current browser display",
                "parameters": {
                    "type": "object",
                    "properties": {}
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "browser_get_viewport_info",
                "description": "Get current browser viewport information (URL and viewport dimensions). Useful for verifying page state after on-screen actions.",
                "parameters": {
                    "type": "object",
                    "properties": {}
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "browser_navigate",
                "description": "Navigate the browser to a URL (DOM load).",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "url": {
                            "type": "string",
                            "description": "Destination URL to open"
                        }
                    },
                    "required": ["url"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "dom_get_text",
                "description": "Get page text (innerText of body) via DOM, no vision required. Truncates long output.",
                "parameters": {
                    "type": "object",
                    "properties": {}
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "dom_get_html",
                "description": "Get full page HTML via DOM (truncated if long).",
                "parameters": {
                    "type": "object",
                    "properties": {}
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "dom_query_selector",
                "description": "Query elements with a CSS selector and return detailed info: tag, id, class, name, type, href, aria-label, role, text. Use this to identify precise selectors before clicking.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "selector": {
                            "type": "string",
                            "description": "CSS selector to query"
                        },
                        "limit": {
                            "type": "integer",
                            "description": "Maximum elements to return (default 20)"
                        }
                    },
                    "required": ["selector"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "dom_extract_links",
                "description": "Extract hyperlinks (text + href) from the current page, optionally filtered.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "filter_pattern": {
                            "type": "string",
                            "description": "Optional substring to filter links by href or text"
                        },
                        "limit": {
                            "type": "integer",
                            "description": "Maximum links to return (default 50)"
                        }
                    }
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "dom_mark_elements",
                "description": "Mark all interactive elements on the page with unique BIDs (Browser IDentifiers) and return a list of all marked elements with their attributes. This provides a structured view of what elements can be interacted with. Use this before DOM operations to see what elements are available.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "max_elements": {
                            "type": "integer",
                            "description": "Maximum number of elements to mark and return (default 100)"
                        }
                    }
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "dom_click",
                "description": "Click an element by its BID (Browser IDentifier). The BID must be obtained first using dom_mark_elements. This uses direct element references for reliable interaction.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "bid": {
                            "type": "string",
                            "description": "BID of the element to click (e.g., 'bid1', 'bid2')"
                        },
                        "button": {
                            "type": "string",
                            "enum": ["left", "right", "middle"],
                            "description": "Mouse button to use (default left)"
                        },
                        "click_count": {
                            "type": "integer",
                            "enum": [1, 2],
                            "description": "Number of clicks (1=click, 2=double click)"
                        },
                        "timeout_ms": {
                            "type": "integer",
                            "description": "Timeout in milliseconds (default 2000)"
                        }
                    },
                    "required": ["bid"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "dom_hover",
                "description": "Hover over an element by its BID (Browser IDentifier). The BID must be obtained first using dom_mark_elements.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "bid": {
                            "type": "string",
                            "description": "BID of the element to hover over (e.g., 'bid1', 'bid2')"
                        },
                        "timeout_ms": {
                            "type": "integer",
                            "description": "Timeout in milliseconds (default 2000)"
                        }
                    },
                    "required": ["bid"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "dom_type",
                "description": "Type text into an element by its BID (Browser IDentifier). The BID must be obtained first using dom_mark_elements. Useful for filling input fields.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "bid": {
                            "type": "string",
                            "description": "BID of the element to type into (e.g., 'bid1', 'bid2')"
                        },
                        "text": {
                            "type": "string",
                            "description": "Text to type into the element"
                        },
                        "clear_first": {
                            "type": "boolean",
                            "description": "Whether to clear the element's value before typing (default true)"
                        },
                        "timeout_ms": {
                            "type": "integer",
                            "description": "Timeout in milliseconds (default 2000)"
                        }
                    },
                    "required": ["bid", "text"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "dom_press",
                "description": "Press a key on an element by its BID (Browser IDentifier) or on the page. The BID must be obtained first using dom_mark_elements. Useful for submitting forms, navigating, etc.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "key": {
                            "type": "string",
                            "description": "Key to press (e.g., 'Enter', 'Tab', 'Escape', 'ArrowDown')"
                        },
                        "bid": {
                            "type": "string",
                            "description": "Optional BID of the element to press key on. If not provided, key is pressed on the page."
                        },
                        "timeout_ms": {
                            "type": "integer",
                            "description": "Timeout in milliseconds (default 2000)"
                        }
                    },
                    "required": ["key"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "dom_scroll",
                "description": "Scroll an element by its BID (Browser IDentifier) or scroll the page. The BID must be obtained first using dom_mark_elements. Returns scroll position information including whether at top/bottom/left/right.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "bid": {
                            "type": "string",
                            "description": "Optional BID of the element to scroll. If not provided, scrolls the page."
                        },
                        "direction": {
                            "type": "string",
                            "enum": ["up", "down", "left", "right"],
                            "description": "Direction to scroll (default 'down')"
                        },
                        "amount": {
                            "type": "integer",
                            "description": "Amount to scroll in pixels (default 500)"
                        },
                        "timeout_ms": {
                            "type": "integer",
                            "description": "Timeout in milliseconds (default 2000)"
                        }
                    }
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "task_complete",
                "description": "Mark the task as complete and exit. Optionally provide the final result/answer if the task requires returning a specific output (e.g., JSON answer). For tasks that generate files in the sandbox, you can omit the result parameter.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "result": {
                            "type": "string",
                            "description": "Optional: The final result or answer for the task (e.g., JSON string). Use this when the task requires returning a specific output. For tasks that generate files, omit this parameter."
                        }
                    }
                }
            }
        }
    ]
    
    return tools


def get_file_tools() -> List[Dict[str, Any]]:
    """Get OpenAI tool definitions for file operations.
    
    Returns:
        List of tool definitions in OpenAI format
    """
    tools = [
        {
            "type": "function",
            "function": {
                "name": "file_read",
                "description": "Read file contents",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "path": {
                            "type": "string",
                            "description": "Absolute path to the file to read"
                        }
                    },
                    "required": ["path"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "file_write",
                "description": "Write content to a file",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "path": {
                            "type": "string",
                            "description": "Absolute path to the file to write"
                        },
                        "content": {
                            "type": "string",
                            "description": "Content to write to the file"
                        }
                    },
                    "required": ["path", "content"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "file_list",
                "description": "List files in a directory",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "path": {
                            "type": "string",
                            "description": "Absolute path to the directory to list"
                        }
                    },
                    "required": ["path"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "replace_in_file",
                "description": "Replace text in a file",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "file": {
                            "type": "string",
                            "description": "Absolute path to the file"
                        },
                        "old_text": {
                            "type": "string",
                            "description": "Text to replace (will be converted to old_str for API)"
                        },
                        "new_text": {
                            "type": "string",
                            "description": "Replacement text (will be converted to new_str for API)"
                        }
                    },
                    "required": ["file", "old_text", "new_text"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "search_in_file",
                "description": "Search for text in a file using regex pattern",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "file": {
                            "type": "string",
                            "description": "Absolute path to the file"
                        },
                        "pattern": {
                            "type": "string",
                            "description": "Regular expression pattern to search for (will be converted to regex for API)"
                        }
                    },
                    "required": ["file", "pattern"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "find_files",
                "description": "Find files matching a glob pattern",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "path": {
                            "type": "string",
                            "description": "Directory path to search in"
                        },
                        "glob": {
                            "type": "string",
                            "description": "Glob pattern (e.g., '*.py', '**/*.txt')"
                        }
                    },
                    "required": ["path", "glob"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "image_read",
                "description": "Read an image file (PNG, JPG, etc.) and return it as base64-encoded image for visual analysis. Use this to read visualization files generated by code (e.g., matplotlib plots, saved figures). The image will be automatically included in subsequent prompts for analysis.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "path": {
                            "type": "string",
                            "description": "Absolute path to the image file to read (supports PNG, JPG, JPEG formats)"
                        }
                    },
                    "required": ["path"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "str_replace_editor",
                "description": "Advanced file editor with view, create, str_replace, insert, undo_edit commands",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "command": {
                            "type": "string",
                            "enum": ["view", "create", "str_replace", "insert", "undo_edit"],
                            "description": "Editor command to execute"
                        },
                        "path": {
                            "type": "string",
                            "description": "Absolute path to file or directory"
                        },
                        "file_text": {
                            "type": "string",
                            "description": "File content for 'create' command"
                        },
                        "old_str": {
                            "type": "string",
                            "description": "String to replace for 'str_replace' command"
                        },
                        "new_str": {
                            "type": "string",
                            "description": "New string for 'str_replace' or 'insert' command"
                        },
                        "insert_line": {
                            "type": "integer",
                            "description": "Line number for 'insert' command"
                        },
                        "view_range": {
                            "type": "array",
                            "items": {"type": "integer"},
                            "description": "Line range for 'view' command [start, end]"
                        }
                    },
                    "required": ["command", "path"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "task_complete",
                "description": "Mark the task as complete and exit. Optionally provide the final result/answer if the task requires returning a specific output (e.g., JSON answer). For tasks that generate files in the sandbox, you can omit the result parameter.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "result": {
                            "type": "string",
                            "description": "Optional: The final result or answer for the task (e.g., JSON string). Use this when the task requires returning a specific output. For tasks that generate files, omit this parameter."
                        }
                    }
                }
            }
        }
    ]
    
    return tools


def get_code_tools() -> List[Dict[str, Any]]:
    """Get OpenAI tool definitions for code execution.
    
    Returns:
        List of tool definitions in OpenAI format
    """
    tools = [
        {
            "type": "function",
            "function": {
                "name": "code_execute",
                "description": "Execute code via sandbox runtime (python default). Returns stdout/stderr.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "code": {
                            "type": "string",
                            "description": "Source code to execute"
                        },
                        "language": {
                            "type": "string",
                            "enum": ["python", "javascript"],
                            "description": "Runtime language (default python)"
                        },
                        "timeout": {
                            "type": "integer",
                            "description": "Optional timeout in seconds"
                        }
                    },
                    "required": ["code"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "task_complete",
                "description": "Mark the task as complete and exit. Optionally provide the final result/answer if the task requires returning a specific output (e.g., JSON answer). For tasks that generate files in the sandbox, you can omit the result parameter.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "result": {
                            "type": "string",
                            "description": "Optional: The final result or answer for the task (e.g., JSON string). Use this when the task requires returning a specific output. For tasks that generate files, omit this parameter."
                        }
                    }
                }
            }
        }
    ]
    
    return tools


def get_shell_tools() -> List[Dict[str, Any]]:
    """Get OpenAI tool definitions for shell operations.
    
    Returns:
        List of tool definitions in OpenAI format
    """
    tools = [
        {
            "type": "function",
            "function": {
                "name": "shell_execute",
                "description": "Execute a shell command and get the output",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "command": {
                            "type": "string",
                            "description": "Shell command to execute"
                        }
                    },
                    "required": ["command"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "task_complete",
                "description": "Mark the task as complete and exit. Optionally provide the final result/answer if the task requires returning a specific output (e.g., JSON answer). For tasks that generate files in the sandbox, you can omit the result parameter.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "result": {
                            "type": "string",
                            "description": "Optional: The final result or answer for the task (e.g., JSON string). Use this when the task requires returning a specific output. For tasks that generate files, omit this parameter."
                        }
                    }
                }
            }
        }
    ]
    
    return tools


def get_unified_tools() -> List[Dict[str, Any]]:
    """Get unified OpenAI tool definitions combining all sandbox capabilities.
    
    Returns:
        List of tool definitions in OpenAI format combining browser, file, code, and shell tools
    """
    # Get all tool sets
    browser_tools = get_browser_tools()
    file_tools = get_file_tools()
    code_tools = get_code_tools()
    shell_tools = get_shell_tools()
    
    # Combine all tools, removing duplicate task_complete
    all_tools = []
    task_complete_added = False
    
    for tool_set in [browser_tools, file_tools, code_tools, shell_tools]:
        for tool in tool_set:
            tool_name = tool["function"]["name"]
            if tool_name == "task_complete":
                if not task_complete_added:
                    all_tools.append(tool)
                    task_complete_added = True
            else:
                all_tools.append(tool)
    
    return all_tools


def map_tool_call_to_action(tool_name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
    """Map a tool call to a sandbox action.
    
    Args:
        tool_name: Name of the tool being called
        arguments: Tool arguments
        
    Returns:
        Action dictionary for the sandbox client
        
    Raises:
        ValueError: If invalid parameters are provided for a tool
    """
    # Define valid parameters for each tool (to catch invalid parameters early)
    tool_valid_params = {
        "browser_click": {"x", "y", "button", "num_clicks"},
        "browser_type": {"text", "use_clipboard"},
        "browser_press": {"key"},
        "browser_scroll": {"dx", "dy"},
        "browser_move_to": {"x", "y"},
        "browser_move_rel": {"x_offset", "y_offset"},
        "browser_drag_to": {"x", "y"},
        "browser_drag_rel": {"x_offset", "y_offset"},
        "browser_hotkey": {"keys"},
        "browser_key_down": {"key"},
        "browser_key_up": {"key"},
        "browser_wait": {"duration"},
        "browser_screenshot": set(),
        "browser_get_viewport_info": set(),
        "browser_navigate": {"url"},
        "dom_get_text": set(),
        "dom_get_html": set(),
        "dom_query_selector": {"selector", "limit"},
        "dom_extract_links": {"filter_pattern", "limit"},
        "dom_mark_elements": {"max_elements"},
        "dom_click": {"bid", "button", "click_count", "timeout_ms"},
        "dom_hover": {"bid", "timeout_ms"},
        "dom_type": {"bid", "text", "clear_first", "timeout_ms"},
        "dom_press": {"key", "bid", "timeout_ms"},
        "dom_scroll": {"bid", "direction", "amount", "timeout_ms"},
        "file_read": {"path"},
        "file_write": {"path", "content"},
        "file_list": {"path"},
        "replace_in_file": {"file", "old_text", "new_text"},
        "search_in_file": {"file", "pattern"},
        "find_files": {"path", "glob"},
        "image_read": {"path"},
        "str_replace_editor": {"command", "path", "file_text", "old_str", "new_str", "insert_line", "view_range"},
        "code_execute": {"code", "language", "timeout"},
        "shell_execute": {"command"},
        "task_complete": {"result"},
    }
    
    # Validate parameters if tool is in the validation map
    if tool_name in tool_valid_params:
        valid_params = tool_valid_params[tool_name]
        invalid_params = set(arguments.keys()) - valid_params
        if invalid_params:
            raise ValueError(
                f"Tool '{tool_name}' does not support parameters: {invalid_params}. "
                f"Valid parameters are: {valid_params}. "
                f"Received: {list(arguments.keys())}"
            )
        # Filter to only valid parameters (in case of typos or extra params)
        arguments = {k: v for k, v in arguments.items() if k in valid_params}
    
    # Validate that tool_name is known
    valid_tools = set(tool_valid_params.keys())
    if tool_name not in valid_tools:
        raise ValueError(f"Unknown tool: {tool_name}")
    
    # Build action with tool name as action_type (no mapping needed)
    action = {"action_type": tool_name}
    action.update(arguments)
    
    return action

