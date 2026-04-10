#!/usr/bin/env python3
"""
Simple HTTP server for serving the agent visualization interface.
"""

import json
import argparse
from pathlib import Path
from http.server import HTTPServer, SimpleHTTPRequestHandler
from urllib.parse import urlparse, parse_qs
import os

class VisualizationHandler(SimpleHTTPRequestHandler):
    """Custom handler to serve visualization data."""

    def __init__(self, *args, data_dir=None, **kwargs):
        self.data_dir = Path(data_dir) if data_dir else None
        super().__init__(*args, **kwargs)

    def do_GET(self):
        """Handle GET requests."""
        parsed_path = urlparse(self.path)
        path = parsed_path.path

        # Serve visualization data API
        if path == "/api/data":
            query_params = parse_qs(parsed_path.query)
            file_name = query_params.get("file", [None])[0]

            if not file_name or not self.data_dir:
                self.send_error(400, "Missing file parameter or data_dir not configured")
                return

            # Support subdirectory paths (e.g. "subfolder/result.json")
            file_path = (self.data_dir / file_name).resolve()
            # Security: ensure resolved path is inside data_dir
            try:
                file_path.relative_to(self.data_dir.resolve())
            except ValueError:
                self.send_error(403, "Access denied")
                return

            if not file_path.exists():
                self.send_error(404, f"File not found: {file_name}")
                return

            try:
                with open(file_path, 'r') as f:
                    data = json.load(f)

                visualization_data = data.get("visualization_data", {})
                if "eval" in data:
                    visualization_data["eval"] = data["eval"]

                # Include the first user message so the frontend can display the task prompt
                conversation = data.get("conversation", [])
                for msg in conversation:
                    if msg.get("role") == "user":
                        content = msg.get("content", "")
                        # content may be a string or a list of content blocks
                        if isinstance(content, list):
                            text_parts = [
                                block.get("text", "")
                                for block in content
                                if isinstance(block, dict) and block.get("type") == "text"
                            ]
                            content = "\n".join(text_parts)
                        visualization_data["initial_prompt"] = content
                        break

                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Access-Control-Allow-Origin", "*")
                self.end_headers()
                self.wfile.write(json.dumps(visualization_data, indent=2).encode('utf-8'))
            except Exception as e:
                self.send_error(500, f"Error reading file: {str(e)}")
            return

        # List available result files (flat + nested structure)
        if path == "/api/list":
            if not self.data_dir or not self.data_dir.exists():
                self.send_error(404, "Data directory not found")
                return

            try:
                structure = {}

                # Root-level JSON files (key = "" means root)
                root_files = sorted(
                    f.name for f in self.data_dir.glob("*.json") if f.is_file()
                )
                if root_files:
                    structure[""] = root_files

                # One level of subdirectories
                for sub in sorted(self.data_dir.iterdir()):
                    if sub.is_dir():
                        sub_files = sorted(
                            f.name for f in sub.glob("*.json") if f.is_file()
                        )
                        if sub_files:
                            structure[sub.name] = sub_files

                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Access-Control-Allow-Origin", "*")
                self.end_headers()
                self.wfile.write(json.dumps({"structure": structure}, indent=2).encode('utf-8'))
            except Exception as e:
                self.send_error(500, f"Error listing files: {str(e)}")
            return

        # Serve static files
        if path == "/" or path == "/index.html":
            self.path = "/index.html"

        return super().do_GET()

    def log_message(self, format, *args):
        """Suppress default logging."""
        pass


def create_handler_class(data_dir):
    """Create a handler class with data_dir bound."""
    class Handler(VisualizationHandler):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, data_dir=data_dir, **kwargs)
    return Handler


def main():
    parser = argparse.ArgumentParser(description="Agent Visualization Server")
    parser.add_argument(
        "--data-dir",
        type=str,
        required=True,
        help="Directory containing result JSON files with visualization_data"
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8080,
        help="Port to serve on (default: 8080)"
    )
    parser.add_argument(
        "--host",
        type=str,
        default="localhost",
        help="Host to bind to (default: localhost)"
    )

    args = parser.parse_args()

    data_dir = Path(args.data_dir).resolve()
    if not data_dir.exists():
        print(f"Error: Data directory does not exist: {data_dir}")
        return

    visualizer_dir = Path(__file__).parent
    os.chdir(visualizer_dir)

    handler_class = create_handler_class(data_dir)
    server = HTTPServer((args.host, args.port), handler_class)

    print(f"Agent Visualization Server running at http://{args.host}:{args.port}")
    print(f"Serving data from: {data_dir}")
    print("Press Ctrl+C to stop")

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down server...")
        server.shutdown()


if __name__ == "__main__":
    main()
