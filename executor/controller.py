"""
Controller classes for generating actions/commands to solve programming tasks.

This module provides a base Controller class and implementations for:
- LLM: Uses OpenAI API to generate actions
- Human: Prompts user for manual input
"""

import os
import re
import json
import base64
from typing import Any, Dict, List
from openai import OpenAI
from .utils import get_logger, colorize
from .tools import get_browser_tools, get_unified_tools, map_tool_call_to_action

# Try to import Gemini libraries
try:
    from google import genai
    from google.genai import types
    GEMINI_AVAILABLE = True
except ImportError:
    GEMINI_AVAILABLE = False
    types = Any

# Try to import Anthropic libraries
try:
    import anthropic
    ANTHROPIC_AVAILABLE = True
except ImportError:
    ANTHROPIC_AVAILABLE = False
    anthropic = Any

logger = get_logger("llm")


def format_tools_as_text(tools: List[Dict[str, Any]]) -> str:
    """Convert OpenAI tool schema to text description for Qwen3-VL models.
    
    Args:
        tools: List of tool definitions in OpenAI format
        
    Returns:
        Formatted text description of all tools
    """
    tool_descriptions = []
    
    for tool in tools:
        func = tool.get("function", {})
        name = func.get("name", "")
        description = func.get("description", "")
        parameters = func.get("parameters", {})
        properties = parameters.get("properties", {})
        required = parameters.get("required", [])
        
        # Build parameter descriptions
        param_descriptions = []
        for param_name, param_info in properties.items():
            param_type = param_info.get("type", "string")
            param_desc = param_info.get("description", "")
            param_enum = param_info.get("enum")
            param_default = param_info.get("default")
            
            param_str = f"  - {param_name} ({param_type})"
            if param_desc:
                param_str += f": {param_desc}"
            if param_enum:
                param_str += f" [options: {', '.join(map(str, param_enum))}]"
            if param_default is not None:
                param_str += f" [default: {param_default}]"
            if param_name in required:
                param_str += " [required]"
            
            param_descriptions.append(param_str)
        
        # Format tool description
        tool_text = f"- {name}: {description}"
        if param_descriptions:
            tool_text += "\n" + "\n".join(param_descriptions)
        
        tool_descriptions.append(tool_text)
    
    return "\n\n".join(tool_descriptions)


# Unified agent prompts
UNIFIED_INITIAL_PROMPT_TEMPLATE = """
You are a powerful AI agent with access to a comprehensive sandbox environment. You can control a web browser, execute shell commands, manipulate files, and run Python code to solve complex, multi-domain tasks.

Task:
{instruction}

## Available Tools

### Browser Tools

#### On-Screen Actions (Coordinate-based, require visual verification)
**Mouse Actions:**
- `browser_click(x, y, button?, num_clicks?)`: Click at coordinates (x, y) or current cursor position
  - `button`: "left" (default), "right", or "middle"
  - `num_clicks`: 1 (default), 2 (double-click), or 3
  - Use `button="right"` for right-click, `num_clicks=2` for double-click
- `browser_move_to(x, y)`: Move mouse cursor to absolute coordinates
- `browser_move_rel(dx, dy)`: Move mouse cursor relative to current position
- `browser_drag_to(x, y)`: Drag from current position to target coordinates
- `browser_drag_rel(dx, dy)`: Drag relative to current position (useful for scrolling: move to scrollbar, then drag)

**Keyboard Actions:**
- `browser_type(text, use_clipboard?)`: Type text into currently focused element
- `browser_press(key)`: Press a key (Enter, Tab, Escape, ArrowDown, PageDown, etc.)
- `browser_key_down(key)`: Press and hold a key
- `browser_key_up(key)`: Release a key
- `browser_hotkey(keys)`: Press key combination (e.g., ["ctrl", "c"])

**Misc:**
- `browser_wait(duration)`: Wait for specified duration in seconds
- `browser_screenshot()`: Capture current viewport (image) - CRITICAL for visual observation
- `browser_get_viewport_info()`: Get current URL and viewport dimensions (useful for verifying page state after on-screen actions)

**Navigation:**
- `browser_navigate(url)`: Navigate to a URL (DOM load)


#### DOM Actions (Selector-based, no vision required)

**Observation Actions:**
- `dom_get_text()`: Get page text (innerText of body, truncated if long)
- `dom_get_html()`: Get page HTML (truncated if long)
- `dom_query_selector(selector, limit?)`: List elements with detailed attributes (tag, id, class, name, type, href, aria-label, role, text). Use to identify precise selectors before clicking.
- `dom_extract_links(filter_pattern?, limit?)`: Extract links (text + href) optionally filtered by substring
- `dom_mark_elements(max_elements?)`: **[REQUIRED FIRST STEP]** Mark all interactive elements with unique BIDs and return structured list. Use this FIRST to get a comprehensive view of clickable/interactive elements with their attributes. Then use the BIDs with interaction actions below.

**DOM Interaction Actions (Use BIDs from dom_mark_elements):**
- `dom_click(bid, button?, click_count?, timeout_ms?)`: Click an element by its BID (obtained from dom_mark_elements)
- `dom_hover(bid, timeout_ms?)`: Hover over an element by its BID
- `dom_type(bid, text, clear_first?, timeout_ms?)`: Type text into an element by its BID
- `dom_press(key, bid?, timeout_ms?)`: Press a key on an element by its BID (or on the page if bid not provided)
- `dom_scroll(bid?, direction?, amount?, timeout_ms?)`: Scroll an element by its BID (or scroll the page if bid not provided). Returns scroll position info including whether at top/bottom/left/right.

**Note**: Always use `dom_mark_elements` first to get BIDs, then use DOM interaction actions. These are more reliable than on-screen actions and don't require visual verification.

### File Tools
- `file_read(path)`: Read file content
- `file_write(path, content)`: Write content to file
- `file_list(path)`: List files in directory
- `replace_in_file(file, old_text, new_text)`: Replace text in file
- `search_in_file(file, pattern)`: Search for pattern in file
- `find_files(path, glob)`: Find files matching glob pattern
- `image_read(path)`: Read image files (PNG, JPG, etc.) and return as base64-encoded images for visual analysis
- `str_replace_editor(command, path, ...)`: Powerful file editing with view/create/replace/insert/undo

**Note**: All file paths are relative to `/home/gem/` (the sandbox root directory).

### Code Execution Tools
- `code_execute(code, language?, timeout?)`: Run code via sandbox runtime (python default); returns stdout/stderr
- **Note**: Working directory is `/home/gem/`

### Shell Tools
- `shell_execute(command)`: Execute bash commands in the sandbox
- **Note**: Working directory is `/home/gem/`

### Task Management
- `task_complete(result?)`: Mark task as complete. **MUST** call this when finished.
  - If task requires returning a specific output, pass it as `result` parameter: `task_complete(result="your_answer")`
  - If task generates files or has no specific output, call `task_complete()` without parameters

## Tool-Specific Guidelines

### Browser Tools Guidelines

#### (a) Interaction Mode Selection
- **CRITICAL: ALWAYS prefer DOM operations over on-screen actions**
  - **First step**: Use `dom_mark_elements()` to get a list of all interactive elements with their BIDs
  - **Then use**: `dom_click(bid)`, `dom_type(bid, text)`, `dom_hover(bid)`, `dom_press(bid, key)`, `dom_scroll(bid, direction)` with the BIDs from `dom_mark_elements`
  - DOM operations are more reliable, faster, and don't require visual verification
  - **CRITICAL: BIDs are DYNAMIC and TEMPORARY**
    - BIDs are reassigned every time you run `dom_mark_elements()`
    - **NEVER reuse old BIDs** from previous `dom_mark_elements()` calls
    - If a click fails with "No element found with BID", the BID is stale - you MUST run `dom_mark_elements()` again to get fresh BIDs
    - After any page change (navigation, modal open/close, element state change), run `dom_mark_elements()` again
    - **DO NOT repeatedly click the same stale BID** - if it fails once, refresh BIDs immediately
  - **Only use on-screen actions** when:
    - DOM operations fail after multiple attempts
    - Target elements are not accessible via DOM (e.g., canvas, video controls, custom widgets)
    - You need to interact with non-DOM elements (tabs, browser back/forward buttons)

#### (a2) Handling Modals, Popups, and Close Buttons
- **When encountering popups/modals/dialogs:**
  1. **Always run `dom_mark_elements` immediately** to identify interactive elements in the modal
  2. **Look for close/dismiss buttons** - marked elements will include:
     - Elements with `aria-label` containing "close", "dismiss", "cancel"
     - Elements with `class` containing "close", "dismiss", "cancel"
     - Elements with text like "×", "✕", "X", "Close", "No thanks", "Dismiss"
     - Elements with `data-dismiss` or `data-close` attributes
     - SVG icons or small divs/spans with cursor:pointer
  3. **If modal blocks your target action:**
     - First close the modal using identified close button BID
     - Then run `dom_mark_elements` again to refresh BIDs for the underlying page
     - Continue with your original task
  4. **If close button is not in marked elements:**
     - The element marking may have missed it due to DOM structure
     - Try `browser_press("Escape")` to dismiss modal
     - If Escape fails, use `browser_screenshot` to locate close button visually
     - As last resort, use on-screen click on the close button coordinates
  5. **Common error patterns:**
     - **Clicking wrong element**: If you try to click something but keep clicking Overview/Specifications/Add to Cart instead of close button, it means the close button BID is missing. Run `dom_mark_elements` again and look for BIDs with class/aria-label/text indicating close/dismiss.
     - **Element removed after click**: If click feedback says "Element removed from DOM", this is GOOD - it means you successfully clicked a close/dismiss button that removed the modal.

#### (b) On-Screen Action Verification Protocol
**CRITICAL: Every on-screen action MUST be verified with screenshots**

1. **Before any on-screen action:**
   - Take `browser_screenshot()` to:
     - Locate target coordinates
     - Verify mouse cursor position (if using relative movements)
     - Confirm page state

2. **After any on-screen action:**
   - Take `browser_screenshot()` to verify:
     - Action executed correctly (e.g., clicked element changed state)
     - Page content changed as expected
     - No error dialogs appeared
   - Call `browser_get_viewport_info()` to verify:
     - URL changed (if navigation occurred)
     - Viewport dimensions (if relevant)

3. **Specific action requirements:**
   - **Before `browser_type` or `browser_press`**: 
     - MUST verify cursor/focus is on correct element via screenshot
     - Ensure target input field is visible and focused
   - **Before `browser_drag_to/rel` or scrolling**:
     - MUST verify scrollbar position via screenshot
     - Confirm drag start position is correct
   - **For `browser_click`**:
     - Verify target coordinates are correct via screenshot
     - Do NOT click same coordinates > 2 times unless state change occurred
   - **For all mouse movements**:
     - Verify final position via screenshot if critical

4. **State change verification:**
   - Compare screenshots before/after action
   - Treat action as successful ONLY if:
     - URL changed meaningfully, OR
     - Page content (screenshot) changed meaningfully
   - If no meaningful change, treat as failed and try different approach

#### (c) Failure Modes and Recovery

**DOM Operation Failures:**
- **Common causes:**
  - **Stale BID**: BID from previous `dom_mark_elements()` call is no longer valid (element was re-rendered, page changed, etc.)
  - Element removed from DOM after previous action
  - Element not yet loaded or visible
- **Recovery strategies:**
  - **If click/hover/type fails with "No element found with BID"**: 
    - **IMMEDIATELY run `dom_mark_elements()` again** to get fresh BIDs
    - **DO NOT retry the same stale BID** - it will never work
    - Find the target element in the new BID list and use the new BID
  - **If same BID fails > 1 time**: Stop retrying that BID, refresh BIDs immediately
  - **After page state changes** (modal opens/closes, navigation, element updates): Always run `dom_mark_elements()` again
  - **If element keeps disappearing**: The element may be dynamically recreated - use `dom_query_selector` to find it by attributes instead

**On-Screen Action Failures:**
- **Common causes:**
  - Mouse clicked wrong position (coordinates inaccurate)
  - Time gap between actions too long → mouse cursor disappeared (need to click anywhere to restore)
  - Target element moved/not loaded yet
- **Recovery strategies:**
  - If same coordinates fail > 2 times: Stop retrying, switch to DOM operations
  - If mouse disappeared: Click any visible element first to restore cursor
  - If wrong page loaded: Use `browser_navigate(url)` to return to previous page
  - After 6 consecutive browser actions without verified progress:
    - Stop automated attempts
    - Switch to DOM operations (e.g., use `dom_mark_elements` then `dom_click` with BID)
    - Or use `code_execute` to programmatically scrape/interact
    - Document attempts and request human input if needed

**Non-DOM Elements:**
- Some elements (tabs, browser back/forward, custom widgets) cannot be accessed via DOM operations
- These MUST use on-screen actions with careful coordinate verification

**Error Pages (404, maintenance, blocked):**
- If screenshot shows error page:
  - Do NOT try to find elements on error page
  - Use `browser_navigate(url)` to go to:
    - Previous valid page
    - Site root or known canonical entry
    - Alternative resource

**No Fabrication:**
- Never invent URLs, filenames, or data
- Never use placeholder domains (example.com) as actual inputs
- If required resource cannot be found, document:
  - What you searched
  - Screenshots/evidence
  - Why search failed

### Code & Shell Tools Guidelines
- **Working directory**: Always `/home/gem/`
- Use relative paths from `/home/gem/` or absolute paths starting with `/home/gem/`
- For file operations, remember root is `/home/gem/`

## Cross-Tool Workflow Guidelines

### Download Workflow
1. **Find download target via browser:**
   - Use `dom_query_selector` or `dom_extract_links` to find download links
   - Or use `browser_screenshot` + visual analysis to locate download button
   - Verify it's the correct file (e.g., PDF) via screenshot or DOM text

2. **Download file:**
   - **DO NOT** use on-screen clicks blindly
   - **PREFER**: Use `shell_execute` with wget/curl or `code_execute` to download programmatically:
     - Using shell: `shell_execute("wget -O /home/gem/file.pdf https://example.com/file.pdf")`
     - Using code:
       ```python
       import requests
       url = "https://example.com/file.pdf"
       response = requests.get(url)
       with open("/home/gem/file.pdf", "wb") as f:
           f.write(response.content)
       ```
   - Or use `dom_mark_elements` then `dom_click` with BID if download link is available

3. **Verify download:**
   - Use `file_list("/home/gem")` or `shell_execute("ls -lh /home/gem/file.pdf")` to verify file exists
   - Use `file_read` or `code_execute` to verify file content/parsability

### File Verification
- After saving any file, verify:
  - File exists: `file_list(path)` or `shell_execute("test -f /home/gem/path && echo exists")`
  - File size > 0: `shell_execute("stat -c%s /home/gem/path")`
  - For PDFs/documents: Parse via `code_execute` to confirm expected sections exist

### Using Code to Implement Missing Capabilities
- If needed operation not supported by tools:
  - Implement helper in `code_execute`
  - Verify output before using
  - Examples: advanced parsing, OCR, link discovery, data extraction

### Logging Progress
- Record milestones to `/home/gem/task_progress.txt`:
  - Brief notes on what was accomplished
  - Screenshot references used for decisions
  - File paths created/modified

### Failure Reporting
- If subtask cannot be completed after reasonable attempts:
  - Document: actions tried, screenshot references, why each failed
  - Suggest next steps or request human input
  - Include in `task_complete(result="failure_summary")` if task fails

## Critical Reminders

1. **ALWAYS use DOM operations first**: Start with `dom_mark_elements()`, then use `dom_click(bid)`, `dom_type(bid, text)`, etc.
2. **Only use on-screen actions** when DOM operations fail or are unavailable
3. **Always verify on-screen actions** with screenshots before and after (if you must use them)
4. **Remember working directory** is `/home/gem/` for all file/code/shell operations
5. **Download files programmatically** using `code_execute`, not blind clicks
6. **Verify all file operations** (existence, size, content)
7. **MUST call `task_complete`** when finished, with result if applicable
8. **No fabrication** - never invent URLs, filenames, or data
9. **Stop retrying** after 6 failed browser actions - switch strategy or request help
10. **Use `image_read` for images**: When you need to read or view a downloaded image, use the `image_read` tool. **DO NOT** use `code_execute` to display images (e.g., using matplotlib/PIL) because it produces large base64 outputs that exceed API length limits.
"""

UNIFIED_FEEDBACK_PROMPT_TEMPLATE = """
Your previous actions have been executed. Here is the feedback:

{feedback}

Based on the feedback and your progress toward the goal, determine the next actions to take. You can call multiple tools in sequence.

Remember:
- Analyze what has been accomplished and what remains
- Use the appropriate tools (browser, file, code, shell) for each subtask
- For downloading files: prefer `shell_execute` (wget/curl) or `code_execute` over on-screen clicks
- Verify results when necessary
- **CRITICAL**: When you have the final answer or result, you MUST call `task_complete` to finish the task
  - If the task requires returning a specific output (e.g., JSON answer, text answer), pass it as the 'result' parameter: `task_complete(result="your_answer")`
  - If the task generates files in the sandbox (no specific output required), call `task_complete()` without parameters
  - If the task failed after reasonable attempts, call `task_complete(result="failure_summary: ...")` with a summary of what was tried and why it failed
- Call `task_complete` when the entire task is finished - this is mandatory
"""


UNIFIED_INITIAL_PROMPT_TEMPLATE_QWEN3VL = """
You are a powerful AI agent with access to a comprehensive sandbox environment. You can control a web browser, execute shell commands, manipulate files, and run Python code to solve complex, multi-domain tasks.

Task:
{instruction}

{tools_description}

## Available Tools

### Browser Tools

#### On-Screen Actions (Coordinate-based, require visual verification)
**Mouse Actions:**
- `browser_click(x, y, button?, num_clicks?)`: Click at coordinates (x, y) or current cursor position
  - `button`: "left" (default), "right", or "middle"
  - `num_clicks`: 1 (default), 2 (double-click), or 3
  - Use `button="right"` for right-click, `num_clicks=2` for double-click
- `browser_move_to(x, y)`: Move mouse cursor to absolute coordinates
- `browser_move_rel(dx, dy)`: Move mouse cursor relative to current position
- `browser_drag_to(x, y)`: Drag from current position to target coordinates
- `browser_drag_rel(dx, dy)`: Drag relative to current position (useful for scrolling: move to scrollbar, then drag)

**Keyboard Actions:**
- `browser_type(text, use_clipboard?)`: Type text into currently focused element
- `browser_press(key)`: Press a key (Enter, Tab, Escape, ArrowDown, PageDown, etc.)
- `browser_key_down(key)`: Press and hold a key
- `browser_key_up(key)`: Release a key
- `browser_hotkey(keys)`: Press key combination (e.g., ["ctrl", "c"])

**Misc:**
- `browser_wait(duration)`: Wait for specified duration in seconds
- `browser_screenshot()`: Capture current viewport (image) - CRITICAL for visual observation
- `browser_get_viewport_info()`: Get current URL and viewport dimensions (useful for verifying page state after on-screen actions)

**Navigation:**
- `browser_navigate(url)`: Navigate to a URL (DOM load)


#### DOM Actions (Selector-based, no vision required)

**Observation Actions:**
- `dom_get_text()`: Get page text (innerText of body, truncated if long)
- `dom_get_html()`: Get page HTML (truncated if long)
- `dom_query_selector(selector, limit?)`: List elements with detailed attributes (tag, id, class, name, type, href, aria-label, role, text). Use to identify precise selectors before clicking.
- `dom_extract_links(filter_pattern?, limit?)`: Extract links (text + href) optionally filtered by substring
- `dom_mark_elements(max_elements?)`: **[REQUIRED FIRST STEP]** Mark all interactive elements with unique BIDs and return structured list. Use this FIRST to get a comprehensive view of clickable/interactive elements with their attributes. Then use the BIDs with interaction actions below.

**DOM Interaction Actions (Use BIDs from dom_mark_elements):**
- `dom_click(bid, button?, click_count?, timeout_ms?)`: Click an element by its BID (obtained from dom_mark_elements)
- `dom_hover(bid, timeout_ms?)`: Hover over an element by its BID
- `dom_type(bid, text, clear_first?, timeout_ms?)`: Type text into an element by its BID
- `dom_press(key, bid?, timeout_ms?)`: Press a key on an element by its BID (or on the page if bid not provided)
- `dom_scroll(bid?, direction?, amount?, timeout_ms?)`: Scroll an element by its BID (or scroll the page if bid not provided). Returns scroll position info including whether at top/bottom/left/right.

**Note**: Always use `dom_mark_elements` first to get BIDs, then use DOM interaction actions. These are more reliable than on-screen actions and don't require visual verification.

### File Tools
- `file_read(path)`: Read file content
- `file_write(path, content)`: Write content to file
- `file_list(path)`: List files in directory
- `replace_in_file(file, old_text, new_text)`: Replace text in file
- `search_in_file(file, pattern)`: Search for pattern in file
- `find_files(path, glob)`: Find files matching glob pattern
- `image_read(path)`: Read image files (PNG, JPG, etc.) and return as base64-encoded images for visual analysis
- `str_replace_editor(command, path, ...)`: Powerful file editing with view/create/replace/insert/undo

**Note**: All file paths are relative to `/home/gem/` (the sandbox root directory).

### Code Execution Tools
- `code_execute(code, language?, timeout?)`: Run code via sandbox runtime (python default); returns stdout/stderr
- **Note**: Working directory is `/home/gem/`

### Shell Tools
- `shell_execute(command)`: Execute bash commands in the sandbox
- **Note**: Working directory is `/home/gem/`

### Task Management
- `task_complete(result?)`: Mark task as complete. **MUST** call this when finished.
  - If task requires returning a specific output, pass it as `result` parameter: `task_complete(result="your_answer")`
  - If task generates files or has no specific output, call `task_complete()` without parameters

## Tool-Specific Guidelines

### Browser Tools Guidelines

#### (a) Interaction Mode Selection
- **CRITICAL: ALWAYS prefer DOM operations over on-screen actions**
  - **First step**: Use `dom_mark_elements()` to get a list of all interactive elements with their BIDs
  - **Then use**: `dom_click(bid)`, `dom_type(bid, text)`, `dom_hover(bid)`, `dom_press(bid, key)`, `dom_scroll(bid, direction)` with the BIDs from `dom_mark_elements`
  - DOM operations are more reliable, faster, and don't require visual verification
  - **CRITICAL: BIDs are DYNAMIC and TEMPORARY**
    - BIDs are reassigned every time you run `dom_mark_elements()`
    - **NEVER reuse old BIDs** from previous `dom_mark_elements()` calls
    - If a click fails with "No element found with BID", the BID is stale - you MUST run `dom_mark_elements()` again to get fresh BIDs
    - After any page change (navigation, modal open/close, element state change), run `dom_mark_elements()` again
    - **DO NOT repeatedly click the same stale BID** - if it fails once, refresh BIDs immediately
  - **Only use on-screen actions** when:
    - DOM operations fail after multiple attempts
    - Target elements are not accessible via DOM (e.g., canvas, video controls, custom widgets)
    - You need to interact with non-DOM elements (tabs, browser back/forward buttons)

#### (a2) Handling Modals, Popups, and Close Buttons
- **When encountering popups/modals/dialogs:**
  1. **Always run `dom_mark_elements` immediately** to identify interactive elements in the modal
  2. **Look for close/dismiss buttons** - marked elements will include:
     - Elements with `aria-label` containing "close", "dismiss", "cancel"
     - Elements with `class` containing "close", "dismiss", "cancel"
     - Elements with text like "×", "✕", "X", "Close", "No thanks", "Dismiss"
     - Elements with `data-dismiss` or `data-close` attributes
     - SVG icons or small divs/spans with cursor:pointer
  3. **If modal blocks your target action:**
     - First close the modal using identified close button BID
     - Then run `dom_mark_elements` again to refresh BIDs for the underlying page
     - Continue with your original task
  4. **If close button is not in marked elements:**
     - The element marking may have missed it due to DOM structure
     - Try `browser_press("Escape")` to dismiss modal
     - If Escape fails, use `browser_screenshot` to locate close button visually
     - As last resort, use on-screen click on the close button coordinates
  5. **Common error patterns:**
     - **Clicking wrong element**: If you try to click something but keep clicking Overview/Specifications/Add to Cart instead of close button, it means the close button BID is missing. Run `dom_mark_elements` again and look for BIDs with class/aria-label/text indicating close/dismiss.
     - **Element removed after click**: If click feedback says "Element removed from DOM", this is GOOD - it means you successfully clicked a close/dismiss button that removed the modal.

#### (b) On-Screen Action Verification Protocol
**CRITICAL: Every on-screen action MUST be verified with screenshots**

1. **Before any on-screen action:**
   - Take `browser_screenshot()` to:
     - Locate target coordinates
     - Verify mouse cursor position (if using relative movements)
     - Confirm page state

2. **After any on-screen action:**
   - Take `browser_screenshot()` to verify:
     - Action executed correctly (e.g., clicked element changed state)
     - Page content changed as expected
     - No error dialogs appeared
   - Call `browser_get_viewport_info()` to verify:
     - URL changed (if navigation occurred)
     - Viewport dimensions (if relevant)

3. **Specific action requirements:**
   - **Before `browser_type` or `browser_press`**: 
     - MUST verify cursor/focus is on correct element via screenshot
     - Ensure target input field is visible and focused
   - **Before `browser_drag_to/rel` or scrolling**:
     - MUST verify scrollbar position via screenshot
     - Confirm drag start position is correct
   - **For `browser_click`**:
     - Verify target coordinates are correct via screenshot
     - Do NOT click same coordinates > 2 times unless state change occurred
   - **For all mouse movements**:
     - Verify final position via screenshot if critical

4. **State change verification:**
   - Compare screenshots before/after action
   - Treat action as successful ONLY if:
     - URL changed meaningfully, OR
     - Page content (screenshot) changed meaningfully
   - If no meaningful change, treat as failed and try different approach

#### (c) Failure Modes and Recovery

**DOM Operation Failures:**
- **Common causes:**
  - **Stale BID**: BID from previous `dom_mark_elements()` call is no longer valid (element was re-rendered, page changed, etc.)
  - Element removed from DOM after previous action
  - Element not yet loaded or visible
- **Recovery strategies:**
  - **If click/hover/type fails with "No element found with BID"**: 
    - **IMMEDIATELY run `dom_mark_elements()` again** to get fresh BIDs
    - **DO NOT retry the same stale BID** - it will never work
    - Find the target element in the new BID list and use the new BID
  - **If same BID fails > 1 time**: Stop retrying that BID, refresh BIDs immediately
  - **After page state changes** (modal opens/closes, navigation, element updates): Always run `dom_mark_elements()` again
  - **If element keeps disappearing**: The element may be dynamically recreated - use `dom_query_selector` to find it by attributes instead

**On-Screen Action Failures:**
- **Common causes:**
  - Mouse clicked wrong position (coordinates inaccurate)
  - Time gap between actions too long → mouse cursor disappeared (need to click anywhere to restore)
  - Target element moved/not loaded yet
- **Recovery strategies:**
  - If same coordinates fail > 2 times: Stop retrying, switch to DOM operations
  - If mouse disappeared: Click any visible element first to restore cursor
  - If wrong page loaded: Use `browser_navigate(url)` to return to previous page
  - After 6 consecutive browser actions without verified progress:
    - Stop automated attempts
    - Switch to DOM operations (e.g., use `dom_mark_elements` then `dom_click` with BID)
    - Or use `code_execute` to programmatically scrape/interact
    - Document attempts and request human input if needed

**Non-DOM Elements:**
- Some elements (tabs, browser back/forward, custom widgets) cannot be accessed via DOM operations
- These MUST use on-screen actions with careful coordinate verification

**Error Pages (404, maintenance, blocked):**
- If screenshot shows error page:
  - Do NOT try to find elements on error page
  - Use `browser_navigate(url)` to go to:
    - Previous valid page
    - Site root or known canonical entry
    - Alternative resource

**No Fabrication:**
- Never invent URLs, filenames, or data
- Never use placeholder domains (example.com) as actual inputs
- If required resource cannot be found, document:
  - What you searched
  - Screenshots/evidence
  - Why search failed

### Code & Shell Tools Guidelines
- **Working directory**: Always `/home/gem/`
- Use relative paths from `/home/gem/` or absolute paths starting with `/home/gem/`
- For file operations, remember root is `/home/gem/`

## Cross-Tool Workflow Guidelines

### Download Workflow
1. **Find download target via browser:**
   - Use `dom_query_selector` or `dom_extract_links` to find download links
   - Or use `browser_screenshot` + visual analysis to locate download button
   - Verify it's the correct file (e.g., PDF) via screenshot or DOM text

2. **Download file:**
   - **DO NOT** use on-screen clicks blindly
   - **PREFER**: Use `shell_execute` with wget/curl or `code_execute` to download programmatically:
     - Using shell: `shell_execute("wget -O /home/gem/file.pdf https://example.com/file.pdf")`
     - Using code:
       ```python
       import requests
       url = "https://example.com/file.pdf"
       response = requests.get(url)
       with open("/home/gem/file.pdf", "wb") as f:
           f.write(response.content)
       ```
   - Or use `dom_mark_elements` then `dom_click` with BID if download link is available

3. **Verify download:**
   - Use `file_list("/home/gem")` or `shell_execute("ls -lh /home/gem/file.pdf")` to verify file exists
   - Use `file_read` or `code_execute` to verify file content/parsability

### File Verification
- After saving any file, verify:
  - File exists: `file_list(path)` or `shell_execute("test -f /home/gem/path && echo exists")`
  - File size > 0: `shell_execute("stat -c%s /home/gem/path")`
  - For PDFs/documents: Parse via `code_execute` to confirm expected sections exist

### Using Code to Implement Missing Capabilities
- If needed operation not supported by tools:
  - Implement helper in `code_execute`
  - Verify output before using
  - Examples: advanced parsing, OCR, link discovery, data extraction

### Logging Progress
- Record milestones to `/home/gem/task_progress.txt`:
  - Brief notes on what was accomplished
  - Screenshot references used for decisions
  - File paths created/modified

### Failure Reporting
- If subtask cannot be completed after reasonable attempts:
  - Document: actions tried, screenshot references, why each failed
  - Suggest next steps or request human input
  - Include in `task_complete(result="failure_summary")` if task fails

## Tool Call Format

To call a tool, use this format:
<tool_call>
{{"name": "tool_name", "arguments": {{"param1": "value1", "param2": "value2"}}}}
</tool_call>

## Critical Reminders

1. **ALWAYS use DOM operations first**: Start with `dom_mark_elements()`, then use `dom_click(bid)`, `dom_type(bid, text)`, etc.
2. **Only use on-screen actions** when DOM operations fail or are unavailable
3. **Always verify on-screen actions** with screenshots before and after (if you must use them)
4. **Remember working directory** is `/home/gem/` for all file/code/shell operations
5. **Download files programmatically** using `code_execute`, not blind clicks
6. **Verify all file operations** (existence, size, content)
7. **MUST call `task_complete`** when finished, with result if applicable
8. **No fabrication** - never invent URLs, filenames, or data
9. **Stop retrying** after 6 failed browser actions - switch strategy or request help
10. **Use `image_read` for images**: When you need to read or view a downloaded image, use the `image_read` tool. **DO NOT** use `code_execute` to display images (e.g., using matplotlib/PIL) because it produces large base64 outputs that exceed API length limits.

## Summary
Act visually, verify rigorously, and avoid blind exploration. Prefer one extra screenshot + VLM judgement before any ambiguous click.
"""

UNIFIED_FEEDBACK_PROMPT_TEMPLATE_QWEN3VL = """
Your previous actions have been executed. Here is the feedback:

{feedback}

Based on the feedback and your progress toward the goal, determine the next actions to take. You can call multiple tools in sequence.

Remember:
- Analyze what has been accomplished and what remains
- Use the appropriate tools (browser, file, code, shell) for each subtask
- For downloading files: prefer `shell_execute` (wget/curl) or `code_execute` over on-screen clicks
- Verify results when necessary
- **CRITICAL**: When you have the final answer or result, you MUST call `task_complete` to finish the task
  - If the task requires returning a specific output (e.g., JSON answer, text answer), pass it as the 'result' parameter: `task_complete(result="your_answer")`
  - If the task generates files in the sandbox (no specific output required), call `task_complete()` without parameters
  - If the task failed after reasonable attempts, call `task_complete(result="failure_summary: ...")` with a summary of what was tried and why it failed
- Call `task_complete` when the entire task is finished - this is mandatory
- To call a tool, use the format: <tool_call>
{{"name": "tool_name", "arguments": {{"param1": "value1", "param2": "value2"}}}}
</tool_call>
"""


class Controller:
    """Base class for controllers that generate actions given a prompt."""

    def call(self, prompt: str, message_history: List[Dict[str, Any]] | None = None) -> Dict[str, Any]:
        """Send a prompt and return the parsed action/response.

        Args:
            prompt: The prompt to send to the controller
            message_history: Optional list of previous messages for context

        Returns:
            Dictionary with keys:
            - command: The action/command to execute
            - explanation: Brief explanation of what the command does
        """
        raise NotImplementedError("Not implemented")

    def clear_history(self) -> None:
        """Clear any stored conversation history."""
        raise NotImplementedError("Not implemented")

    def build_prompt(self, task_description: str = None, feedback: str = None) -> str:
        """Build a prompt for the controller.

        Args:
            task_description: The task description
            feedback: Feedback from previous iteration

        Returns:
            A formatted prompt string
        """
        raise NotImplementedError("Not implemented")

    def parse_response(self, response: str) -> Dict[str, Any]:
        """Parse controller's response into a structured format.

        Args:
            response: The controller's raw response

        Returns:
            Dictionary with command and explanation
        """
        raise NotImplementedError("Not implemented")

    def get_history(self) -> List[Dict[str, str]]:
        """Get the message history. Can be overridden by subclasses."""
        return []

    def add_tool_message(self, tool_call_id: str, content: str) -> None:
        """Optional hook for controllers that maintain conversation history with tool outputs."""
        return


# OpenAI API Pricing (per 1M tokens)
OPENAI_PRICING = {
    # Flagship models
    "gpt-5.2": {
        "input": 1.750,
        "cached_input": 0.175,
        "output": 14.000
    },
    "gpt-5.2-pro": {
        "input": 21.00,
        "cached_input": None,
        "output": 168.00
    },
    "gpt-5-mini": {
        "input": 0.250,
        "cached_input": 0.025,
        "output": 2.000
    },
    # Fine-tuning models
    "gpt-4.1": {
        "input": 3.00,
        "cached_input": 0.75,
        "output": 12.00
    },
    "gpt-4.1-mini": {
        "input": 0.80,
        "cached_input": 0.20,
        "output": 3.20
    },
    "gpt-4.1-nano": {
        "input": 0.20,
        "cached_input": 0.05,
        "output": 0.80
    },
    "o4-mini": {
        "input": 4.00,
        "cached_input": 1.00,
        "output": 16.00
    },
    # Realtime API - Text
    "gpt-realtime": {
        "input": 4.00,
        "cached_input": 0.40,
        "output": 16.00
    },
    "gpt-realtime-mini": {
        "input": 0.60,
        "cached_input": 0.06,
        "output": 2.40
    },
    # Image Generation API - Text
    "gpt-image-1.5": {
        "input": 5.00,
        "cached_input": 1.25,
        "output": 10.00
    },
    "gpt-image-1": {
        "input": 5.00,
        "cached_input": 1.25,
        "output": None
    },
    "gpt-image-1-mini": {
        "input": 2.00,
        "cached_input": 0.20,
        "output": None
    },
    # Legacy models (fallback pricing)
    "gpt-4o": {
        "input": 2.50,
        "cached_input": 0.25,
        "output": 10.00
    },
    "gpt-4o-mini": {
        "input": 0.15,
        "cached_input": 0.015,
        "output": 0.60
    },
    "gpt-4-turbo": {
        "input": 10.00,
        "cached_input": 1.00,
        "output": 30.00
    },
    "gpt-3.5-turbo": {
        "input": 0.50,
        "cached_input": 0.25,
        "output": 1.50
    }
}


def get_model_pricing(model_name: str) -> Dict[str, float | None]:
    """Get pricing for a model, with fallback to closest match.
    
    Args:
        model_name: Model name (e.g., "gpt-5.2", "gpt-4.1")
        
    Returns:
        Dictionary with input, cached_input, and output pricing per 1M tokens
    """
    model_lower = model_name.lower()
    
    # Direct match
    if model_lower in OPENAI_PRICING:
        return OPENAI_PRICING[model_lower]
    
    # Try to match by prefix
    for key, pricing in OPENAI_PRICING.items():
        if model_lower.startswith(key) or key in model_lower:
            return pricing
    
    # Default fallback to gpt-4.1 pricing
    logger.warning(f"Unknown model pricing for {model_name}, using gpt-4.1 pricing as fallback")
    return OPENAI_PRICING.get("gpt-4.1", {"input": 3.00, "cached_input": 0.75, "output": 12.00})


def calculate_cost(usage, model_name: str) -> float:
    """Calculate API cost from usage information.
    
    Args:
        usage: Usage object from OpenAI API response (has prompt_tokens, completion_tokens, total_tokens, cached_tokens)
        model_name: Model name for pricing lookup
        
    Returns:
        Total cost in USD
    """
    pricing = get_model_pricing(model_name)
    
    # Get token counts (default to 0 if not present)
    prompt_tokens = getattr(usage, "prompt_tokens", 0) or 0
    completion_tokens = getattr(usage, "completion_tokens", 0) or 0
    cached_tokens = getattr(usage, "cached_tokens", 0) or 0
    
    # Calculate costs
    input_cost = 0.0
    if cached_tokens > 0 and pricing.get("cached_input") is not None:
        # Use cached pricing for cached tokens
        input_cost += (cached_tokens / 1_000_000) * pricing["cached_input"]
        # Use regular input pricing for non-cached tokens
        non_cached = prompt_tokens - cached_tokens
        if non_cached > 0 and pricing.get("input") is not None:
            input_cost += (non_cached / 1_000_000) * pricing["input"]
    else:
        # All tokens use regular input pricing
        if pricing.get("input") is not None:
            input_cost = (prompt_tokens / 1_000_000) * pricing["input"]
    
    output_cost = 0.0
    if completion_tokens > 0 and pricing.get("output") is not None:
        output_cost = (completion_tokens / 1_000_000) * pricing["output"]
    
    total_cost = input_cost + output_cost
    return total_cost


class BaseLLM(Controller):
    """Base class for LLM controllers with common functionality."""
    
    def __init__(self, llm_config: Dict[str, Any] | None = None, client_type: str = "shell", **kwargs):
        """Initialize base LLM controller.
        
        Args:
            llm_config: Configuration dictionary
            client_type: Type of client (unified, browser, file, code, shell)
            **kwargs: Additional keyword arguments
        """
        if llm_config is None:
            llm_config = {}
        
        # Common attributes
        self.model = llm_config.get("model", kwargs.get("model", ""))
        self.messages: List[Dict[str, Any]] = []
        self.last_think: str | None = None
        
        # Cost tracking
        self.total_cost: float = 0.0
        self.total_input_tokens: int = 0
        self.total_output_tokens: int = 0
        self.total_cached_tokens: int = 0
        self.api_calls: int = 0
        
        # Store client type and determine tool usage
        self.client_type = client_type
        self.use_tools = client_type in ["browser", "file", "code", "jupyter", "shell", "unified"]
        self.max_parse_retries = max(1, int(llm_config.get("max_parse_retries", 2)))
        
        # Load appropriate tools based on client type
        if self.use_tools:
            from .tools import get_browser_tools, get_file_tools, get_code_tools, get_shell_tools, get_unified_tools
            if client_type == "unified":
                self.tools = get_unified_tools()
            elif client_type == "browser":
                self.tools = get_browser_tools()
            elif client_type == "file":
                self.tools = get_file_tools()
            elif client_type == "code" or client_type == "jupyter":
                self.tools = get_code_tools()
            elif client_type == "shell":
                self.tools = get_shell_tools()
            else:
                self.tools = None
        else:
            self.tools = None
    
    def _prepare_message_content(self, prompt: str, images_base64: list = None) -> Any:
        """Prepare message content from prompt and images.
        
        Args:
            prompt: Text prompt
            images_base64: Optional list of base64-encoded images
            
        Returns:
            Message content (string or list depending on provider)
        """
        # Handle backward compatibility: if single string is passed, convert to list
        if images_base64 is not None and isinstance(images_base64, str):
            images_base64 = [images_base64]
        
        # Build message content based on whether we have images
        if images_base64 and len(images_base64) > 0:
            # Build content list with text and all images
            message_content = []
            
            # Default: text first, then images (OpenAI format)
            # Subclasses can override this method to change the order
            message_content.append({
                "type": "text",
                "text": prompt
            })
            for img_base64 in images_base64:
                message_content.append({
                    "type": "image_url",
                    "image_url": {
                        "url": f"data:image/png;base64,{img_base64}"
                    }
                })
            logger.debug(f"Adding {len(images_base64)} image(s) to message")
            return message_content
        else:
            # Regular text message
            return prompt
    
    def _handle_api_response(self, response: Any, attempt: int, max_attempts: int) -> Dict[str, Any]:
        """Handle API response and parse into action format.
        
        This method should be implemented by subclasses to handle provider-specific responses.
        
        Args:
            response: API response object
            attempt: Current attempt number
            max_attempts: Maximum number of attempts
            
        Returns:
            Parsed response dictionary
        """
        raise NotImplementedError("Subclasses must implement _handle_api_response")
    
    def call(self, prompt: str, images_base64: list = None) -> Dict[str, Any]:
        """Send prompt to LLM API and return parsed response.
        
        Args:
            prompt: The prompt string to send to the LLM
            images_base64: Optional list of base64-encoded image strings
            
        Returns:
            Parsed response dictionary with action information
        """
        # Prepare message content
        message_content = self._prepare_message_content(prompt, images_base64)
        self.messages.append({"role": "user", "content": message_content})
        
        attempt = 0
        max_attempts = self.max_parse_retries
        
        while attempt < max_attempts:
            attempt += 1
            logger.debug(f"Sending prompt to {self.model} (conversation depth: {len(self.messages)}, attempt {attempt}/{max_attempts})")
            
            try:
                # Call provider-specific API
                response = self._make_api_call()
                
                # Handle response (provider-specific)
                parsed_response = self._handle_api_response(response, attempt, max_attempts)
                
                # Cleanup old images after successful call
                self._cleanup_old_user_message_images()
                
                return parsed_response
            except Exception as e:
                logger.error(f"Error calling LLM API: {e}")
                if attempt >= max_attempts:
                    raise
                # Retry logic can be added here if needed
                continue
        
        raise ValueError("Failed to obtain a valid action after retrying LLM response parsing.")
    
    def _make_api_call(self) -> Any:
        """Make the actual API call. Must be implemented by subclasses.
        
        Returns:
            API response object
        """
        raise NotImplementedError("Subclasses must implement _make_api_call")
    
    def build_prompt(self, task_description: str = None, feedback: str = None, conversation_history: list = None) -> str:
        """Build the initial prompt for the LLM.
        
        Args:
            task_description: Initial task description (only used for first iteration)
            feedback: Feedback from previous actions
            conversation_history: List of previous conversation turns (not used, using self.messages for context instead)
        """
        # For Qwen3-VL models, include tool descriptions in prompt
        tools_description = ""
        if hasattr(self, 'is_qwen_vl_model') and self.is_qwen_vl_model and self.use_tools and self.tools:
            tools_description = format_tools_as_text(self.tools)
        
        if task_description is not None:
            # Initial prompt - only used for first iteration
            if hasattr(self, 'is_qwen_vl_model') and self.is_qwen_vl_model:
                if self.client_type in ["unified", "shell"]:
                    return UNIFIED_INITIAL_PROMPT_TEMPLATE_QWEN3VL.format(instruction=task_description, tools_description=tools_description)
            else:
                if self.client_type in ["unified", "shell"]:
                    return UNIFIED_INITIAL_PROMPT_TEMPLATE.format(instruction=task_description)
        if feedback is not None:
            # Feedback prompt - only contains feedback, context is maintained in self.messages
            if hasattr(self, 'is_qwen_vl_model') and self.is_qwen_vl_model:
                if self.client_type in ["unified", "shell"]:
                    return UNIFIED_FEEDBACK_PROMPT_TEMPLATE_QWEN3VL.format(feedback=feedback)
            else:
                if self.client_type in ["unified", "shell"]:
                    return UNIFIED_FEEDBACK_PROMPT_TEMPLATE.format(feedback=feedback)
        raise ValueError("No task description or feedback provided")
    
    def parse_tool_calls_list(self, tool_calls: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Parse a list of tool calls into action format.
        
        Args:
            tool_calls: List of tool call dictionaries
            
        Returns:
            Dictionary with actions list or single action
        """
        actions = []
        
        for tool_call in tool_calls:
            function = tool_call.get("function", {})
            tool_call_id = tool_call.get("id")
            tool_name = function.get("name")
            try:
                arguments_str = function.get("arguments", "{}")
                if isinstance(arguments_str, str):
                    arguments = json.loads(arguments_str)
                else:
                    arguments = arguments_str
            except json.JSONDecodeError:
                logger.error(f"Failed to parse tool arguments: {function.get('arguments')}")
                arguments = {}
            
            # Map tool call to action
            from .tools import map_tool_call_to_action
            action = map_tool_call_to_action(tool_name, arguments)
            if tool_call_id:
                action["tool_call_id"] = tool_call_id
            actions.append(action)
            logger.debug(f"Tool call: {tool_name} -> Action: {action}")
        
        # If only one action, return it directly; otherwise return list
        if len(actions) == 1:
            return actions[0]
        else:
            return {"actions": actions}
    
    def parse_response(self, response: str) -> Dict[str, Any]:
        """Parse JSON from the LLM response."""
        # Check if response contains tool_call tags (Qwen format) - if so, try to parse as tool call first
        if self.use_tools and ("<tool_call>" in response or "</tool_call>" in response):
            if hasattr(self, 'parse_text_tool_calls'):
                tool_calls = self.parse_text_tool_calls(response)
                if tool_calls:
                    logger.debug(f"Found tool_call tags in response, parsed {len(tool_calls)} tool calls")
                    parsed_response = self.parse_tool_calls_list(tool_calls)
                    if parsed_response:
                        return parsed_response[0] if isinstance(parsed_response, list) else parsed_response
        
        # Qwen models often prepend a `<think>...</think>` block; only parse content after it
        try:
            model_name = getattr(self, "model", "")
            if isinstance(model_name, str) and "qwen" in model_name.lower():
                lower = response.lower()
                if "<think>" in lower:
                    end_tag = "</think>"
                    if end_tag in lower:
                        idx = lower.rfind(end_tag)
                        response = response[idx + len(end_tag):]
                    else:
                        open_idx = lower.find("<think>")
                        response = response[open_idx + len("<think>"):]
        except Exception:
            pass
        
        # Remove tool_call tags if present (in case they weren't parsed above)
        if "<tool_call>" in response or "</tool_call>" in response:
            # Try to extract JSON from tool_call tags
            pattern = r'<tool_call>\s*({.*?})\s*</tool_call>'
            match = re.search(pattern, response, re.DOTALL)
            if match:
                response = match.group(1)
                logger.debug(f"Extracted JSON from tool_call tags: {response[:200]}...")
        
        # Try to find JSON in markdown code block
        json_match = re.search(r"```(?:json)?\s*\n?(.*?)\n?```", response, re.DOTALL)
        if json_match:
            json_str = json_match.group(1).strip()
        else:
            # Try to parse the entire response as JSON
            json_str = response.strip()
            logger.debug(f"No markdown code block found, attempting to parse raw response: {json_str}")
        
        try:
            parsed = json.loads(json_str)
            logger.debug(f"Successfully parsed JSON response with keys: {list(parsed.keys())}")
            return parsed
        except json.JSONDecodeError as e:
            # Attempt to auto-fix invalid backslash escapes common in shell commands
            try:
                fixed_json_str = re.sub(r"\\(?![\"\\/bfnrtu])", r"\\\\", json_str)
                parsed = json.loads(fixed_json_str)
                logger.debug("Successfully parsed JSON after fixing invalid escapes")
                return parsed
            except json.JSONDecodeError as e2:
                logger.error(f"Failed to parse JSON response: {e2}")
                logger.error(f"Response content: {response[:200]}...")
                raise ValueError(f"Invalid JSON in LLM response: {e2}")
    
    def get_history(self) -> List[Dict[str, str]]:
        """Get the message history."""
        return self.messages
    
    def clear_history(self) -> None:
        """Clear the message history."""
        logger.debug(f"Clearing message history ({len(self.messages)} messages removed)")
        self.messages = []
        # Note: Cost tracking is NOT reset on clear_history to maintain cumulative cost
    
    def get_cost_stats(self) -> Dict[str, Any]:
        """Get API cost and usage statistics.
        
        Returns:
            Dictionary with cost and token usage information
        """
        return {
            "total_cost_usd": round(self.total_cost, 6),
            "total_input_tokens": self.total_input_tokens,
            "total_output_tokens": self.total_output_tokens,
            "total_cached_tokens": self.total_cached_tokens,
            "total_tokens": self.total_input_tokens + self.total_output_tokens,
            "api_calls": self.api_calls,
            "model": self.model
        }
    
    def reset_cost_tracking(self) -> None:
        """Reset cost tracking statistics."""
        logger.debug("Resetting cost tracking")
        self.total_cost = 0.0
        self.total_input_tokens = 0
        self.total_output_tokens = 0
        self.total_cached_tokens = 0
        self.api_calls = 0
        self.last_think = None
    
    def get_last_think(self) -> str | None:
        """Get the last think/reasoning content for visualization.
        
        Returns:
            The last think content string, or None if not available
        """
        return self.last_think
    
    def add_tool_message(self, tool_call_id: str, content: str) -> None:
        """Append tool call results to the conversation history.
        
        Args:
            tool_call_id: ID of the tool call
            content: Result content from tool execution
        """
        if not tool_call_id:
            return
        if content is None:
            content = ""
        if not isinstance(content, str):
            content = str(content)
        tool_message = {
            "role": "tool",
            "tool_call_id": tool_call_id,
            "content": content
        }
        self.messages.append(tool_message)
        logger.debug(f"Added tool message for {tool_call_id}: {content[:200]}")
    
    def _remove_images_from_message(self, message: Dict[str, Any]) -> Dict[str, Any]:
        """Remove images from a message, keeping only text content.
        
        Args:
            message: Message dictionary with 'role' and 'content' keys
            
        Returns:
            Modified message dictionary with images removed
        """
        content = message.get("content", "")
        if isinstance(content, list):
            # Filter out image items, keep only text
            text_items = [
                item for item in content
                if not (isinstance(item, dict) and item.get("type") == "image_url")
            ]
            # If only one text item remains, extract just the text string
            if len(text_items) == 1 and isinstance(text_items[0], dict) and text_items[0].get("type") == "text":
                message["content"] = text_items[0].get("text", "")
            else:
                message["content"] = text_items
        return message
    
    def _cleanup_old_user_message_images(self) -> None:
        """Remove images from old user messages, keeping only the most recent user message's images.
        
        This prevents image accumulation across iterations. Only the current iteration's images
        should be included in the API call.
        """
        # Check if this provider supports images (subclasses can override)
        if not (hasattr(self, 'is_qwen_vl_model') or hasattr(self, 'is_qwen_model')):
            # For non-Qwen models, check if we should cleanup images
            # This is a generic implementation that can be overridden
            pass
        
        # Find the last user message (should be the one we just added)
        last_user_msg_idx = None
        for i in range(len(self.messages) - 1, -1, -1):
            if self.messages[i].get("role") == "user":
                last_user_msg_idx = i
                break
        
        # Remove images from all user messages except the last one
        if last_user_msg_idx is not None:
            for i in range(len(self.messages)):
                if i != last_user_msg_idx and self.messages[i].get("role") == "user":
                    old_content = self.messages[i].get("content", "")
                    if isinstance(old_content, list):
                        # Check if it has images
                        has_images = any(isinstance(item, dict) and item.get("type") == "image_url"
                                        for item in old_content)
                        if has_images:
                            # Remove images, keep only text
                            self.messages[i] = self._remove_images_from_message(self.messages[i])
                            logger.debug(f"Removed images from old user message at index {i}")


class OpenAILLM(BaseLLM):
    """Language model client using OpenAI API."""

    def __init__(self, llm_config: Dict[str, Any] | None = None, client_type: str = "shell", **kwargs):
        # Initialize base class first
        super().__init__(llm_config, client_type, **kwargs)
        
        if llm_config is None:
            llm_config = {}

        # Extract model and api_key from llm_config, with fallback to kwargs and env variables
        self.model = llm_config.get("model", kwargs.get("model", "gpt-4.1"))
        api_key = (
            llm_config.get("api_key") or
            kwargs.get("api_key") or
            os.getenv("OPENAI_API_KEY")
        )
        # Supports reading base_url from environment variables and falling back to local vLLM if no OpenAI key is provided
        base_url = (
            llm_config.get("base_url") or
            kwargs.get("base_url") or
            os.getenv("OPENAI_BASE_URL") or
            os.getenv("VLLM_BASE_URL")
        )

        # If no OpenAI key is found, but a base_url is configured/detected, set a placeholder key for vLLM compatibility
        if not api_key:
            if base_url:
                api_key = "EMPTY"  # vLLM does not validate the key, but OpenAI SDK requires a string
                logger.info("No OPENAI_API_KEY found. Using placeholder key for vLLM.")
            else:
                # If no key and no base_url, attempt to fall back to a local port-forwarded vLLM
                base_url = "http://localhost:8000/v1"
                api_key = "EMPTY"
                logger.info("No OPENAI_API_KEY or base_url provided. Falling back to local vLLM at http://localhost:8001/v1")

        # Initialize OpenAI client
        client_kwargs = {}
        if api_key:
            client_kwargs["api_key"] = api_key
        if base_url:
            client_kwargs["base_url"] = base_url

        self.client = OpenAI(**client_kwargs)
        
        logger.info(f"OpenAILLM initialized with model: {self.model}")
        if base_url:
            logger.info(f"Using custom base_url: {base_url}")
        logger.debug(f"API key configured: {bool(api_key)}")
        logger.debug(f"Client type: {self.client_type}")
        logger.debug(f"Tool calling mode: {self.use_tools}")
    
    def _prepare_message_content(self, prompt: str, images_base64: list = None) -> Any:
        """Prepare message content for OpenAI API."""
        # Handle backward compatibility: if single string is passed, convert to list
        if images_base64 is not None and isinstance(images_base64, str):
            images_base64 = [images_base64]
        
        # Build message content based on whether we have images
        if images_base64 and len(images_base64) > 0:
            # Build content list with text and all images
            message_content = []
            
            # OpenAI multimodal format: text first, then images
            message_content.append({
                "type": "text",
                "text": prompt
            })
            for img_base64 in images_base64:
                message_content.append({
                    "type": "image_url",
                    "image_url": {
                        "url": f"data:image/png;base64,{img_base64}"
                    }
                })
            logger.debug(f"Adding {len(images_base64)} image(s) to message (total size: {sum(len(img) for img in images_base64)} chars)")
            return message_content
        else:
            # Regular text message
            return prompt
    
    def _make_api_call(self) -> Any:
        """Make OpenAI API call."""
        # Prepare API call parameters
        api_params = {
            "model": self.model,
            "messages": self.messages
        }
        
        # Add tools if in tool calling mode
        if self.use_tools and self.tools:
            api_params["tools"] = self.tools
        
        return self.client.chat.completions.create(**api_params)
    
    def _handle_api_response(self, response: Any, attempt: int, max_attempts: int) -> Dict[str, Any]:
        """Handle OpenAI API response."""
        # Calculate and track API cost
        if hasattr(response, "usage") and response.usage:
            usage = response.usage
            cost = calculate_cost(usage, self.model)
            self.total_cost += cost
            self.total_input_tokens += getattr(usage, "prompt_tokens", 0) or 0
            self.total_output_tokens += getattr(usage, "completion_tokens", 0) or 0
            self.total_cached_tokens += getattr(usage, "cached_tokens", 0) or 0
            self.api_calls += 1
            
            logger.info(
                f"API call cost: ${cost:.6f} | "
                f"Tokens: {getattr(usage, 'prompt_tokens', 0)} input, "
                f"{getattr(usage, 'completion_tokens', 0)} output, "
                f"{getattr(usage, 'cached_tokens', 0)} cached | "
                f"Total cost: ${self.total_cost:.6f}"
            )

        message = response.choices[0].message
        
        # Handle tool calling response (OpenAI format)
        if self.use_tools and hasattr(message, 'tool_calls') and message.tool_calls:
            # Save think content (reasoning before action) for visualization
            self.last_think = message.content if message.content else None
            
            self.messages.append({
                "role": "assistant",
                "content": message.content,
                "tool_calls": [
                    {
                        "id": tc.id,
                        "type": tc.type,
                        "function": {
                            "name": tc.function.name,
                            "arguments": tc.function.arguments
                        }
                    } for tc in message.tool_calls
                ]
            })
            
            logger.debug(f"Received {len(message.tool_calls)} tool calls from {self.model}")
            
            try:
                parsed_response = self.parse_tool_calls(message.tool_calls)
                logger.debug(f"Parsed tool calls (ACTION): \n{colorize(json.dumps(parsed_response, indent=2), 'YELLOW')}")
                return parsed_response
            except ValueError as parse_error:
                logger.warning(f"Failed to parse tool calls (attempt {attempt}/{max_attempts}): {parse_error}")
                # Add tool messages for each tool_call_id to satisfy OpenAI API requirements
                for tc in message.tool_calls:
                    tool_call_id = getattr(tc, "id", None)
                    if tool_call_id:
                        error_content = f"Error parsing tool call: {str(parse_error)}"
                        self.add_tool_message(tool_call_id, error_content)
                
                if attempt >= max_attempts:
                    return {
                        "action_type": "error",
                        "error_message": str(parse_error),
                        "tool_calls": message.tool_calls
                    }
                # Add error message to conversation and retry
                error_message = (
                    f"Error parsing tool calls: {str(parse_error)}\n"
                    f"Please check the tool parameters and try again. "
                    f"Make sure you only use the parameters documented for each tool."
                )
                self.messages.append({
                    "role": "user",
                    "content": error_message
                })
                # Retry by making another API call
                return self._handle_api_response(self._make_api_call(), attempt + 1, max_attempts)
        else:
            # Regular text response (non-tool calling mode or no tools called)
            assistant_message = message.content if message.content else ""
            # Save think content for visualization
            self.last_think = assistant_message
            self.messages.append({"role": "assistant", "content": assistant_message})

            logger.debug(f"Received response from {self.model} (length: {len(assistant_message)} chars)")

            try:
                parsed_response = self.parse_response(assistant_message)
                logger.debug(f"Parsed response (ACTION): \n{colorize(json.dumps(parsed_response, indent=2), 'YELLOW')}")
                return parsed_response
            except ValueError as parse_error:
                logger.warning(f"Failed to parse assistant response (attempt {attempt}/{max_attempts}): {parse_error}")
                if attempt >= max_attempts:
                    raise
                correction_prompt = (
                    "Your previous response did not follow the required format. "
                    "Always respond with either (a) a tool call, or (b) a JSON object describing the next action "
                    "following this schema:\n"
                    "{\n"
                    '  "action_type": "<one of: browser_*, file_*, code_execute, shell_execute, task_complete>",\n'
                    '  "param_name": "param_value", ...\n'
                    "}\n"
                    "Do not nest parameters in a 'parameters' field. Put all parameters at the top level.\n"
                    "Do not include natural language outside the JSON object."
                )
                self.messages.append({
                    "role": "user",
                    "content": correction_prompt
                })
                # Retry by making another API call
                return self._handle_api_response(self._make_api_call(), attempt + 1, max_attempts)
    
    def parse_tool_calls_list(self, tool_calls: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Parse a list of tool calls into action format."""
        actions = []
        
        for tool_call in tool_calls:
            function = tool_call.get("function", {})
            tool_call_id = tool_call.get("id")
            tool_name = function.get("name")
            try:
                arguments_str = function.get("arguments", "{}")
                if isinstance(arguments_str, str):
                    arguments = json.loads(arguments_str)
                else:
                    arguments = arguments_str
            except json.JSONDecodeError:
                logger.error(f"Failed to parse tool arguments: {function.get('arguments')}")
                arguments = {}
            
            # Map tool call to action
            from .tools import map_tool_call_to_action
            action = map_tool_call_to_action(tool_name, arguments)
            if tool_call_id:
                action["tool_call_id"] = tool_call_id
            actions.append(action)
            logger.debug(f"Tool call: {tool_name} -> Action: {action}")
        
        # If only one action, return it directly; otherwise return list
        if len(actions) == 1:
            return actions[0]
        else:
            return {"actions": actions}
    
    def parse_tool_calls(self, tool_calls) -> Dict[str, Any]:
        """Parse tool calls from OpenAI API response into action format."""
        # Convert OpenAI tool_calls to our internal format
        tool_calls_list = []
        for tc in tool_calls:
            tool_calls_list.append({
                "id": getattr(tc, "id", None),
                "function": {
                    "name": tc.function.name,
                    "arguments": tc.function.arguments
                }
            })
        
        return self.parse_tool_calls_list(tool_calls_list)

    def parse_response(self, response: str) -> Dict[str, Any]:
        """Parse JSON from the LLM response."""
        # Try to find JSON in markdown code block
        json_match = re.search(r"```(?:json)?\s*\n?(.*?)\n?```", response, re.DOTALL)
        if json_match:
            json_str = json_match.group(1).strip()
        else:
            # Try to parse the entire response as JSON
            json_str = response.strip()
            logger.debug(f"No markdown code block found, attempting to parse raw response: {json_str}")

        try:
            parsed = json.loads(json_str)
            logger.debug(f"Successfully parsed JSON response with keys: {list(parsed.keys())}")
            return parsed
        except json.JSONDecodeError as e:
            # Attempt to auto-fix invalid backslash escapes common in shell commands
            try:
                fixed_json_str = re.sub(r"\\(?![\"\\/bfnrtu])", r"\\\\", json_str)
                parsed = json.loads(fixed_json_str)
                logger.debug("Successfully parsed JSON after fixing invalid escapes")
                return parsed
            except json.JSONDecodeError as e2:
                logger.error(f"Failed to parse JSON response: {e2}")
                logger.error(f"Response content: {response[:200]}...")
                raise ValueError(f"Invalid JSON in LLM response: {e2}")

    def get_history(self) -> List[Dict[str, str]]:
        """Get the message history."""
        return self.messages

    def clear_history(self) -> None:
        """Clear the message history."""
        logger.debug(f"Clearing message history ({len(self.messages)} messages removed)")
        self.messages = []
        # Note: Cost tracking is NOT reset on clear_history to maintain cumulative cost

    def get_cost_stats(self) -> Dict[str, Any]:
        """Get API cost and usage statistics."""
        return {
            "total_cost_usd": round(self.total_cost, 6),
            "total_input_tokens": self.total_input_tokens,
            "total_output_tokens": self.total_output_tokens,
            "total_cached_tokens": self.total_cached_tokens,
            "total_tokens": self.total_input_tokens + self.total_output_tokens,
            "api_calls": self.api_calls,
            "model": self.model
        }
    
    def reset_cost_tracking(self) -> None:
        """Reset cost tracking statistics."""
        logger.debug("Resetting cost tracking")
        self.total_cost = 0.0
        self.total_input_tokens = 0
        self.total_output_tokens = 0
        self.total_cached_tokens = 0
        self.api_calls = 0
        self.last_think = None
    
    def get_last_think(self) -> str | None:
        """Get the last think/reasoning content for visualization."""
        return self.last_think

    def add_tool_message(self, tool_call_id: str, content: str) -> None:
        """Append tool call results to the conversation history for OpenAI tool-calling compliance."""
        if not tool_call_id:
            return
        if content is None:
            content = ""
        if not isinstance(content, str):
            content = str(content)
        tool_message = {
            "role": "tool",
            "tool_call_id": tool_call_id,
            "content": content
        }
        self.messages.append(tool_message)
        logger.debug(f"Added tool message for {tool_call_id}: {content[:200]}")
    
    def _cleanup_old_user_message_images(self) -> None:
        """Remove images from old user messages (default implementation: no-op)."""
        pass


class QwenLLM(OpenAILLM):
    """Language model client for Qwen models (compatible with OpenAI API but with special handling)."""

    def __init__(self, llm_config: Dict[str, Any] | None = None, client_type: str = "shell", **kwargs):
        super().__init__(llm_config, client_type, **kwargs)
        self.is_qwen_vl_model = "qwen3-vl" in self.model.lower() or "qwen3_vl" in self.model.lower()
        logger.info(f"QwenLLM initialized with model: {self.model} (is_vl: {self.is_qwen_vl_model})")

    def _prepare_message_content(self, prompt: str, images_base64: list = None) -> Any:
        """Prepare message content for Qwen models."""
        # Handle backward compatibility: if single string is passed, convert to list
        if images_base64 is not None and isinstance(images_base64, str):
            images_base64 = [images_base64]
        
        # Build message content based on whether we have images
        if images_base64 and len(images_base64) > 0:
            # Build content list with text and all images
            message_content = []
            
            # Qwen3-VL format: images first, then text
            if self.is_qwen_vl_model:
                for img_base64 in images_base64:
                    message_content.append({
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:image/png;base64,{img_base64}"
                        }
                    })
                message_content.append({
                    "type": "text",
                    "text": prompt
                })
            else:
                # Default/OpenAI format for non-VL Qwen (if they support images?)
                # Assuming text first
                message_content.append({
                    "type": "text",
                    "text": prompt
                })
                for img_base64 in images_base64:
                    message_content.append({
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:image/png;base64,{img_base64}"
                        }
                    })
            
            logger.debug(f"Adding {len(images_base64)} image(s) to message")
            return message_content
        else:
            # Regular text message
            return prompt

    def build_prompt(self, task_description: str = None, feedback: str = None, conversation_history: list = None) -> str:
        """Build the initial prompt for the LLM (handling Qwen3-VL)."""
        # For Qwen3-VL models, include tool descriptions in prompt
        tools_description = ""
        if self.is_qwen_vl_model and self.use_tools and self.tools:
            tools_description = format_tools_as_text(self.tools)
        
        if task_description is not None:
            # Initial prompt - only used for first iteration
            if self.is_qwen_vl_model:
                # Use Qwen3-VL specific templates with tool descriptions
                if self.client_type == "unified":
                    return UNIFIED_INITIAL_PROMPT_TEMPLATE_QWEN3VL.format(instruction=task_description, tools_description=tools_description)
            else:
                # Regular templates for non-VL Qwen models
                if self.client_type == "unified":
                    return UNIFIED_INITIAL_PROMPT_TEMPLATE.format(instruction=task_description)
        if feedback is not None:
            # Feedback prompt
            if self.is_qwen_vl_model:
                if self.client_type == "unified":
                    return UNIFIED_FEEDBACK_PROMPT_TEMPLATE_QWEN3VL.format(feedback=feedback)
            else:
                if self.client_type == "unified":
                    return UNIFIED_FEEDBACK_PROMPT_TEMPLATE.format(feedback=feedback)
        
        # Fallback to base implementation if no match
        return super().build_prompt(task_description, feedback, conversation_history)

    def _make_api_call(self) -> Any:
        """Make OpenAI API call, but exclude tools for Qwen3-VL (text-based tool calling)."""
        # Prepare API call parameters
        api_params = {
            "model": self.model,
            "messages": self.messages
        }
        
        # Add tools if in tool calling mode (except for Qwen3-VL text-based tool calls)
        if self.use_tools and self.tools and not self.is_qwen_vl_model:
            api_params["tools"] = self.tools
        
        return self.client.chat.completions.create(**api_params)

    def _handle_api_response(self, response: Any, attempt: int, max_attempts: int) -> Dict[str, Any]:
        """Handle API response with Qwen-specific parsing."""
        # Calculate cost (same as base)
        if hasattr(response, "usage") and response.usage:
            usage = response.usage
            cost = calculate_cost(usage, self.model)
            self.total_cost += cost
            self.total_input_tokens += getattr(usage, "prompt_tokens", 0) or 0
            self.total_output_tokens += getattr(usage, "completion_tokens", 0) or 0
            self.total_cached_tokens += getattr(usage, "cached_tokens", 0) or 0
            self.api_calls += 1
            logger.info(f"API call cost: ${cost:.6f} | Total cost: ${self.total_cost:.6f}")

        message = response.choices[0].message
        assistant_message = message.content if message.content else ""
        
        # Handle Qwen model special format (text-based tool calls)
        # Check for tool calls either by content pattern
        has_tool_call_pattern = ("<tool_call>" in assistant_message or "</tool_call>" in assistant_message)
        
        if self.use_tools and assistant_message and has_tool_call_pattern:
            tool_calls = self.parse_text_tool_calls(assistant_message)
            if tool_calls:
                # Save think content (extract reasoning before tool calls) for visualization
                if "<tool_call>" in assistant_message:
                    think_part = assistant_message.split("<tool_call>")[0].strip()
                    self.last_think = think_part if think_part else None
                else:
                    self.last_think = assistant_message
                
                self.messages.append({"role": "assistant", "content": assistant_message})
                
                logger.debug(f"Parsed {len(tool_calls)} tool calls from Qwen model")
                
                try:
                    parsed_response = self.parse_tool_calls_list(tool_calls)
                    logger.debug(f"Parsed tool calls (ACTION): \n{colorize(json.dumps(parsed_response, indent=2), 'YELLOW')}")
                    return parsed_response
                except ValueError as parse_error:
                    logger.warning(f"Failed to parse Qwen tool calls (attempt {attempt}/{max_attempts}): {parse_error}")
                    if attempt >= max_attempts:
                        return {
                            "action_type": "error",
                            "error_message": str(parse_error),
                            "tool_calls": tool_calls
                        }
                    error_message = f"Error parsing tool calls: {str(parse_error)}\nPlease check the tool parameters."
                    self.messages.append({"role": "user", "content": error_message})
                    return self._handle_api_response(self._make_api_call(), attempt + 1, max_attempts)
        
        # If no text tool calls, fall back to base implementation (which handles standard tool calls or JSON)
        return super()._handle_api_response(response, attempt, max_attempts)

    def parse_text_tool_calls(self, content: str) -> List[Dict[str, Any]]:
        """Parse Qwen model text-based tool calls."""
        tool_calls = []
        
        # First, try to find complete tool_call blocks
        pattern = r'<tool_call>\s*({.*?})\s*</tool_call>'
        matches = re.findall(pattern, content, re.DOTALL)
        
        # If no complete blocks found, try to find JSON before </tool_call> tag
        if not matches:
            pattern2 = r'({[^{}]*"name"[^{}]*})\s*</tool_call>'
            matches = re.findall(pattern2, content, re.DOTALL)
            if not matches:
                pattern3 = r'({[^{}]*"name"[^{}]*"arguments"[^{}]*})'
                potential_matches = re.findall(pattern3, content, re.DOTALL)
                for potential in potential_matches:
                    idx = content.find(potential)
                    if idx != -1:
                        remaining = content[idx + len(potential):idx + len(potential) + 50]
                        if "</tool_call>" in remaining:
                            matches.append(potential)
                            break
        
        for match in matches:
            try:
                tool_call_data = json.loads(match)
            except json.JSONDecodeError:
                try:
                    fixed_match = self._fix_json_control_chars(match)
                    tool_call_data = json.loads(fixed_match)
                except (json.JSONDecodeError, Exception) as e:
                    logger.error(f"Failed to parse Qwen tool call: {e}")
                    continue
            
            tool_calls.append({
                "function": {
                    "name": tool_call_data.get("name"),
                    "arguments": json.dumps(tool_call_data.get("arguments", {}))
                }
            })
        
        return tool_calls

    def _fix_json_control_chars(self, json_str: str) -> str:
        """Fix unescaped control characters in JSON string values."""
        result = []
        i = 0
        in_string = False
        escape_next = False
        
        while i < len(json_str):
            char = json_str[i]
            if escape_next:
                result.append(char)
                escape_next = False
            elif char == '\\':
                result.append(char)
                escape_next = True
            elif char == '"':
                result.append(char)
                in_string = not in_string
            elif in_string:
                if char == '\n': result.append('\\n')
                elif char == '\r': result.append('\\r')
                elif char == '\t': result.append('\\t')
                elif char == '\b': result.append('\\b')
                elif char == '\f': result.append('\\f')
                elif ord(char) < 32: result.append(f'\\u{ord(char):04x}')
                else: result.append(char)
            else:
                result.append(char)
            i += 1
        return ''.join(result)

    def parse_response(self, response: str) -> Dict[str, Any]:
        """Parse JSON from the LLM response (handling <think> tags)."""
        # Qwen models often prepend a `<think>...</think>` block
        try:
            lower = response.lower()
            if "<think>" in lower:
                end_tag = "</think>"
                if end_tag in lower:
                    idx = lower.rfind(end_tag)
                    response = response[idx + len(end_tag):]
                else:
                    open_idx = lower.find("<think>")
                    response = response[open_idx + len("<think>"):]
        except Exception:
            pass
        
        # Remove tool_call tags if present (in case they weren't parsed above)
        if "<tool_call>" in response or "</tool_call>" in response:
            pattern = r'<tool_call>\s*({.*?})\s*</tool_call>'
            match = re.search(pattern, response, re.DOTALL)
            if match:
                response = match.group(1)
        
        return super().parse_response(response)

    def _remove_images_from_message(self, message: Dict[str, Any]) -> Dict[str, Any]:
        """Remove images from a message, keeping only text content."""
        content = message.get("content", "")
        if isinstance(content, list):
            text_items = [
                item for item in content
                if not (isinstance(item, dict) and item.get("type") == "image_url")
            ]
            if len(text_items) == 1 and isinstance(text_items[0], dict) and text_items[0].get("type") == "text":
                message["content"] = text_items[0].get("text", "")
            else:
                message["content"] = text_items
        return message

    def _cleanup_old_user_message_images(self) -> None:
        """Remove images from old user messages."""
        # Find the last user message
        last_user_msg_idx = None
        for i in range(len(self.messages) - 1, -1, -1):
            if self.messages[i].get("role") == "user":
                last_user_msg_idx = i
                break
        
        if last_user_msg_idx is not None:
            for i in range(len(self.messages)):
                if i != last_user_msg_idx and self.messages[i].get("role") == "user":
                    old_content = self.messages[i].get("content", "")
                    if isinstance(old_content, list):
                        has_images = any(isinstance(item, dict) and item.get("type") == "image_url"
                                        for item in old_content)
                        if has_images:
                            self.messages[i] = self._remove_images_from_message(self.messages[i])
                            logger.debug(f"Removed images from old user message at index {i}")


class ClaudeLLM(BaseLLM):
    """Language model client using Anthropic Claude API."""

    def __init__(self, llm_config: Dict[str, Any] | None = None, client_type: str = "shell", **kwargs):
        if not ANTHROPIC_AVAILABLE:
            raise ImportError("Anthropic libraries not available. Install with: pip install anthropic")
        
        # Initialize base class first
        super().__init__(llm_config, client_type, **kwargs)
        
        if llm_config is None:
            llm_config = {}

        # Extract model and api_key from llm_config, with fallback to kwargs and env variables
        self.model = llm_config.get("model", kwargs.get("model", "claude-3-5-sonnet-20241022"))
        api_key = (
            llm_config.get("api_key") or
            kwargs.get("api_key") or
            os.getenv("ANTHROPIC_API_KEY")
        )
        
        if not api_key:
            raise ValueError("Anthropic API key not found. Set ANTHROPIC_API_KEY environment variable, or provide in config.")

        # Initialize Anthropic client
        base_url = (
            llm_config.get("base_url") or
            kwargs.get("base_url") or
            os.getenv("ANTHROPIC_BASE_URL")
        )
        
        client_kwargs = {"api_key": api_key}
        if base_url:
            client_kwargs["base_url"] = base_url
            
        self.client = anthropic.Anthropic(**client_kwargs)

        logger.info(f"ClaudeLLM initialized with model: {self.model}")
        logger.debug(f"API key configured: {bool(api_key)}")
        logger.debug(f"Client type: {self.client_type}")
        logger.debug(f"Tool calling mode: {self.use_tools}")

    def _convert_openai_tools_to_claude(self, openai_tools: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Convert OpenAI tool format to Claude tool format."""
        claude_tools = []
        for tool in openai_tools:
            if tool.get("type") == "function":
                func = tool.get("function", {})
                claude_tool = {
                    "name": func.get("name", ""),
                    "description": func.get("description", ""),
                    "input_schema": func.get("parameters", {})
                }
                claude_tools.append(claude_tool)
        return claude_tools

    def _prepare_message_content(self, prompt: str, images_base64: list = None) -> Any:
        """Prepare message content for Claude API."""
        # Handle backward compatibility
        if images_base64 is not None and isinstance(images_base64, str):
            images_base64 = [images_base64]
        
        if images_base64 and len(images_base64) > 0:
            message_content = []
            
            # Add images first (or text first? Claude documentation says text/image order doesn't matter much but usually alternating)
            # The user example has image first then text.
            for img_base64 in images_base64:
                message_content.append({
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": "image/png", # Assuming PNG for now
                        "data": img_base64,
                    }
                })
            
            # Add text
            message_content.append({
                "type": "text",
                "text": prompt
            })
            
            logger.debug(f"Adding {len(images_base64)} image(s) to message")
            return message_content
        else:
            return prompt

    def _make_api_call(self) -> Any:
        """Make Claude API call."""
        # Prepare API call parameters
        api_params = {
            "model": self.model,
            "messages": self.messages,
            "max_tokens": 4096, # Default max tokens
        }
        
        # Add tools if in tool calling mode
        if self.use_tools and self.tools:
            api_params["tools"] = self._convert_openai_tools_to_claude(self.tools)
        
        return self.client.messages.create(**api_params)
    
    def _handle_api_response(self, response: Any, attempt: int, max_attempts: int) -> Dict[str, Any]:
        """Handle Claude API response."""
        # Calculate cost
        if hasattr(response, "usage"):
            usage = response.usage
            # Simplified cost calculation (placeholder)
            # You might want to implement accurate pricing for Claude models
            input_tokens = getattr(usage, "input_tokens", 0)
            output_tokens = getattr(usage, "output_tokens", 0)
            
            # Approximate cost (using Claude 3.5 Sonnet pricing as reference: $3/1M input, $15/1M output)
            cost = (input_tokens / 1_000_000) * 3.00 + (output_tokens / 1_000_000) * 15.00
            
            self.total_cost += cost
            self.total_input_tokens += input_tokens
            self.total_output_tokens += output_tokens
            self.api_calls += 1
            
            logger.info(f"API call cost: ${cost:.6f} | Total cost: ${self.total_cost:.6f}")

        # Extract content
        content_blocks = response.content
        text_content = ""
        tool_use_blocks = []
        
        for block in content_blocks:
            if block.type == "text":
                text_content += block.text
            elif block.type == "tool_use":
                tool_use_blocks.append(block)
        
        # Save think content
        self.last_think = text_content if text_content else None
        
        # Add assistant message to history
        # Claude expects the exact content blocks in history for assistant
        # We need to reconstruct the content list
        assistant_content = []
        for block in content_blocks:
            if block.type == "text":
                assistant_content.append({"type": "text", "text": block.text})
            elif block.type == "tool_use":
                assistant_content.append({
                    "type": "tool_use",
                    "id": block.id,
                    "name": block.name,
                    "input": block.input
                })
        
        self.messages.append({
            "role": "assistant",
            "content": assistant_content
        })

        # Handle tool calls
        if tool_use_blocks:
            tool_calls_list = []
            for tool_use in tool_use_blocks:
                tool_calls_list.append({
                    "id": tool_use.id,
                    "function": {
                        "name": tool_use.name,
                        "arguments": tool_use.input # Already a dict
                    }
                })
            
            logger.debug(f"Received {len(tool_calls_list)} tool calls from {self.model}")
            
            try:
                parsed_response = self.parse_tool_calls_list(tool_calls_list)
                logger.debug(f"Parsed tool calls (ACTION): \n{colorize(json.dumps(parsed_response, indent=2), 'YELLOW')}")
                return parsed_response
            except ValueError as parse_error:
                logger.warning(f"Failed to parse tool calls: {parse_error}")
                if attempt >= max_attempts:
                     return {
                        "action_type": "error",
                        "error_message": str(parse_error),
                        "tool_calls": tool_calls_list
                    }
                
                # Add error message
                self.messages.append({
                    "role": "user",
                    "content": [
                        {
                            "type": "text", 
                            "text": f"Error parsing tool calls: {str(parse_error)}"
                        }
                    ]
                })
                return self._handle_api_response(self._make_api_call(), attempt + 1, max_attempts)
        else:
            # Regular text response
            logger.debug(f"Received response from {self.model} (length: {len(text_content)} chars)")
            
            try:
                parsed_response = self.parse_response(text_content)
                logger.debug(f"Parsed response (ACTION): \n{colorize(json.dumps(parsed_response, indent=2), 'YELLOW')}")
                return parsed_response
            except ValueError as parse_error:
                logger.warning(f"Failed to parse assistant response: {parse_error}")
                if attempt >= max_attempts:
                    raise
                
                correction_prompt = (
                    "Your previous response did not follow the required format. "
                    "Always respond with either (a) a tool call, or (b) a JSON object describing the next action."
                )
                self.messages.append({
                    "role": "user",
                    "content": [{"type": "text", "text": correction_prompt}]
                })
                return self._handle_api_response(self._make_api_call(), attempt + 1, max_attempts)

    def add_tool_message(self, tool_call_id: str, content: str) -> None:
        """Append tool call results to the conversation history."""
        if not tool_call_id:
            return
        if content is None:
            content = ""
        if not isinstance(content, str):
            content = str(content)
            
        tool_message = {
            "role": "user",
            "content": [
                {
                    "type": "tool_result",
                    "tool_use_id": tool_call_id,
                    "content": content
                }
            ]
        }
        self.messages.append(tool_message)
        logger.debug(f"Added tool message for {tool_call_id}: {content[:200]}")

    def _remove_images_from_message(self, message: Dict[str, Any]) -> Dict[str, Any]:
        """Remove images from a message."""
        content = message.get("content", "")
        if isinstance(content, list):
            # Filter out image items
            new_content = [
                item for item in content
                if not (isinstance(item, dict) and item.get("type") == "image")
            ]
            message["content"] = new_content
        return message

    def _cleanup_old_user_message_images(self) -> None:
        """Remove images from old user messages."""
        # Find the last user message
        last_user_msg_idx = None
        for i in range(len(self.messages) - 1, -1, -1):
            if self.messages[i].get("role") == "user":
                last_user_msg_idx = i
                break
        
        if last_user_msg_idx is not None:
            for i in range(len(self.messages)):
                if i != last_user_msg_idx and self.messages[i].get("role") == "user":
                    self.messages[i] = self._remove_images_from_message(self.messages[i])


class GeminiLLM(BaseLLM):
    """Language model client using Google Gemini API."""

    def __init__(self, llm_config: Dict[str, Any] | None = None, client_type: str = "shell", **kwargs):
        if not GEMINI_AVAILABLE:
            raise ImportError("Google Gemini libraries not available. Install with: pip install google-genai")
        
        # Initialize base class first
        super().__init__(llm_config, client_type, **kwargs)
        
        if llm_config is None:
            llm_config = {}

        # Extract model and api_key from llm_config, with fallback to kwargs and env variables
        self.model = llm_config.get("model", kwargs.get("model", "gemini-3-flash-preview"))
        api_key = (
            llm_config.get("api_key") or
            kwargs.get("api_key") or
            os.getenv("GEMINI_API_KEY") or
            os.getenv("GOOGLE_API_KEY")
        )
        
        if not api_key:
            raise ValueError("Gemini API key not found. Set GEMINI_API_KEY or GOOGLE_API_KEY environment variable, or provide in config.")

        # Initialize Gemini client
        # Check if we need v1alpha API version (for media_resolution support)
        use_v1alpha = llm_config.get("use_v1alpha", False)
        if use_v1alpha:
            self.client = genai.Client(api_key=api_key, http_options={'api_version': 'v1alpha'})
        else:
            self.client = genai.Client(api_key=api_key)

        logger.info(f"GeminiLLM initialized with model: {self.model}")
        logger.debug(f"API key configured: {bool(api_key)}")
        logger.debug(f"Client type: {self.client_type}")
        logger.debug(f"Tool calling mode: {self.use_tools}")

    def _sanitize_gemini_parameters(self, parameters: Dict[str, Any]) -> Dict[str, Any]:
        """Sanitize parameters for Gemini API (e.g. remove non-string enums)."""
        if not parameters:
            return parameters
            
        new_params = parameters.copy()
        
        # Handle properties if present
        if "properties" in new_params:
            new_props = {}
            for name, prop in new_params["properties"].items():
                new_props[name] = self._sanitize_gemini_parameters(prop)
            new_params["properties"] = new_props
            
        # Handle enum validation
        if "enum" in new_params:
            # Check if any enum value is not a string
            if any(not isinstance(v, str) for v in new_params["enum"]):
                # Gemini only supports string enums in its Pydantic models
                # So we remove the enum constraint for non-string types
                # and add the options to description
                options_str = ", ".join(map(str, new_params["enum"]))
                if "description" in new_params:
                    new_params["description"] += f" (Options: {options_str})"
                else:
                    new_params["description"] = f"Options: {options_str}"
                del new_params["enum"]
                
        return new_params

    def _convert_openai_tools_to_gemini(self, openai_tools: List[Dict[str, Any]]) -> List[types.Tool]:
        """Convert OpenAI tool format to Gemini tool format.
        
        Args:
            openai_tools: List of tools in OpenAI format
            
        Returns:
            List of Gemini Tool objects
        """
        gemini_tools = []
        for tool in openai_tools:
            if tool.get("type") == "function":
                func = tool.get("function", {})
                
                # Sanitize parameters
                parameters = func.get("parameters", {})
                sanitized_parameters = self._sanitize_gemini_parameters(parameters)
                
                gemini_function = {
                    "name": func.get("name", ""),
                    "description": func.get("description", ""),
                    "parameters": sanitized_parameters
                }
                gemini_tools.append(types.Tool(function_declarations=[gemini_function]))
        return gemini_tools

    def _convert_openai_messages_to_gemini_contents(self, messages: List[Dict[str, Any]]) -> List[types.Content]:
        """Convert OpenAI message format to Gemini contents format.
        
        Args:
            messages: List of messages in OpenAI format
            
        Returns:
            List of Gemini Content objects
        """
        contents = []
        current_role = None
        current_parts = []
        
        for message in messages:
            role = message.get("role")
            content = message.get("content", "")
            
            # Handle tool messages (skip for now, Gemini handles tool results differently)
            if role == "tool":
                continue
            
            # Handle assistant messages with tool_calls
            if role == "assistant" and "tool_calls" in message:
                # For assistant messages with tool calls, we need to add the function call parts
                if current_parts:
                    contents.append(types.Content(role=current_role, parts=current_parts))
                    current_parts = []
                
                # Add text content if present
                if content:
                    current_parts.append(types.Part(text=content))
                
                # Add function call parts
                for tool_call in message.get("tool_calls", []):
                    func = tool_call.get("function", {})
                    try:
                        args = json.loads(func.get("arguments", "{}"))
                    except json.JSONDecodeError:
                        args = {}
                    
                    current_parts.append(types.Part(
                        function_call=types.FunctionCall(
                            name=func.get("name", ""),
                            args=args
                        )
                    ))
                
                if current_parts:
                    contents.append(types.Content(role="model", parts=current_parts))
                    current_parts = []
                continue
            
            # Map OpenAI roles to Gemini roles
            gemini_role = "user" if role == "user" else "model"
            
            # If role changed, save previous content
            if current_role is not None and current_role != gemini_role and current_parts:
                contents.append(types.Content(role=current_role, parts=current_parts))
                current_parts = []
            
            current_role = gemini_role
            
            # Handle content (can be string or list for multimodal)
            if isinstance(content, str):
                if content:
                    current_parts.append(types.Part(text=content))
            elif isinstance(content, list):
                for item in content:
                    if isinstance(item, dict):
                        if item.get("type") == "text":
                            current_parts.append(types.Part(text=item.get("text", "")))
                        elif item.get("type") == "image_url":
                            # Extract base64 data from data URL
                            image_url = item.get("image_url", {}).get("url", "")
                            if image_url.startswith("data:image"):
                                # Format: data:image/png;base64,<base64_data>
                                base64_data = image_url.split(",", 1)[1] if "," in image_url else ""
                                if base64_data:
                                    try:
                                        image_data = base64.b64decode(base64_data)
                                        mime_type = "image/png"  # Default
                                        if "image/jpeg" in image_url or "image/jpg" in image_url:
                                            mime_type = "image/jpeg"
                                        elif "image/gif" in image_url:
                                            mime_type = "image/gif"
                                        elif "image/webp" in image_url:
                                            mime_type = "image/webp"
                                        
                                        current_parts.append(types.Part(
                                            inline_data=types.Blob(
                                                mime_type=mime_type,
                                                data=image_data
                                            )
                                        ))
                                    except Exception as e:
                                        logger.warning(f"Failed to decode image: {e}")
        
        # Add remaining content
        if current_parts:
            contents.append(types.Content(role=current_role, parts=current_parts))
        
        return contents

    def _make_api_call(self) -> Any:
        """Make Gemini API call."""
        # Convert messages to Gemini contents format
        contents = self._convert_openai_messages_to_gemini_contents(self.messages)
        
        # Prepare API call parameters
        api_params = {
            "model": self.model,
            "contents": contents
        }
        
        # Add tools if in tool calling mode
        if self.use_tools and self.tools:
            gemini_tools = self._convert_openai_tools_to_gemini(self.tools)
            if gemini_tools:
                config = types.GenerateContentConfig(tools=gemini_tools)
                api_params["config"] = config
        
        response = self.client.models.generate_content(**api_params)
        self.api_calls += 1
        return response
    
    def _handle_api_response(self, response: Any, attempt: int, max_attempts: int) -> Dict[str, Any]:
        """Handle Gemini API response."""
        # Extract response content
        if not response.candidates:
            raise ValueError("No candidates in Gemini response")
        
        candidate = response.candidates[0]
        if not candidate.content or not candidate.content.parts:
            raise ValueError("No content parts in Gemini response")
        
        # Check for function calls
        function_calls = []
        text_content = ""
        
        for part in candidate.content.parts:
            if hasattr(part, 'function_call') and part.function_call:
                # Extract function call name and args
                func_call = part.function_call
                func_name = func_call.name if hasattr(func_call, 'name') else ""
                # Args might be a dict or already serialized, handle both cases
                if hasattr(func_call, 'args'):
                    func_args = func_call.args
                    if isinstance(func_args, dict):
                        func_args_str = json.dumps(func_args)
                    else:
                        func_args_str = str(func_args)
                else:
                    func_args_str = "{}"
                
                function_calls.append({
                    "id": f"call_{len(function_calls)}",
                    "function": {
                        "name": func_name,
                        "arguments": func_args_str
                    }
                })
            elif hasattr(part, 'text') and part.text:
                text_content += part.text
        
        # Save think content for visualization
        self.last_think = text_content if text_content else None
        
        # Handle tool calling response
        if function_calls:
            # Convert to OpenAI-style tool_calls format for parsing
            tool_calls_list = []
            for fc in function_calls:
                tool_calls_list.append({
                    "id": fc.get("id"),
                    "function": {
                        "name": fc["function"]["name"],
                        "arguments": fc["function"]["arguments"]
                    }
                })
            
            # Add assistant message with tool calls
            assistant_message = {"role": "assistant", "content": text_content, "tool_calls": tool_calls_list}
            self.messages.append(assistant_message)
            
            logger.debug(f"Received {len(function_calls)} function calls from {self.model}")
            
            try:
                parsed_response = self.parse_tool_calls(tool_calls_list)
                logger.debug(f"Parsed tool calls (ACTION): \n{colorize(json.dumps(parsed_response, indent=2), 'YELLOW')}")
                return parsed_response
            except ValueError as parse_error:
                logger.warning(f"Failed to parse tool calls (attempt {attempt}/{max_attempts}): {parse_error}")
                if attempt >= max_attempts:
                    return {
                        "action_type": "error",
                        "error_message": str(parse_error),
                        "tool_calls": tool_calls_list
                    }
                error_message = (
                    f"Error parsing tool calls: {str(parse_error)}\n"
                    f"Please check the tool parameters and try again. "
                    f"Make sure you only use the parameters documented for each tool."
                )
                self.messages.append({
                    "role": "user",
                    "content": error_message
                })
                # Retry by making another API call
                return self._handle_api_response(self._make_api_call(), attempt + 1, max_attempts)
        else:
            # Regular text response
            assistant_message = {"role": "assistant", "content": text_content}
            self.messages.append(assistant_message)

            logger.debug(f"Received response from {self.model} (length: {len(text_content)} chars)")

            try:
                parsed_response = self.parse_response(text_content)
                logger.debug(f"Parsed response (ACTION): \n{colorize(json.dumps(parsed_response, indent=2), 'YELLOW')}")
                return parsed_response
            except ValueError as parse_error:
                logger.warning(f"Failed to parse assistant response (attempt {attempt}/{max_attempts}): {parse_error}")
                if attempt >= max_attempts:
                    raise
                correction_prompt = (
                    "Your previous response did not follow the required format. "
                    "Always respond with either (a) a tool call, or (b) a JSON object describing the next action "
                    "following this schema:\n"
                    "{\n"
                    '  "action_type": "<one of: browser_*, file_*, code_execute, shell_execute, task_complete>",\n'
                    '  "param_name": "param_value", ...\n'
                    "}\n"
                    "Do not nest parameters in a 'parameters' field. Put all parameters at the top level.\n"
                    "Do not include natural language outside the JSON object."
                )
                self.messages.append({
                    "role": "user",
                    "content": correction_prompt
                })
                # Retry by making another API call
                return self._handle_api_response(self._make_api_call(), attempt + 1, max_attempts)
    
    def parse_tool_calls(self, tool_calls) -> Dict[str, Any]:
        """Parse tool calls from Gemini API response into action format.
        
        Args:
            tool_calls: List of tool calls from Gemini API
            
        Returns:
            Dictionary with actions list or single action
        """
        # Convert Gemini tool_calls to our internal format
        tool_calls_list = []
        for tc in tool_calls:
            tool_calls_list.append({
                "id": tc.get("id"),
                "function": {
                    "name": tc["function"]["name"],
                    "arguments": tc["function"]["arguments"]
                }
            })
        
        return self.parse_tool_calls_list(tool_calls_list)

    def get_history(self) -> List[Dict[str, str]]:
        """Get the message history."""
        return self.messages

    def clear_history(self) -> None:
        """Clear the message history."""
        logger.debug(f"Clearing message history ({len(self.messages)} messages removed)")
        self.messages = []
        # Note: Cost tracking is NOT reset on clear_history to maintain cumulative cost

    def get_cost_stats(self) -> Dict[str, Any]:
        """Get API cost and usage statistics.
        
        Returns:
            Dictionary with cost and token usage information
        """
        return {
            "total_cost_usd": round(self.total_cost, 6),
            "total_input_tokens": self.total_input_tokens,
            "total_output_tokens": self.total_output_tokens,
            "total_cached_tokens": self.total_cached_tokens,
            "total_tokens": self.total_input_tokens + self.total_output_tokens,
            "api_calls": self.api_calls,
            "model": self.model
        }
    
    def reset_cost_tracking(self) -> None:
        """Reset cost tracking statistics."""
        logger.debug("Resetting cost tracking")
        self.total_cost = 0.0
        self.total_input_tokens = 0
        self.total_output_tokens = 0
        self.total_cached_tokens = 0
        self.api_calls = 0
        self.last_think = None
    
    def get_last_think(self) -> str | None:
        """Get the last think/reasoning content for visualization.
        
        Returns:
            The last think content string, or None if not available
        """
        return self.last_think

    def add_tool_message(self, tool_call_id: str, content: str) -> None:
        """Append tool call results to the conversation history for Gemini tool-calling compliance."""
        if not tool_call_id:
            return
        if content is None:
            content = ""
        if not isinstance(content, str):
            content = str(content)
        
        # For Gemini, we need to add function response as a part
        # Find the corresponding function call and add result
        # This is a simplified implementation - Gemini may handle this differently
        tool_message = {
            "role": "model",
            "content": f"Tool call {tool_call_id} result: {content}"
        }
        self.messages.append(tool_message)
        logger.debug(f"Added tool message for {tool_call_id}: {content[:200]}")

    def _remove_images_from_message(self, message: Dict[str, Any]) -> Dict[str, Any]:
        """Remove images from a message, keeping only text content.
        
        Args:
            message: Message dictionary with 'role' and 'content' keys
            
        Returns:
            Modified message dictionary with images removed
        """
        content = message.get("content", "")
        if isinstance(content, list):
            # Filter out image items, keep only text
            text_items = [
                item for item in content
                if not (isinstance(item, dict) and item.get("type") == "image_url")
            ]
            # If only one text item remains, extract just the text string
            if len(text_items) == 1 and isinstance(text_items[0], dict) and text_items[0].get("type") == "text":
                message["content"] = text_items[0].get("text", "")
            else:
                message["content"] = text_items
        return message

    def _cleanup_old_user_message_images(self) -> None:
        """Remove images from old user messages, keeping only the most recent user message's images.
        
        This prevents image accumulation across iterations. Only the current iteration's images
        should be included in the API call.
        """
        # Find the last user message (should be the one we just added)
        last_user_msg_idx = None
        for i in range(len(self.messages) - 1, -1, -1):
            if self.messages[i].get("role") == "user":
                last_user_msg_idx = i
                break
        
        # Remove images from all user messages except the last one
        if last_user_msg_idx is not None:
            for i in range(len(self.messages)):
                if i != last_user_msg_idx and self.messages[i].get("role") == "user":
                    old_content = self.messages[i].get("content", "")
                    if isinstance(old_content, list):
                        # Check if it has images
                        has_images = any(isinstance(item, dict) and item.get("type") == "image_url"
                                        for item in old_content)
                        if has_images:
                            # Remove images, keep only text
                            self.messages[i] = self._remove_images_from_message(self.messages[i])
                            logger.debug(f"Removed images from old user message at index {i}")


class Human(Controller):
    """Human controller that prompts user for manual input."""

    def __init__(self):
        """Initialize the Human controller."""
        logger.info("Human controller initialized")

    def call(self, prompt: str, message_history: List[Dict[str, Any]] | None = None) -> Dict[str, Any]:
        """Prompt user for manual input given a prompt.

        Args:
            prompt: The prompt to display to the user
            message_history: Ignored for Human controller

        Returns:
            Dictionary with command and explanation
        """
        logger.debug(f"Prompting user with: {prompt[:100]}...")
        print("\n" + "=" * 80)
        print("PROMPT:")
        print("=" * 80)
        print(prompt)
        print("=" * 80)
        print("Please provide your response below:")
        print("=" * 80)

        user_input = input("> ").strip()
        logger.debug(f"User provided input: {user_input[:100]}...")

        # Parse and return the structured response
        parsed_response = self.parse_response(user_input)
        return parsed_response

    def clear_history(self) -> None:
        """Human controller doesn't maintain history."""
        logger.debug("Human controller has no history to clear")

    def build_prompt(self, task_description: str = None, feedback: str = None) -> str:
        """Build a prompt for the human user.

        Args:
            task_description: The task description
            feedback: Feedback from previous iteration

        Returns:
            A formatted prompt string
        """
        if task_description is not None:
            prompt = f"Task: {task_description}\n\nPlease provide a shell command to solve this task."
            logger.debug(f"Built initial prompt for task: {prompt}")
            return prompt
        if feedback is not None:
            prompt = f"Feedback: {feedback}\n\nPlease provide the next shell command."
            logger.debug(f"Built feedback prompt: {prompt}")
            return prompt
        raise ValueError("No task description or feedback provided")

    def parse_response(self, response: str) -> Dict[str, Any]:
        """Parse user's response as a simple shell command.

        Args:
            response: The user's input response (plain shell command)

        Returns:
            Dictionary with command and explanation
        """
        command = response.strip()
        logger.debug(f"Parsed user command: {command[:100]}...")
        return {"command": command, "explanation": "User provided command"}
