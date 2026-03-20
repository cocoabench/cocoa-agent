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
            
            file_path = self.data_dir / file_name
            if not file_path.exists():
                self.send_error(404, f"File not found: {file_name}")
                return
            
            try:
                with open(file_path, 'r') as f:
                    data = json.load(f)
                
                # Extract visualization_data from result
                visualization_data = data.get("visualization_data", {})
                
                # Add eval data if available
                if "eval" in data:
                    visualization_data["eval"] = data["eval"]
                
                # Add instruction if available
                if "instruction" in data:
                    visualization_data["instruction"] = data["instruction"]

                
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Access-Control-Allow-Origin", "*")
                self.end_headers()
                self.wfile.write(json.dumps(visualization_data, indent=2).encode('utf-8'))
            except Exception as e:
                self.send_error(500, f"Error reading file: {str(e)}")
            return
        
        # List available result files
        if path == "/api/list":
            if not self.data_dir or not self.data_dir.exists():
                self.send_error(404, "Data directory not found")
                return
            
            try:
                files = [f.name for f in self.data_dir.glob("*.json") if f.is_file()]
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Access-Control-Allow-Origin", "*")
                self.end_headers()
                self.wfile.write(json.dumps({"files": files}, indent=2).encode('utf-8'))
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
    
    # Convert to absolute path BEFORE changing directory
    data_dir = Path(args.data_dir).resolve()
    if not data_dir.exists():
        print(f"Error: Data directory does not exist: {data_dir}")
        return
    
    # Change to the visualizer directory to serve static files
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



