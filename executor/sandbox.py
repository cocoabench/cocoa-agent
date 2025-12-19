"""
Helper functions for executor operations.
"""

import time
import subprocess
import json
from typing import Any, Dict, Optional
from pathlib import Path
import requests
from .utils import retry_request, validate_response, get_logger, colorize

from agent_sandbox import Sandbox
from agent_sandbox.browser import (
    Action_Click, Action_Typing, Action_Press, Action_Scroll,
    Action_MoveTo, Action_MoveRel, Action_Wait, Action_DoubleClick, Action_RightClick,
    Action_DragTo, Action_DragRel, Action_Hotkey, Action_KeyDown, Action_KeyUp
)

logger = get_logger("sandbox")


class SandboxClient:
    """Client for communicating with the agent server."""

    def __init__(self, sandbox_config: Dict[str, Any] | None = None, **kwargs):
        if sandbox_config is None:
            sandbox_config = {}

        # Extract docker settings from sandbox_config, with fallback to kwargs for backwards compatibility
        self.port = sandbox_config.get("docker_port", kwargs.get("port", 8080))
        base_url = sandbox_config.get("base_url", kwargs.get("base_url", f"http://localhost:{self.port}"))

        self.base_url = base_url.rstrip('/')
        self.container_id: Optional[str] = None
        self.task_name: Optional[str] = None
        self.task_dir: Optional[str] = None

    def health_check(self) -> bool:
        """Check if the agent server is running."""
        try:
            response = requests.get(f"{self.base_url}/v1/sandbox", timeout=5)
            return response.status_code == 200
        except Exception:
            return False

    def get_feedback(self, action: Dict[str, Any]) -> Dict[str, Any]:
        """Get feedback from executing an action.

        Args:
            action: The action/command to execute

        Returns:
            Dictionary with done status and feedback message
        """
        raise NotImplementedError("Not implemented")

    def send_request(self, endpoint: str, data: Dict[str, Any]) -> Dict[str, Any]:
        """Send request to agent server."""
        def _request():
            response = requests.post(
                f"{self.base_url}/{endpoint.lstrip('/')}",
                json=data,
                headers={"Content-Type": "application/json"},
                timeout=30
            )
            return validate_response(response)

        return retry_request(_request)

    def create_docker_environment(self, task: Dict[str, Any], wait_time: int = 60) -> bool:
        """
        Create and start an agent server container using task's docker-compose.yaml.

        Args:
            task: Task object containing task_dir (path to task directory with docker-compose.yaml)
            wait_time: Time to wait for server to be ready (default: 60 seconds)

        Returns:
            True if successful, False otherwise
        """
        try:
            task_dir = task.get("task_dir")
            task_name = task.get("task_name", "task")

            if not task_dir:
                logger.error("Task object must contain 'task_dir' key")
                return False

            self.task_name = task_name
            self.task_dir = task_dir
            docker_compose_path = f"{task_dir}/docker-compose.yaml"

            # Set up environment variables for docker-compose
            env = {
                "TASK_DOCKER_IMAGE_NAME": f"task-{task_name}:latest",
                "TASK_DOCKER_CONTAINER_NAME": f"task-{task_name}-container",
                "HOST_PORT": str(self.port)
            }

            # Build without cache and start using docker-compose
            logger.info(f"Building and starting container for task '{task_name}' using docker-compose")

            # Build the image without cache
            build_result = subprocess.run(
                ["docker", "compose", "-f", docker_compose_path, "build", "--no-cache"],
                capture_output=True,
                text=True,
                timeout=120,
                env={**subprocess.os.environ, **env}
            )

            if build_result.returncode != 0:
                logger.error(f"Failed to build container with docker-compose: {build_result.stderr}")
                return False

            # Start the container
            result = subprocess.run(
                ["docker", "compose", "-f", docker_compose_path, "up", "-d"],
                capture_output=True,
                text=True,
                timeout=120,
                env={**subprocess.os.environ, **env}
            )

            if result.returncode != 0:
                logger.error(f"Failed to start container with docker-compose: {result.stderr}")
                return False

            # Extract container ID from docker-compose
            self.container_id = env["TASK_DOCKER_CONTAINER_NAME"]
            logger.info(f"Container started successfully. Container name: {self.container_id}")

            # Wait for server to be ready
            waited = 0
            while waited < wait_time:
                if self.health_check():
                    logger.info("Docker environment ready")
                    return True
                else:
                    waited += 5
                    logger.info(f"Docker environment not ready yet. Waiting ... ({waited}/{wait_time} seconds)")
                    time.sleep(5)

            logger.error(f"Docker environment failed to become ready within timeout of {wait_time} seconds")
            return False

        except subprocess.TimeoutExpired:
            logger.error("Docker command timed out")
            return False
        except Exception as e:
            logger.error(f"Error creating agent server: {e}")
            return False

    def copy_to_container(self, host_path: str, container_path: str) -> bool:
        """
        Copy file or directory from host to running container.

        Creates the parent directory in the container if it doesn't exist.

        Args:
            host_path: Path on host machine (file or directory)
            container_path: Destination path in container

        Returns:
            True if successful, False otherwise
        """
        try:
            if not self.container_id:
                logger.error("No container running. Call create_docker_environment first.")
                return False

            host_file = Path(host_path)
            if not host_file.exists():
                logger.error(f"Source path does not exist: {host_path}")
                return False

            # Create parent directory in container if needed
            parent_dir = str(Path(container_path).parent)
            if parent_dir and parent_dir != "/":
                mkdir_result = subprocess.run(
                    ["docker", "exec", self.container_id, "mkdir", "-p", parent_dir],
                    capture_output=True,
                    text=True,
                    timeout=30
                )
                if mkdir_result.returncode != 0:
                    logger.error(f"Failed to create parent directory: {mkdir_result.stderr}")
                    return False

            logger.info(f"Copying {host_path} to container {self.container_id}:{container_path}")

            # Use docker cp to copy the file/directory
            result = subprocess.run(
                ["docker", "cp", str(host_file), f"{self.container_id}:{container_path}"],
                capture_output=True,
                text=True,
                timeout=30
            )

            if result.returncode == 0:
                logger.info(f"Successfully copied {host_path} to container")
                return True
            else:
                logger.error(f"Failed to copy file to container: {result.stderr}")
                return False

        except subprocess.TimeoutExpired:
            logger.error("Docker copy command timed out")
            return False
        except Exception as e:
            logger.error(f"Error copying file to container: {e}")
            return False


    def cleanup_docker_environment(self) -> bool:
        """
        Stop and remove the agent server container using docker-compose.

        Returns:
            True if successful, False otherwise
        """
        try:
            if self.task_dir and self.task_name:
                docker_compose_path = f"{self.task_dir}/docker-compose.yaml"
                logger.info(f"Stopping container for task '{self.task_name}' using docker-compose")

                result = subprocess.run(
                    ["docker", "compose", "-f", docker_compose_path, "down"],
                    capture_output=True,
                    text=True,
                    timeout=30
                )

                if result.returncode == 0:
                    logger.info("Agent server container stopped successfully")
                    self.container_id = None
                    return True
                else:
                    logger.error(f"Failed to stop container: {result.stderr}")
                    return False
            else:
                logger.info("No container to clean up")
                return True
        except subprocess.TimeoutExpired:
            logger.error("Docker command timed out")
            return False
        except Exception as e:
            logger.error(f"Error cleaning up agent server: {e}")
            return False

class BrowserSandboxClient(SandboxClient):
    """Client for communicating with the agent server for browser actions."""

    def __init__(self, sandbox_config: Dict[str, Any] | None = None, **kwargs):
        super().__init__(sandbox_config, **kwargs)
        # Track all actions and their feedbacks
        self.execution_history: list[Dict[str, Any]] = []
        self.sdk_client: Optional[Sandbox] = None

    def _initialize_sdk_client(self) -> None:
        """Initialize the AIO Sandbox SDK client."""
        if self.sdk_client is None:
            self.sdk_client = Sandbox(base_url=self.base_url)
            logger.debug(f"Initialized Sandbox SDK client with base_url: {self.base_url}")

    def _construct_browser_action(self, action_data: Dict[str, Any]):
        """Construct a browser action object from action data.
        
        Args:
            action_data: Dictionary containing action_type and parameters
            
        Returns:
            Browser action object
        """
        action_type = action_data.get("action_type")
        
        if action_type == "browser_click":
            return Action_Click(
                x=action_data.get("x"),
                y=action_data.get("y"),
                button=action_data.get("button", "left"),
                num_clicks=action_data.get("num_clicks", 1)
            )
        elif action_type == "browser_type":
            return Action_Typing(
                text=action_data.get("text"),
                use_clipboard=action_data.get("use_clipboard", True)
            )
        elif action_type == "browser_press":
            # Convert key to lowercase for API compatibility
            key = action_data.get("key", "")
            return Action_Press(key=key.lower() if isinstance(key, str) else key)
        elif action_type == "browser_key_down":
            # Convert key to lowercase for API compatibility
            key = action_data.get("key", "")
            return Action_KeyDown(key=key.lower() if isinstance(key, str) else key)
        elif action_type == "browser_key_up":
            # Convert key to lowercase for API compatibility
            key = action_data.get("key", "")
            return Action_KeyUp(key=key.lower() if isinstance(key, str) else key)
        elif action_type == "browser_hotkey":
            # Convert all keys to lowercase for API compatibility
            keys = action_data.get("keys", [])
            keys_lower = [k.lower() if isinstance(k, str) else k for k in keys]
            return Action_Hotkey(keys=keys_lower)
        elif action_type == "browser_scroll":
            return Action_Scroll(
                dx=action_data.get("dx", 0),
                dy=action_data.get("dy", 0)
            )
        elif action_type == "browser_move_to":
            return Action_MoveTo(
                x=action_data.get("x"),
                y=action_data.get("y")
            )
        elif action_type == "browser_move_rel":
            return Action_MoveRel(
                x_offset=action_data.get("x_offset"),
                y_offset=action_data.get("y_offset")
            )
        elif action_type == "browser_drag_to":
            return Action_DragTo(
                x=action_data.get("x"),
                y=action_data.get("y")
            )
        elif action_type == "browser_drag_rel":
            return Action_DragRel(
                x_offset=action_data.get("x_offset"),
                y_offset=action_data.get("y_offset")
            )
        elif action_type == "browser_wait":
            return Action_Wait(duration=action_data.get("duration"))
        else:
            raise ValueError(f"Unsupported action type: {action_type}")

    def _take_screenshot(self) -> tuple[str, str]:
        """Take a screenshot and return base64 encoded string and status message.
        
        Returns:
            Tuple of (base64_encoded_image, status_message)
        """
        try:
            import base64
            screenshot_data = b""
            for chunk in self.sdk_client.browser.screenshot():
                screenshot_data += chunk
            
            # Encode to base64
            base64_image = base64.b64encode(screenshot_data).decode('utf-8')
            status_message = f"Screenshot taken successfully ({len(screenshot_data)} bytes)"
            return base64_image, status_message
        except Exception as e:
            logger.error(f"Failed to take screenshot: {e}")
            return "", f"Failed to take screenshot: {str(e)}"
    
    def take_screenshot(self) -> tuple[str, str]:
        """Public method to take a screenshot for visualization.
        
        Returns:
            Tuple of (base64_encoded_image, status_message)
        """
        self._initialize_sdk_client()
        return self._take_screenshot()
    
    def _get_browser_info(self) -> str:
        """Get browser information including CDP URL and viewport.
        
        Returns:
            Browser info as formatted string
        """
        try:
            info = self.sdk_client.browser.get_info()
            browser_data = info.data
            return f"Browser Info:\nCDP URL: {browser_data.cdp_url}\nViewport: {browser_data.viewport.width}x{browser_data.viewport.height}"
        except Exception as e:
            logger.error(f"Failed to get browser info: {e}")
            return f"Failed to get browser info: {str(e)}"
    
    def _run_async(self, coro):
        """Run an async coroutine, handling both sync and async contexts.
        
        Args:
            coro: Coroutine to run
            
        Returns:
            Result of the coroutine
        """
        import asyncio
        try:
            # Try to get the current event loop
            loop = asyncio.get_running_loop()
            # If we're in an async context, we need to use a different approach
            # Create a new event loop in a thread
            import concurrent.futures
            import threading
            
            def run_in_thread():
                new_loop = asyncio.new_event_loop()
                asyncio.set_event_loop(new_loop)
                try:
                    return new_loop.run_until_complete(coro)
                finally:
                    new_loop.close()
            
            with concurrent.futures.ThreadPoolExecutor() as executor:
                future = executor.submit(run_in_thread)
                return future.result(timeout=60)  # Increased timeout for complex pages
        except RuntimeError:
            # No running event loop, use asyncio.run()
            return asyncio.run(coro)

    def _with_page(self, func, wait_timeout: int = 5000):
        """Connect to the running browser via CDP and run an async function on the active page.
        
        Args:
            func: Async function that takes a page and returns a result
            wait_timeout: Timeout in ms for waiting for page load (default 5000ms, use 0 to skip wait)
        """
        import asyncio
        from playwright.async_api import async_playwright

        async def runner():
            browser_info = self.sdk_client.browser.get_info().data
            async with async_playwright() as p:
                browser = await p.chromium.connect_over_cdp(browser_info.cdp_url)
                try:
                    context = browser.contexts[0] if browser.contexts else await browser.new_context()
                    page = context.pages[0] if context.pages else await context.new_page()
                    # Use shorter timeout for DOM operations on already-loaded pages
                    if wait_timeout > 0:
                        try:
                            await page.wait_for_load_state("domcontentloaded", timeout=wait_timeout)
                        except Exception:
                            # If page is already loaded or timeout, continue anyway
                            pass
                    return await func(page)
                finally:
                    # Closing the Playwright client disconnects but does not shut down the remote browser
                    await browser.close()

        return self._run_async(runner())

    def _dom_get_text(self, max_chars: int = 8000) -> str:
        """Return page text (innerText of body)."""
        try:
            async def op(page):
                return await page.inner_text("body")

            text = self._with_page(lambda page: op(page), wait_timeout=5000)
            if text is None:
                return "Page text is empty."
            if len(text) > max_chars:
                text = text[:max_chars] + "\n... (truncated)"
            return f"Page text content:\n{text}"
        except Exception as e:
            logger.error(f"Failed to get page text: {e}")
            return f"Failed to get page text: {str(e)}"

    def _dom_get_html(self, max_chars: int = 12000) -> str:
        """Return page HTML (page.content)."""
        try:
            async def op(page):
                return await page.content()

            html = self._with_page(lambda page: op(page), wait_timeout=5000)
            if html is None:
                return "Page HTML is empty."
            if len(html) > max_chars:
                html = html[:max_chars] + "\n... (truncated)"
            return f"Page HTML content:\n{html}"
        except Exception as e:
            logger.error(f"Failed to get page HTML: {e}")
            return f"Failed to get page HTML: {str(e)}"

    def _dom_query_selector(self, selector: str, limit: int = 20) -> str:
        """Query elements via CSS selector and summarize tag/text/href/class/id/name for precise selection."""
        try:
            async def op(page):
                elements = await page.query_selector_all(selector)
                results = []
                for i, element in enumerate(elements[:limit]):
                    try:
                        text = await element.inner_text()
                    except Exception:
                        text = ""
                    try:
                        tag = await element.evaluate("el => el.tagName")
                    except Exception:
                        tag = "UNKNOWN"
                    # Get key attributes for precise selection
                    attrs = {}
                    for attr_name in ["id", "class", "name", "type", "href", "role", "aria-label"]:
                        try:
                            val = await element.get_attribute(attr_name)
                            if val:
                                attrs[attr_name] = val
                        except Exception:
                            pass
                    
                    # Build info string
                    info_parts = [f"{i+1}. <{tag}>"]
                    
                    # Add id if present (most specific)
                    if "id" in attrs:
                        info_parts.append(f"id=\"{attrs['id']}\"")
                    
                    # Add class if present
                    if "class" in attrs:
                        # Truncate long class lists
                        class_val = attrs["class"]
                        if len(class_val) > 100:
                            class_val = class_val[:100] + "..."
                        info_parts.append(f"class=\"{class_val}\"")
                    
                    # Add name if present
                    if "name" in attrs:
                        info_parts.append(f"name=\"{attrs['name']}\"")
                    
                    # Add type if present (for inputs)
                    if "type" in attrs:
                        info_parts.append(f"type=\"{attrs['type']}\"")
                    
                    # Add href if present
                    if "href" in attrs:
                        href_val = attrs["href"]
                        if len(href_val) > 80:
                            href_val = href_val[:80] + "..."
                        info_parts.append(f"href=\"{href_val}\"")
                    
                    # Add aria-label if present (accessibility)
                    if "aria-label" in attrs:
                        aria_val = attrs["aria-label"]
                        if len(aria_val) > 60:
                            aria_val = aria_val[:60] + "..."
                        info_parts.append(f"aria-label=\"{aria_val}\"")
                    
                    # Add role if present
                    if "role" in attrs:
                        info_parts.append(f"role=\"{attrs['role']}\"")
                    
                    # Add text snippet (truncated)
                    if text:
                        snippet = text[:150].replace("\n", " ").strip()
                        if len(text) > 150:
                            snippet += "..."
                        info_parts.append(f"text=\"{snippet}\"")
                    
                    results.append(" ".join(info_parts))
                
                extra = ""
                if len(elements) > limit:
                    extra = f"\n... and {len(elements) - limit} more elements"
                return f"Found {len(elements)} element(s) matching selector '{selector}':\n" + "\n".join(results) + extra

            return self._with_page(lambda page: op(page), wait_timeout=5000)
        except Exception as e:
            logger.error(f"Failed to query selector: {e}")
            return f"Failed to query selector: {str(e)}"

    def _dom_extract_links(self, filter_pattern: str | None = None, limit: int = 50) -> str:
        """Extract links from page, optionally filtered by substring."""
        try:
            async def op(page):
                links = await page.evaluate(
                    """(pattern) => {
                        const patt = pattern ? pattern.toLowerCase() : null;
                        return Array.from(document.querySelectorAll('a[href]')).map((a, idx) => {
                            const text = (a.innerText || '').trim();
                            const href = a.href || '';
                            const title = a.title || '';
                            const keep = !patt || href.toLowerCase().includes(patt) || text.toLowerCase().includes(patt);
                            return {text, href, title, keep};
                        }).filter(l => l.keep);
                    }""",
                    filter_pattern,
                )
                summary = []
                for i, link in enumerate(links[:limit]):
                    label = link["text"][:80].replace("\n", " ")
                    summary.append(f"{i+1}. {label} -> {link['href']}")
                extra = ""
                if len(links) > limit:
                    extra = f"\n... and {len(links) - limit} more links"
                header = f"Found {len(links)} link(s)" + (
                    f" matching '{filter_pattern}'" if filter_pattern else ""
                )
                return header + (":\n" + "\n".join(summary) if summary else "")

            return self._with_page(lambda page: op(page), wait_timeout=5000)
        except Exception as e:
            logger.error(f"Failed to extract links: {e}")
            return f"Failed to extract links: {str(e)}"

    # Temporarily commented out selector-based DOM operations - using BID-based operations instead
    # def _dom_click(
    #     self,
    #     selector: str,
    #     nth: int = 0,
    #     button: str = "left",
    #     click_count: int = 1,
    #     timeout_ms: int = 2000,
    # ) -> str:
    #     """Click a DOM element using a CSS selector (and optional index)."""
    #     try:
    #         async def op(page):
    #             elements = await page.query_selector_all(selector)
    #             if not elements:
    #                 return f"No element found for selector '{selector}'"
    #             idx = min(max(nth, 0), len(elements) - 1)
    #             target = elements[idx]
    #             await target.scroll_into_view_if_needed(timeout=timeout_ms)
    #             await target.click(
    #                 button=button,
    #                 click_count=click_count,
    #                 timeout=timeout_ms,
    #                 force=True,
    #             )
    #             try:
    #                 text = await target.inner_text()
    #                 text = text.strip().replace("\n", " ")
    #             except Exception:
    #                 text = ""
    #             return f"Clicked element {idx+1}/{len(elements)} matching '{selector}' (button={button}, clicks={click_count}). Text: {text[:120]}"

    #         return self._with_page(lambda page: op(page), wait_timeout=5000)
    #     except Exception as e:
    #         logger.error(f"Failed to click selector: {e}")
    #         return f"Failed to click selector: {str(e)}"

    # def _dom_hover(
    #     self,
    #     selector: str,
    #     nth: int = 0,
    #     timeout_ms: int = 2000,
    # ) -> str:
    #     """Hover over a DOM element using a CSS selector (and optional index)."""
    #     try:
    #         async def op(page):
    #             elements = await page.query_selector_all(selector)
    #             if not elements:
    #                 return f"No element found for selector '{selector}'"
    #             idx = min(max(nth, 0), len(elements) - 1)
    #             target = elements[idx]
    #             await target.scroll_into_view_if_needed(timeout=timeout_ms)
    #             await target.hover(timeout=timeout_ms)
    #             try:
    #                 text = await target.inner_text()
    #                 text = text.strip().replace("\n", " ")
    #             except Exception:
    #                 text = ""
    #             return f"Hovered over element {idx+1}/{len(elements)} matching '{selector}'. Text: {text[:120]}"

    #         return self._with_page(lambda page: op(page), wait_timeout=5000)
    #     except Exception as e:
    #         logger.error(f"Failed to hover over selector: {e}")
    #         return f"Failed to hover over selector: {str(e)}"

    # def _dom_type(
    #     self,
    #     selector: str,
    #     text: str,
    #     nth: int = 0,
    #     clear_first: bool = True,
    #     timeout_ms: int = 2000,
    # ) -> str:
    #     """Type text into a DOM element using a CSS selector (and optional index)."""
    #     try:
    #         async def op(page):
    #             elements = await page.query_selector_all(selector)
    #             if not elements:
    #                 return f"No element found for selector '{selector}'"
    #             idx = min(max(nth, 0), len(elements) - 1)
    #             target = elements[idx]
    #             await target.scroll_into_view_if_needed(timeout=timeout_ms)
    #             
    #             if clear_first:
    #                 await target.fill("", timeout=timeout_ms)
    #             
    #             await target.type(text, timeout=timeout_ms)
    #             
    #             try:
    #                 final_value = await target.input_value()
    #             except Exception:
    #                 final_value = text
    #             
    #             return f"Typed into element {idx+1}/{len(elements)} matching '{selector}'. Final value: {final_value[:120]}"

    #         return self._with_page(lambda page: op(page), wait_timeout=5000)
    #     except Exception as e:
    #         logger.error(f"Failed to type into selector: {e}")
    #         return f"Failed to type into selector: {str(e)}"

    # def _dom_press(
    #     self,
    #     key: str,
    #     selector: str | None = None,
    #     nth: int = 0,
    #     timeout_ms: int = 2000,
    # ) -> str:
    #     """Press a key on the page or on a specific element."""
    #     try:
    #         async def op(page):
    #             if selector:
    #                 elements = await page.query_selector_all(selector)
    #                 if not elements:
    #                     return f"No element found for selector '{selector}'"
    #                 idx = min(max(nth, 0), len(elements) - 1)
    #                 target = elements[idx]
    #                 await target.scroll_into_view_if_needed(timeout=timeout_ms)
    #                 await target.press(key, timeout=timeout_ms)
    #                 return f"Pressed key '{key}' on element {idx+1}/{len(elements)} matching '{selector}'"
    #             else:
    #                 await page.keyboard.press(key)
    #                 return f"Pressed key '{key}' on page"

    #         return self._with_page(lambda page: op(page), wait_timeout=5000)
    #     except Exception as e:
    #         logger.error(f"Failed to press key: {e}")
    #         return f"Failed to press key: {str(e)}"

    # def _dom_scroll(
    #     self,
    #     direction: str = "down",
    #     amount: int = 500,
    #     selector: str | None = None,
    #     nth: int = 0,
    #     timeout_ms: int = 2000,
    # ) -> str:
    #     """Scroll the page or a specific element."""
    #     try:
    #         async def op(page):
    #             if selector:
    #                 elements = await page.query_selector_all(selector)
    #                 if not elements:
    #                     return f"No element found for selector '{selector}'"
    #                 idx = min(max(nth, 0), len(elements) - 1)
    #                 target = elements[idx]
    #                 
    #                 if direction == "down":
    #                     await target.evaluate(f"el => el.scrollTop += {amount}")
    #                 elif direction == "up":
    #                     await target.evaluate(f"el => el.scrollTop -= {amount}")
    #                 elif direction == "left":
    #                     await target.evaluate(f"el => el.scrollLeft -= {amount}")
    #                 elif direction == "right":
    #                     await target.evaluate(f"el => el.scrollLeft += {amount}")
    #                 
    #                 return f"Scrolled {direction} by {amount}px on element {idx+1}/{len(elements)} matching '{selector}'"
    #             else:
    #                 if direction == "down":
    #                     await page.evaluate(f"window.scrollBy(0, {amount})")
    #                 elif direction == "up":
    #                     await page.evaluate(f"window.scrollBy(0, -{amount})")
    #                 elif direction == "left":
    #                     await page.evaluate(f"window.scrollBy(-{amount}, 0)")
    #                 elif direction == "right":
    #                     await page.evaluate(f"window.scrollBy({amount}, 0)")
    #                 
    #                 return f"Scrolled page {direction} by {amount}px"

    #         return self._with_page(lambda page: op(page), wait_timeout=5000)
    #     except Exception as e:
    #         logger.error(f"Failed to scroll: {e}")
    #         return f"Failed to scroll: {str(e)}"

    def _dom_mark_elements_and_extract(self, max_elements: int = 100) -> str:
        """Mark interactive elements with unique BIDs and return structured list with context."""
        try:
            async def op(page):
                # JavaScript to inject BIDs and extract interactive elements
                js_code = """
                () => {
                    // Clear previous marks
                    document.querySelectorAll('[data-cocoa-bid]').forEach(el => {
                        el.removeAttribute('data-cocoa-bid');
                    });
                    
                    // Interactive element selectors
                    const interactiveSelectors = [
                        'a[href]',
                        'button',
                        'input',
                        'textarea',
                        'select',
                        '[role="button"]',
                        '[role="link"]',
                        '[role="tab"]',
                        '[role="menuitem"]',
                        '[role="dialog"]',
                        '[role="checkbox"]',
                        '[role="radio"]',
                        '[role="switch"]',
                        '[onclick]',
                        '[contenteditable="true"]',
                        '[class*="close"]',
                        '[class*="dismiss"]',
                        '[class*="cancel"]',
                        '[aria-label*="close" i]',
                        '[aria-label*="dismiss" i]',
                        '[aria-label*="cancel" i]',
                        '[title*="close" i]',
                        '[title*="dismiss" i]',
                        'svg[onclick]',
                        '[data-dismiss]',
                        '[data-close]'
                    ];
                    
                    // Helper function to check if element is interactive
                    function isInteractive(el) {
                        const tag = el.tagName.toLowerCase();
                        const hasClick = el.onclick || el.hasAttribute('onclick');
                        const hasRole = ['button', 'link', 'tab', 'menuitem', 'checkbox', 'radio', 'switch'].includes(el.getAttribute('role'));
                        const isClickable = el.style.cursor === 'pointer' || window.getComputedStyle(el).cursor === 'pointer';
                        const hasCloseIndicator = (el.textContent || '').trim().match(/^[×✕✖✗xX]$/);
                        
                        return hasClick || hasRole || isClickable || hasCloseIndicator;
                    }
                    
                    // Get all potentially interactive elements
                    const directElements = Array.from(document.querySelectorAll(interactiveSelectors.join(',')));
                    
                    // Also check divs and spans with cursor:pointer or close indicators
                    const allDivSpan = Array.from(document.querySelectorAll('div, span, i, svg'));
                    const extraElements = allDivSpan.filter(el => {
                        if (directElements.includes(el)) return false;
                        return isInteractive(el);
                    });
                    
                    const elements = [...directElements, ...extraElements];
                    const results = [];
                    let bid = 1;
                    
                    for (const el of elements) {
                        // Check visibility
                        const rect = el.getBoundingClientRect();
                        const style = window.getComputedStyle(el);
                        
                        // More lenient visibility check
                        if (style.display === 'none' || style.visibility === 'hidden') {
                            continue;
                        }
                        
                        // Allow small elements (close buttons can be small)
                        if (rect.width === 0 && rect.height === 0) {
                            continue;
                        }
                        
                        // Check if element is actually rendered and not completely transparent
                        if (style.opacity === '0') {
                            continue;
                        }
                        
                        // Skip if covered by another element (except for high z-index elements like modals)
                        const zIndex = parseInt(style.zIndex) || 0;
                        if (zIndex < 0) {
                            continue;
                        }
                        
                        // Assign BID
                        const bidStr = `bid${bid}`;
                        el.setAttribute('data-cocoa-bid', bidStr);
                        
                        // Extract element info
                        const tag = el.tagName.toLowerCase();
                        const text = (el.innerText || el.textContent || '').trim().substring(0, 150);
                        const value = el.value || '';
                        const placeholder = el.placeholder || '';
                        const type = el.type || '';
                        const href = el.href || '';
                        const id = el.id || '';
                        const classList = Array.from(el.classList || []).join(' ');
                        const role = el.getAttribute('role') || '';
                        const ariaLabel = el.getAttribute('aria-label') || '';
                        const title = el.title || '';
                        const name = el.name || '';
                        const dataDismiss = el.getAttribute('data-dismiss') || '';
                        const dataClose = el.getAttribute('data-close') || '';
                        
                        // Build readable description
                        let description = `<${tag}>`;
                        if (id) description += ` id="${id}"`;
                        if (classList) description += ` class="${classList.substring(0, 80)}"`;
                        if (type) description += ` type="${type}"`;
                        if (role) description += ` role="${role}"`;
                        if (ariaLabel) description += ` aria-label="${ariaLabel}"`;
                        if (title) description += ` title="${title}"`;
                        if (name) description += ` name="${name}"`;
                        if (dataDismiss) description += ` data-dismiss="${dataDismiss}"`;
                        if (dataClose) description += ` data-close="${dataClose}"`;
                        if (text) description += ` text="${text}"`;
                        if (value) description += ` value="${value}"`;
                        if (placeholder) description += ` placeholder="${placeholder}"`;
                        if (href) description += ` href="${href.substring(0, 80)}"`;
                        
                        results.push({
                            bid: bidStr,
                            description: description
                        });
                        
                        bid++;
                        if (bid > """ + str(max_elements) + """) break;
                    }
                    
                    return results;
                }
                """
                
                elements_info = await page.evaluate(js_code)
                
                if not elements_info:
                    return "No interactive elements found on page"
                
                # Format output
                lines = [f"Found {len(elements_info)} interactive element(s):"]
                for elem in elements_info:
                    lines.append(f"[{elem['bid']}] {elem['description']}")
                
                return "\n".join(lines)
            
            return self._with_page(lambda page: op(page), wait_timeout=5000)
        except Exception as e:
            logger.error(f"Failed to mark elements and extract: {e}")
            return f"Failed to mark elements and extract: {str(e)}"

    def _dom_click(self, bid: str, button: str = "left", click_count: int = 1, timeout_ms: int = 2000) -> str:
        """Click a DOM element using a BID."""
        try:
            async def op(page):
                selector = f'[data-cocoa-bid="{bid}"]'
                element = await page.query_selector(selector)
                if not element:
                    return f"ERROR: No element found with BID '{bid}'. This BID is stale/invalid. DO NOT retry this BID. You MUST run dom_mark_elements() again to get fresh BIDs, then find your target element in the new list and use its new BID."
                
                # Get element info before clicking
                tag_name = await element.evaluate('el => el.tagName.toLowerCase()')
                element_visible = await element.is_visible()
                element_enabled = await element.is_enabled()
                
                try:
                    text_before = await element.inner_text()
                    text_before = text_before.strip().replace("\n", " ")
                except Exception:
                    text_before = ""
                
                # Try multiple click strategies
                click_success = False
                error_msg = ""
                
                # Strategy 1: Standard click with scroll
                try:
                    await element.scroll_into_view_if_needed(timeout=timeout_ms)
                    await element.click(button=button, click_count=click_count, timeout=timeout_ms)
                    click_success = True
                except Exception as e1:
                    error_msg = str(e1)
                    
                    # Strategy 2: Force click
                    try:
                        await element.click(button=button, click_count=click_count, timeout=timeout_ms, force=True)
                        click_success = True
                        error_msg = ""
                    except Exception as e2:
                        error_msg = str(e2)
                        
                        # Strategy 3: JS click for stubborn elements
                        try:
                            await element.evaluate('el => el.click()')
                            click_success = True
                            error_msg = ""
                        except Exception as e3:
                            error_msg = f"All click strategies failed. Last error: {str(e3)}"
                
                if not click_success:
                    return f"Failed to click BID '{bid}' ({tag_name}). Element visible: {element_visible}, enabled: {element_enabled}. Error: {error_msg}"
                
                # Get element state after clicking (if still exists)
                try:
                    await page.wait_for_timeout(300)  # Short wait for UI update
                    text_after = await element.inner_text()
                    text_after = text_after.strip().replace("\n", " ")
                    if text_after != text_before:
                        return f"Clicked element with BID '{bid}' (button={button}, clicks={click_count}). Text changed: '{text_before[:60]}' -> '{text_after[:60]}'"
                except Exception:
                    # Element might be removed after click (e.g., close button)
                    return f"Clicked element with BID '{bid}' (button={button}, clicks={click_count}). Element removed from DOM (likely a close/dismiss button or navigation)."
                
                return f"Clicked element with BID '{bid}' (button={button}, clicks={click_count}). Text: {text_before[:120]}"
            
            return self._with_page(lambda page: op(page), wait_timeout=5000)
        except Exception as e:
            logger.error(f"Failed to click BID: {e}")
            return f"Failed to click BID: {str(e)}"

    def _dom_hover(self, bid: str, timeout_ms: int = 2000) -> str:
        """Hover over a DOM element using a BID."""
        try:
            async def op(page):
                selector = f'[data-cocoa-bid="{bid}"]'
                element = await page.query_selector(selector)
                if not element:
                    return f"ERROR: No element found with BID '{bid}'. This BID is stale/invalid. DO NOT retry this BID. You MUST run dom_mark_elements() again to get fresh BIDs."
                
                await element.scroll_into_view_if_needed(timeout=timeout_ms)
                await element.hover(timeout=timeout_ms)
                
                try:
                    text = await element.inner_text()
                    text = text.strip().replace("\n", " ")
                except Exception:
                    text = ""
                
                return f"Hovered over element with BID '{bid}'. Text: {text[:120]}"
            
            return self._with_page(lambda page: op(page), wait_timeout=5000)
        except Exception as e:
            logger.error(f"Failed to hover BID: {e}")
            return f"Failed to hover BID: {str(e)}"

    def _dom_type(self, bid: str, text: str, clear_first: bool = True, timeout_ms: int = 2000) -> str:
        """Type text into a DOM element using a BID."""
        try:
            async def op(page):
                selector = f'[data-cocoa-bid="{bid}"]'
                element = await page.query_selector(selector)
                if not element:
                    return f"ERROR: No element found with BID '{bid}'. This BID is stale/invalid. DO NOT retry this BID. You MUST run dom_mark_elements() again to get fresh BIDs."
                
                await element.scroll_into_view_if_needed(timeout=timeout_ms)
                
                if clear_first:
                    await element.fill("", timeout=timeout_ms)
                
                await element.type(text, timeout=timeout_ms)
                
                try:
                    final_value = await element.input_value()
                except Exception:
                    final_value = text
                
                return f"Typed into element with BID '{bid}'. Final value: {final_value[:120]}"
            
            return self._with_page(lambda page: op(page), wait_timeout=5000)
        except Exception as e:
            logger.error(f"Failed to type into BID: {e}")
            return f"Failed to type into BID: {str(e)}"

    def _dom_press(self, key: str, bid: str | None = None, timeout_ms: int = 2000) -> str:
        """Press a key on a DOM element using a BID or on the page."""
        try:
            async def op(page):
                if bid:
                    selector = f'[data-cocoa-bid="{bid}"]'
                    element = await page.query_selector(selector)
                    if not element:
                        return f"ERROR: No element found with BID '{bid}'. This BID is stale/invalid. DO NOT retry this BID. You MUST run dom_mark_elements() again to get fresh BIDs."
                    
                    await element.scroll_into_view_if_needed(timeout=timeout_ms)
                    await element.press(key, timeout=timeout_ms)
                    
                    return f"Pressed key '{key}' on element with BID '{bid}'"
                else:
                    await page.keyboard.press(key)
                    return f"Pressed key '{key}' on page"
            
            return self._with_page(lambda page: op(page), wait_timeout=5000)
        except Exception as e:
            logger.error(f"Failed to press key: {e}")
            return f"Failed to press key: {str(e)}"

    def _dom_scroll(self, bid: str | None = None, direction: str = "down", amount: int = 500, timeout_ms: int = 2000) -> str:
        """Scroll a DOM element or the page using a BID."""
        try:
            async def op(page):
                if bid:
                    selector = f'[data-cocoa-bid="{bid}"]'
                    element = await page.query_selector(selector)
                    if not element:
                        return f"ERROR: No element found with BID '{bid}'. This BID is stale/invalid. DO NOT retry this BID. You MUST run dom_mark_elements() again to get fresh BIDs."
                    
                    # Get scroll info before scrolling
                    scroll_info_before = await element.evaluate("""
                        el => ({
                            scrollTop: el.scrollTop,
                            scrollLeft: el.scrollLeft,
                            scrollHeight: el.scrollHeight,
                            scrollWidth: el.scrollWidth,
                            clientHeight: el.clientHeight,
                            clientWidth: el.clientWidth
                        })
                    """)
                    
                    if direction == "down":
                        await element.evaluate(f"el => el.scrollTop += {amount}")
                    elif direction == "up":
                        await element.evaluate(f"el => el.scrollTop -= {amount}")
                    elif direction == "left":
                        await element.evaluate(f"el => el.scrollLeft -= {amount}")
                    elif direction == "right":
                        await element.evaluate(f"el => el.scrollLeft += {amount}")
                    
                    # Get scroll info after scrolling
                    scroll_info_after = await element.evaluate("""
                        el => ({
                            scrollTop: el.scrollTop,
                            scrollLeft: el.scrollLeft,
                            scrollHeight: el.scrollHeight,
                            scrollWidth: el.scrollWidth,
                            clientHeight: el.clientHeight,
                            clientWidth: el.clientWidth
                        })
                    """)
                    
                    # Calculate scroll position and limits
                    if direction in ["up", "down"]:
                        max_scroll = scroll_info_after["scrollHeight"] - scroll_info_after["clientHeight"]
                        current = scroll_info_after["scrollTop"]
                        at_top = current <= 0
                        at_bottom = current >= max_scroll - 1
                        position_info = f"Position: {current}/{max_scroll}"
                        if at_top:
                            position_info += " (at top)"
                        elif at_bottom:
                            position_info += " (at bottom)"
                        else:
                            percent = int((current / max_scroll) * 100) if max_scroll > 0 else 0
                            position_info += f" ({percent}%)"
                    else:
                        max_scroll = scroll_info_after["scrollWidth"] - scroll_info_after["clientWidth"]
                        current = scroll_info_after["scrollLeft"]
                        at_left = current <= 0
                        at_right = current >= max_scroll - 1
                        position_info = f"Position: {current}/{max_scroll}"
                        if at_left:
                            position_info += " (at left)"
                        elif at_right:
                            position_info += " (at right)"
                        else:
                            percent = int((current / max_scroll) * 100) if max_scroll > 0 else 0
                            position_info += f" ({percent}%)"
                    
                    return f"Scrolled {direction} by {amount}px on element with BID '{bid}'. {position_info}"
                else:
                    # Scroll the page - try multiple strategies for modern SPA pages
                    scroll_info_before = await page.evaluate("""
                        () => ({
                            scrollY: window.scrollY,
                            scrollX: window.scrollX,
                            scrollHeight: document.documentElement.scrollHeight,
                            scrollWidth: document.documentElement.scrollWidth,
                            clientHeight: window.innerHeight,
                            clientWidth: window.innerWidth
                        })
                    """)
                    
                    # Strategy 1: Try scrolling the main scrollable container if page itself isn't scrollable
                    page_scrollable_x = scroll_info_before["scrollWidth"] > scroll_info_before["clientWidth"]
                    page_scrollable_y = scroll_info_before["scrollHeight"] > scroll_info_before["clientHeight"]
                    
                    scroll_success = False
                    scroll_target = "page"
                    
                    # If page isn't scrollable in target direction, try to find and scroll a container
                    if (direction in ["left", "right"] and not page_scrollable_x) or \
                       (direction in ["up", "down"] and not page_scrollable_y):
                        # Find and scroll the largest scrollable container
                        container_scrolled = await page.evaluate(f"""
                            (direction, amount) => {{
                                const allElements = document.querySelectorAll('*');
                                let bestContainer = null;
                                let bestSize = 0;
                                
                                for (const el of allElements) {{
                                    if (el === document.body || el === document.documentElement) continue;
                                    
                                    const style = window.getComputedStyle(el);
                                    const overflowX = style.overflowX;
                                    const overflowY = style.overflowY;
                                    
                                    let isScrollable = false;
                                    let scrollableSize = 0;
                                    
                                    if (direction === 'left' || direction === 'right') {{
                                        isScrollable = (overflowX === 'auto' || overflowX === 'scroll') && 
                                                      el.scrollWidth > el.clientWidth;
                                        scrollableSize = el.scrollWidth - el.clientWidth;
                                    }} else {{
                                        isScrollable = (overflowY === 'auto' || overflowY === 'scroll') && 
                                                      el.scrollHeight > el.clientHeight;
                                        scrollableSize = el.scrollHeight - el.clientHeight;
                                    }}
                                    
                                    if (isScrollable && scrollableSize > bestSize) {{
                                        bestContainer = el;
                                        bestSize = scrollableSize;
                                    }}
                                }}
                                
                                if (bestContainer) {{
                                    if (direction === 'down') {{
                                        bestContainer.scrollTop += amount;
                                    }} else if (direction === 'up') {{
                                        bestContainer.scrollTop -= amount;
                                    }} else if (direction === 'left') {{
                                        bestContainer.scrollLeft -= amount;
                                    }} else if (direction === 'right') {{
                                        bestContainer.scrollLeft += amount;
                                    }}
                                    return true;
                                }}
                                return false;
                            }}
                        """, direction, amount)
                        
                        if container_scrolled:
                            scroll_success = True
                            scroll_target = "container"
                    
                    # Strategy 2: Scroll the page/window (if not already scrolled via container)
                    if not scroll_success:
                        if direction == "down":
                            await page.evaluate(f"window.scrollBy(0, {amount})")
                        elif direction == "up":
                            await page.evaluate(f"window.scrollBy(0, -{amount})")
                        elif direction == "left":
                            await page.evaluate(f"window.scrollBy(-{amount}, 0)")
                        elif direction == "right":
                            await page.evaluate(f"window.scrollBy({amount}, 0)")
                    
                    # Wait a bit for scroll to complete
                    await page.wait_for_timeout(100)
                    
                    # Get scroll info after scrolling
                    scroll_info_after = await page.evaluate("""
                        () => ({
                            scrollY: window.scrollY,
                            scrollX: window.scrollX,
                            scrollHeight: document.documentElement.scrollHeight,
                            scrollWidth: document.documentElement.scrollWidth,
                            clientHeight: window.innerHeight,
                            clientWidth: window.innerWidth
                        })
                    """)
                    
                    # Calculate scroll position and limits
                    if direction in ["up", "down"]:
                        max_scroll = scroll_info_after["scrollHeight"] - scroll_info_after["clientHeight"]
                        current = scroll_info_after["scrollY"]
                        at_top = current <= 0
                        at_bottom = current >= max_scroll - 1
                        position_info = f"Position: {current}/{max_scroll}"
                        if at_top:
                            position_info += " (at top)"
                        elif at_bottom:
                            position_info += " (at bottom)"
                        else:
                            percent = int((current / max_scroll) * 100) if max_scroll > 0 else 0
                            position_info += f" ({percent}%)"
                    else:
                        max_scroll = scroll_info_after["scrollWidth"] - scroll_info_after["clientWidth"]
                        current = scroll_info_after["scrollX"]
                        at_left = current <= 0
                        at_right = current >= max_scroll - 1
                        position_info = f"Position: {current}/{max_scroll}"
                        if at_left:
                            position_info += " (at left)"
                        elif at_right:
                            position_info += " (at right)"
                        else:
                            percent = int((current / max_scroll) * 100) if max_scroll > 0 else 0
                            position_info += f" ({percent}%)"
                    
                    # Check if scroll actually happened
                    scroll_changed = False
                    if direction in ["up", "down"]:
                        scroll_changed = abs(scroll_info_after["scrollY"] - scroll_info_before["scrollY"]) > 1
                    else:
                        scroll_changed = abs(scroll_info_after["scrollX"] - scroll_info_before["scrollX"]) > 1
                    
                    if not scroll_changed and max_scroll <= 0:
                        return f"WARNING: Page is not scrollable in {direction} direction. Content fits within viewport (scrollWidth={scroll_info_after['scrollWidth']}, clientWidth={scroll_info_after['clientWidth']}). Try scrolling a specific element by providing its BID from dom_mark_elements()."
                    
                    return f"Scrolled page {direction} by {amount}px ({scroll_target}). {position_info}"
            
            return self._with_page(lambda page: op(page), wait_timeout=5000)
        except Exception as e:
            logger.error(f"Failed to scroll: {e}")
            return f"Failed to scroll: {str(e)}"

    def _navigate_to_url(self, url: str) -> str:
        """Navigate browser to a URL via CDP + Playwright."""
        if not url:
            raise ValueError("browser_navigate requires 'url' parameter")
        try:
            from playwright.async_api import async_playwright

            async def op():
                browser_info = self.sdk_client.browser.get_info().data
                async with async_playwright() as p:
                    browser = await p.chromium.connect_over_cdp(browser_info.cdp_url)
                    try:
                        context = browser.contexts[0] if browser.contexts else await browser.new_context()
                        page = context.pages[0] if context.pages else await context.new_page()
                        await page.goto(url, wait_until="domcontentloaded")
                        return f"Successfully navigated to {url}"
                    finally:
                        await browser.close()

            return self._run_async(op())
        except Exception as e:
            logger.error(f"Failed to navigate: {e}")
            logger.exception("Full traceback:")
            return f"Failed to navigate: {str(e)}"

    def get_feedback(self, action: Dict[str, Any]) -> Dict[str, Any]:
        """Get feedback from executing a browser action.

        Args:
            action: The action to execute (can be a dict with tool_calls or single action)

        Returns:
            Dictionary with done status and feedback message
        """
        # Initialize SDK client if not already done
        self._initialize_sdk_client()

        # Handle task_complete action
        if action.get("action_type") == "task_complete" or action.get("command") == "exit" or action.get("action_type") == "exit":
            logger.debug("Task completed")
            result_text = action.get("result")
            if result_text:
                logger.debug(f"Task completed with result: {result_text[:200]}...")
                feedback = {
                    "done": True,
                    "message": f"Task completed. Result: {result_text}"
                }
                # Store result in feedback for later extraction
                feedback["task_result"] = result_text
            else:
                feedback = {
                    "done": True,
                    "message": "Task completed"
                }
            self.execution_history.append({
                "action": action,
                "feedback": feedback
            })
            return feedback

        # DOM-based actions (selector/text-based, no coordinates)
        if action.get("action_type") == "dom_get_text":
            message = self._dom_get_text()
            feedback = {"done": False, "message": message}
            self.execution_history.append({"action": action, "feedback": feedback})
            return feedback

        if action.get("action_type") == "dom_get_html":
            message = self._dom_get_html()
            feedback = {"done": False, "message": message}
            self.execution_history.append({"action": action, "feedback": feedback})
            return feedback

        if action.get("action_type") == "dom_query_selector":
            selector = action.get("selector")
            limit = action.get("limit", 20)
            if not selector:
                feedback = {"done": False, "message": "selector is required for dom_query_selector"}
            else:
                message = self._dom_query_selector(selector, limit=limit)
                feedback = {"done": False, "message": message}
            self.execution_history.append({"action": action, "feedback": feedback})
            return feedback

        if action.get("action_type") == "dom_extract_links":
            pattern = action.get("filter_pattern")
            limit = action.get("limit", 50)
            message = self._dom_extract_links(filter_pattern=pattern, limit=limit)
            feedback = {"done": False, "message": message}
            self.execution_history.append({"action": action, "feedback": feedback})
            return feedback

        # Temporarily commented out selector-based DOM action handlers - using BID-based operations instead
        # if action.get("action_type") == "dom_click":
        #     selector = action.get("selector")
        #     if not selector:
        #         feedback = {"done": False, "message": "selector is required for dom_click"}
        #     else:
        #         message = self._dom_click(
        #             selector=selector,
        #             nth=action.get("nth", 0),
        #             button=action.get("button", "left"),
        #             click_count=action.get("click_count", 1),
        #             timeout_ms=action.get("timeout_ms", 2000),
        #         )
        #         feedback = {"done": False, "message": message}
        #     self.execution_history.append({"action": action, "feedback": feedback})
        #     return feedback

        # if action.get("action_type") == "dom_hover":
        #     selector = action.get("selector")
        #     if not selector:
        #         feedback = {"done": False, "message": "selector is required for dom_hover"}
        #     else:
        #         message = self._dom_hover(
        #             selector=selector,
        #             nth=action.get("nth", 0),
        #             timeout_ms=action.get("timeout_ms", 2000),
        #         )
        #         feedback = {"done": False, "message": message}
        #     self.execution_history.append({"action": action, "feedback": feedback})
        #     return feedback

        # if action.get("action_type") == "dom_type":
        #     selector = action.get("selector")
        #     text = action.get("text")
        #     if not selector:
        #         feedback = {"done": False, "message": "selector is required for dom_type"}
        #     elif text is None:
        #         feedback = {"done": False, "message": "text is required for dom_type"}
        #     else:
        #         message = self._dom_type(
        #             selector=selector,
        #             text=text,
        #             nth=action.get("nth", 0),
        #             clear_first=action.get("clear_first", True),
        #             timeout_ms=action.get("timeout_ms", 2000),
        #         )
        #         feedback = {"done": False, "message": message}
        #     self.execution_history.append({"action": action, "feedback": feedback})
        #     return feedback

        # if action.get("action_type") == "dom_press":
        #     key = action.get("key")
        #     if not key:
        #         feedback = {"done": False, "message": "key is required for dom_press"}
        #     else:
        #         message = self._dom_press(
        #             key=key,
        #             selector=action.get("selector"),
        #             nth=action.get("nth", 0),
        #             timeout_ms=action.get("timeout_ms", 2000),
        #         )
        #         feedback = {"done": False, "message": message}
        #     self.execution_history.append({"action": action, "feedback": feedback})
        #     return feedback

        # if action.get("action_type") == "dom_scroll":
        #     message = self._dom_scroll(
        #         direction=action.get("direction", "down"),
        #         amount=action.get("amount", 500),
        #         selector=action.get("selector"),
        #         nth=action.get("nth", 0),
        #         timeout_ms=action.get("timeout_ms", 2000),
        #     )
        #     feedback = {"done": False, "message": message}
        #     self.execution_history.append({"action": action, "feedback": feedback})
        #     return feedback

        if action.get("action_type") == "dom_mark_elements":
            max_elements = action.get("max_elements", 100)
            message = self._dom_mark_elements_and_extract(max_elements=max_elements)
            feedback = {"done": False, "message": message}
            self.execution_history.append({"action": action, "feedback": feedback})
            return feedback

        if action.get("action_type") == "dom_click":
            bid = action.get("bid")
            if not bid:
                feedback = {"done": False, "message": "bid is required for dom_click"}
            else:
                message = self._dom_click(
                    bid=bid,
                    button=action.get("button", "left"),
                    click_count=action.get("click_count", 1),
                    timeout_ms=action.get("timeout_ms", 2000),
                )
                feedback = {"done": False, "message": message}
            self.execution_history.append({"action": action, "feedback": feedback})
            return feedback

        if action.get("action_type") == "dom_hover":
            bid = action.get("bid")
            if not bid:
                feedback = {"done": False, "message": "bid is required for dom_hover"}
            else:
                message = self._dom_hover(
                    bid=bid,
                    timeout_ms=action.get("timeout_ms", 2000),
                )
                feedback = {"done": False, "message": message}
            self.execution_history.append({"action": action, "feedback": feedback})
            return feedback

        if action.get("action_type") == "dom_type":
            bid = action.get("bid")
            text = action.get("text")
            if not bid:
                feedback = {"done": False, "message": "bid is required for dom_type"}
            elif text is None:
                feedback = {"done": False, "message": "text is required for dom_type"}
            else:
                message = self._dom_type(
                    bid=bid,
                    text=text,
                    clear_first=action.get("clear_first", True),
                    timeout_ms=action.get("timeout_ms", 2000),
                )
                feedback = {"done": False, "message": message}
            self.execution_history.append({"action": action, "feedback": feedback})
            return feedback

        if action.get("action_type") == "dom_press":
            key = action.get("key")
            bid = action.get("bid")
            if not key:
                feedback = {"done": False, "message": "key is required for dom_press"}
            else:
                message = self._dom_press(
                    key=key,
                    bid=bid,
                    timeout_ms=action.get("timeout_ms", 2000),
                )
                feedback = {"done": False, "message": message}
            self.execution_history.append({"action": action, "feedback": feedback})
            return feedback

        if action.get("action_type") == "dom_scroll":
            message = self._dom_scroll(
                bid=action.get("bid"),
                direction=action.get("direction", "down"),
                amount=action.get("amount", 500),
                timeout_ms=action.get("timeout_ms", 2000),
            )
            feedback = {"done": False, "message": message}
            self.execution_history.append({"action": action, "feedback": feedback})
            return feedback

        if action.get("action_type") == "browser_navigate":
            url = action.get("url")
            message = self._navigate_to_url(url)
            feedback = {"done": False, "message": message}
            self.execution_history.append({"action": action, "feedback": feedback})
            return feedback

        # Handle screenshot action
        if action.get("action_type") == "browser_screenshot":
            base64_image, message = self._take_screenshot()
            feedback = {
                "done": False,
                "message": message
            } # 只将message作为feedback中的message，image_base64作为单独的key-value pair image_base64
            # Add image_base64 if screenshot was successful
            if base64_image:
                feedback["image_base64"] = base64_image
            self.execution_history.append({
                "action": action,
                "feedback": feedback
            })
            logger.debug(f"Feedback (OBSERVATION): \n{colorize(json.dumps({**feedback, 'image_base64': f'<{len(base64_image)} bytes>' if base64_image else None}, indent=2), 'YELLOW')}")
            return feedback

        # Handle get_viewport_info action
        if action.get("action_type") == "browser_get_viewport_info":
            message = self._get_browser_info()
            feedback = {
                "done": False,
                "message": message
            }
            self.execution_history.append({
                "action": action,
                "feedback": feedback
            })
            logger.debug(f"Feedback (OBSERVATION): \n{colorize(json.dumps(feedback, indent=2), 'YELLOW')}")
            return feedback

        try:
            # Execute the browser action
            browser_action = self._construct_browser_action(action)
            response = self.sdk_client.browser.execute_action(request=browser_action)
            
            output = f"Action executed successfully. Response: {response}"
            feedback = {
                "done": False,
                "message": output,
            }
            
            # Record this action-feedback pair
            self.execution_history.append({
                "action": action,
                "feedback": feedback
            })

            logger.debug(f"Feedback (OBSERVATION): \n{colorize(json.dumps(feedback, indent=2), 'YELLOW')}")
            return feedback

        except Exception as e:
            logger.error(f"Error executing browser action: {e}")
            logger.exception("Full traceback:")
            feedback = {
                "done": False,
                "message": f"Error: {str(e)}"
            }
            self.execution_history.append({
                "action": action,
                "feedback": feedback
            })
        return feedback

    def get_history(self) -> list[Dict[str, Any]]:
        """Get the recorded execution history of actions and feedbacks."""
        return self.execution_history

    def clear_history(self) -> None:
        """Clear the execution history."""
        logger.debug(f"Clearing execution history ({len(self.execution_history)} entries)")
        self.execution_history = []

    def create_docker_environment(self, task: Dict[str, Any], wait_time: int = 60) -> bool:
        """
        Create and start an agent server container using task's dockerfile.

        Args:
            task: Task object containing task_dir (path to task directory with dockerfile)
            wait_time: Time to wait for server to be ready (default: 60 seconds)

        Returns:
            True if successful, False otherwise
        """
        if not super().create_docker_environment(task, wait_time):
            return False
        # Clear execution history for new task
        self.clear_history()
        # Initialize SDK client after docker is ready
        self._initialize_sdk_client()
        return True

class UnifiedSandboxClient(SandboxClient):
    """Unified client that can handle browser, file, code, and shell operations."""
    
    def __init__(self, sandbox_config: Dict[str, Any] | None = None, **kwargs):
        super().__init__(sandbox_config, **kwargs)
        self.execution_history: list[Dict[str, Any]] = []
        self.sdk_client: Optional[Sandbox] = None
        
        # Session IDs for stateful operations
        self.shell_session_id: Optional[str] = None
        self.jupyter_session_id: Optional[str] = None
    
    def _initialize_sdk_client(self) -> None:
        """Initialize the AIO Sandbox SDK client and create sessions."""
        if self.sdk_client is None:
            self.sdk_client = Sandbox(base_url=self.base_url)
            logger.debug(f"Initialized Sandbox SDK client with base_url: {self.base_url}")
            
            # Create shell session
            try:
                session = self.sdk_client.shell.create_session(exec_dir="/home/gem")
                self.shell_session_id = session.data.session_id
                logger.debug(f"Created shell session: {self.shell_session_id}")
            except Exception as e:
                logger.warning(f"Failed to create shell session: {e}")
            
            # Create Jupyter session
            try:
                session = self.sdk_client.jupyter.create_session(kernel_name="python3")
                self.jupyter_session_id = session.data.session_id
                logger.debug(f"Created Jupyter session: {self.jupyter_session_id}")
            except Exception as e:
                logger.warning(f"Failed to create Jupyter session: {e}")
    
    def get_feedback(self, action: Dict[str, Any]) -> Dict[str, Any]:
        """Get feedback from executing any type of action.
        
        Determines the action type and routes to appropriate handler.
        """
        self._initialize_sdk_client()
        
        action_type = action.get("action_type")
        
        # Handle task_complete action
        if action_type == "task_complete" or action_type == "exit":
            logger.debug("Task completed")
            result_text = action.get("result")
            if result_text:
                logger.debug(f"Task completed with result: {result_text[:200]}...")
                feedback = {
                    "done": True,
                    "message": f"Task completed. Result: {result_text}"
                }
                # Store result in feedback for later extraction
                feedback["task_result"] = result_text
            else:
                feedback = {
                    "done": True,
                    "message": "Task completed"
                }
            self.execution_history.append({"action": action, "feedback": feedback})
            return feedback
        
        # Route to appropriate handler based on action type
        try:
            # Browser actions
            if action_type in ["browser_click", "browser_type", "browser_press", "browser_key_down", "browser_key_up", "browser_hotkey",
                              "browser_scroll", "browser_move_to", "browser_move_rel", "browser_drag_to", "browser_drag_rel",
                              "browser_wait",
                              "dom_get_text", "dom_get_html", "dom_query_selector",
                              "dom_extract_links", "dom_mark_elements", "dom_click", "dom_hover", "dom_type", "dom_press", "dom_scroll",
                              "browser_navigate",
                              "browser_screenshot", "browser_get_viewport_info",
                              ]:
                return self._handle_browser_action(action)
            
            # File actions
            elif action_type in ["file_read", "file_write", "file_list",
                               "replace_in_file", "search_in_file", "find_files", 
                               "str_replace_editor", "image_read"]:
                return self._handle_file_action(action)
            
            # Code actions
            elif action_type in ["code_execute"]:
                return self._handle_code_action(action)
            
            # Shell actions
            elif action_type in ["shell_execute"] or action.get("command"):
                return self._handle_shell_action(action)
            
            else:
                message = f"Unknown action type: {action_type}"
                feedback = {"done": False, "message": message}
                self.execution_history.append({"action": action, "feedback": feedback})
                return feedback
        
        except Exception as e:
            logger.error(f"Error executing action: {e}")
            feedback = {"done": False, "message": f"Error: {str(e)}"}
            self.execution_history.append({"action": action, "feedback": feedback})
            return feedback
    
    def take_screenshot(self) -> tuple[str, str]:
        """Take a screenshot and return base64 encoded string and status message.
        
        Returns:
            Tuple of (base64_encoded_image, status_message)
        """
        self._initialize_sdk_client()
        try:
            import base64
            screenshot_data = b""
            for chunk in self.sdk_client.browser.screenshot():
                screenshot_data += chunk
            
            # Encode to base64
            base64_image = base64.b64encode(screenshot_data).decode('utf-8')
            status_message = f"Screenshot taken successfully ({len(screenshot_data)} bytes)"
            return base64_image, status_message
        except Exception as e:
            logger.error(f"Failed to take screenshot: {e}")
            return "", f"Failed to take screenshot: {str(e)}"
    
    def _handle_browser_action(self, action: Dict[str, Any]) -> Dict[str, Any]:
        """Handle browser-specific actions."""
        # Reuse BrowserSandboxClient logic
        browser_client = BrowserSandboxClient.__new__(BrowserSandboxClient)
        browser_client.sdk_client = self.sdk_client
        browser_client.execution_history = []
        feedback = browser_client.get_feedback(action)
        
        # Merge history
        self.execution_history.extend(browser_client.execution_history)
        return feedback
    
    def _handle_file_action(self, action: Dict[str, Any]) -> Dict[str, Any]:
        """Handle file-specific actions."""
        action_type = action.get("action_type")
        
        try:
            if action_type == "file_read":
                file_path = action.get("path") or action.get("file")
                if not file_path:
                    raise ValueError("file_read requires 'path' or 'file' parameter")
                result = self.sdk_client.file.read_file(file=file_path)
                content = result.data.content
                # Return full content for small files, summary for large files
                if len(content) > 5000:
                    message = f"File content (first 5000 chars):\n{content[:5000]}\n... (truncated, total {len(content)} chars)"
                else:
                    message = f"File content:\n{content}"
                
            elif action_type == "file_write":
                file_path = action.get("path") or action.get("file")
                content = action.get("content")
                if not file_path:
                    raise ValueError("file_write requires 'path' or 'file' parameter")
                if content is None:
                    raise ValueError("file_write requires 'content' parameter")
                result = self.sdk_client.file.write_file(file=file_path, content=content)
                message = f"Successfully wrote to {file_path}"
                
            elif action_type == "file_list":
                path = action.get("path")
                if not path:
                    raise ValueError("file_list requires 'path' parameter")
                result = self.sdk_client.file.list_path(path=path)
                files = [f.name for f in result.data.files]
                message = f"Files in {path} ({len(files)} items):\n" + "\n".join(files[:50]) + (f"\n... and {len(files) - 50} more" if len(files) > 50 else "")
            
            elif action_type == "replace_in_file":
                file_path = action.get("file")
                old_str = action.get("old_text") or action.get("old_str")  # Support both for compatibility
                new_str = action.get("new_text") or action.get("new_str")  # Support both for compatibility
                if not file_path:
                    raise ValueError("replace_in_file requires 'file' parameter")
                if old_str is None:
                    raise ValueError("replace_in_file requires 'old_text' or 'old_str' parameter")
                if new_str is None:
                    raise ValueError("replace_in_file requires 'new_text' or 'new_str' parameter")
                result = self.sdk_client.file.replace_in_file(
                    file=file_path,
                    old_str=old_str,
                    new_str=new_str
                )
                message = f"Successfully replaced text in {file_path}"
                
            elif action_type == "search_in_file":
                file_path = action.get("file")
                regex = action.get("pattern") or action.get("regex")  # Support both for compatibility
                if not file_path:
                    raise ValueError("search_in_file requires 'file' parameter")
                if not regex:
                    raise ValueError("search_in_file requires 'pattern' or 'regex' parameter")
                result = self.sdk_client.file.search_in_file(
                    file=file_path,
                    regex=regex
                )
                matches = result.data.matches if hasattr(result.data, 'matches') else []
                message = f"Found {len(matches)} matches for '{regex}' in {file_path}"
                
            elif action_type == "find_files":
                path = action.get("path")
                glob_pattern = action.get("glob")
                if not path:
                    raise ValueError("find_files requires 'path' parameter")
                if not glob_pattern:
                    raise ValueError("find_files requires 'glob' parameter")
                result = self.sdk_client.file.find_files(
                    path=path,
                    glob=glob_pattern
                )
                files = result.data.files if result.data.files else []
                message = f"Found {len(files)} files matching '{glob_pattern}'"

            elif action_type == "str_replace_editor":
                from agent_sandbox.file.types import Command
                command = action.get("command")
                path = action.get("path")
                if not command:
                    raise ValueError("str_replace_editor requires 'command' parameter")
                if not path:
                    raise ValueError("str_replace_editor requires 'path' parameter")
                
                command_map = {
                    "view": Command.VIEW,
                    "create": Command.CREATE,
                    "str_replace": Command.STR_REPLACE,
                    "insert": Command.INSERT,
                    "undo_edit": Command.UNDO_EDIT
                }
                if command not in command_map:
                    raise ValueError(f"str_replace_editor: invalid command '{command}'. Valid commands: {list(command_map.keys())}")
                cmd_enum = command_map[command]
                
                kwargs = {"command": cmd_enum, "path": path}
                if action.get("file_text"):
                    kwargs["file_text"] = action.get("file_text")
                if action.get("old_str"):
                    kwargs["old_str"] = action.get("old_str")
                if action.get("new_str"):
                    kwargs["new_str"] = action.get("new_str")
                if action.get("insert_line"):
                    kwargs["insert_line"] = action.get("insert_line")
                if action.get("view_range"):
                    kwargs["view_range"] = action.get("view_range")
                
                result = self.sdk_client.file.str_replace_editor(**kwargs)
                message = f"Editor command '{command}' executed on {path}"
            
            elif action_type == "image_read":
                import base64
                file_path = action.get("path") or action.get("file")
                if not file_path:
                    raise ValueError("image_read requires 'path' or 'file' parameter")
                
                # Download the image file as binary data
                image_data = b""
                for chunk in self.sdk_client.file.download_file(path=file_path):
                    image_data += chunk
                
                if not image_data:
                    raise ValueError(f"Failed to read image file: {file_path} or file is empty")
                
                # Encode to base64
                base64_image = base64.b64encode(image_data).decode('utf-8')
                message = f"Successfully read image from {file_path} ({len(image_data)} bytes)"
                
                # Return feedback with image_base64 (similar to screenshot)
                feedback = {"done": False, "message": message}
                feedback["image_base64"] = base64_image
                self.execution_history.append({"action": action, "feedback": feedback})
                logger.debug(f"Feedback (OBSERVATION): \n{colorize(json.dumps({**feedback, 'image_base64': f'<{len(base64_image)} chars>'}, indent=2), 'YELLOW')}")
                return feedback
            
            else:
                message = f"Unknown file action: {action_type}"
            
            feedback = {"done": False, "message": message}
            self.execution_history.append({"action": action, "feedback": feedback})
            logger.debug(f"Feedback (OBSERVATION): \n{colorize(json.dumps(feedback, indent=2), 'YELLOW')}")
            return feedback
            
        except Exception as e:
            logger.error(f"Error executing file action: {e}")
            logger.exception("Full traceback:")
            feedback = {"done": False, "message": f"Error: {str(e)}"}
            self.execution_history.append({"action": action, "feedback": feedback})
            return feedback
    
    def _handle_code_action(self, action: Dict[str, Any]) -> Dict[str, Any]:
        """Handle code execution actions."""
        try:
            code = action.get("code")
            if not code:
                raise ValueError("code_execute requires 'code' parameter")
            language = action.get("language", "python")
            timeout = action.get("timeout")

            result = self.sdk_client.code.execute_code(
                language=language,
                code=code,
                timeout=timeout,
            )

            # result.data is CodeExecuteResponse
            data = result.data
            parts = []
            if data.stdout:
                parts.append(data.stdout.rstrip())
            if data.stderr:
                parts.append(f"[stderr]\n{data.stderr.rstrip()}")
            if data.outputs:
                try:
                    parts.append(json.dumps(data.outputs, indent=2))
                except Exception:
                    parts.append(str(data.outputs))

            message = "\n".join([p for p in parts if p]) or f"Code executed: status={data.status}"

            feedback = {"done": False, "message": message}
            self.execution_history.append({"action": action, "feedback": feedback})
            logger.debug(f"Feedback (OBSERVATION): \n{colorize(json.dumps(feedback, indent=2), 'YELLOW')}")
            return feedback
            
        except Exception as e:
            logger.error(f"Error executing code action: {e}")
            logger.exception("Full traceback:")
            feedback = {"done": False, "message": f"Error: {str(e)}"}
            self.execution_history.append({"action": action, "feedback": feedback})
            return feedback
    
    def _handle_shell_action(self, action: Dict[str, Any]) -> Dict[str, Any]:
        """Handle shell command execution."""
        try:
            command = action.get("command")
            if not command:
                raise ValueError("shell_execute requires 'command' parameter")
            
            # Ensure shell session exists before executing command
            if not self.shell_session_id:
                try:
                    session = self.sdk_client.shell.create_session(exec_dir="/home/gem")
                    self.shell_session_id = session.data.session_id
                    logger.debug(f"Created new shell session: {self.shell_session_id}")
                except Exception as e:
                    logger.warning(f"Failed to create shell session, will let SDK auto-create: {e}")
                    # If session creation fails, let SDK auto-create by not passing id
            
            # Execute command with session ID (or let SDK auto-create if session_id is None)
            try:
                result = self.sdk_client.shell.exec_command(
                    command=command,
                    id=self.shell_session_id,
                    exec_dir="/home/gem",
                    async_mode=False,
                    timeout=0
                )
                
                # Update session_id in case SDK created a new one
                if hasattr(result, 'data') and hasattr(result.data, 'session_id'):
                    self.shell_session_id = result.data.session_id
                
                output = result.data.output
                message = output if output else "Command executed successfully (no output)"
            except Exception as session_error:
                # If session not found, try to create a new one and retry
                error_str = str(session_error)
                if "Session not found" in error_str or "404" in error_str:
                    logger.warning(f"Session {self.shell_session_id} not found, creating new session")
                    try:
                        session = self.sdk_client.shell.create_session(exec_dir="/home/gem")
                        self.shell_session_id = session.data.session_id
                        logger.debug(f"Created new shell session after error: {self.shell_session_id}")
                        
                        # Retry command with new session
                        result = self.sdk_client.shell.exec_command(
                            command=command,
                            id=self.shell_session_id,
                            exec_dir="/home/gem",
                            async_mode=False,
                            timeout=0
                        )
                        output = result.data.output
                        message = output if output else "Command executed successfully (no output)"
                    except Exception as retry_error:
                        logger.error(f"Failed to create new session and retry: {retry_error}")
                        raise retry_error
                else:
                    raise session_error
            
            feedback = {"done": False, "message": message}
            self.execution_history.append({"action": action, "feedback": feedback})
            logger.debug(f"Feedback (OBSERVATION): \n{colorize(json.dumps(feedback, indent=2), 'YELLOW')}")
            return feedback
            
        except Exception as e:
            logger.error(f"Error executing shell action: {e}")
            logger.exception("Full traceback:")
            feedback = {"done": False, "message": f"Error: {str(e)}"}
            self.execution_history.append({"action": action, "feedback": feedback})
            return feedback
    
    def get_history(self) -> list[Dict[str, Any]]:
        """Get the recorded execution history."""
        return self.execution_history
    
    def clear_history(self) -> None:
        """Clear the execution history."""
        logger.debug(f"Clearing execution history ({len(self.execution_history)} entries)")
        self.execution_history = []
    
    def create_docker_environment(self, task: Dict[str, Any], wait_time: int = 60) -> bool:
        """Create and start an agent server container."""
        if not super().create_docker_environment(task, wait_time):
            return False
        self.clear_history()
        self._initialize_sdk_client()
        return True