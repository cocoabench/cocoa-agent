# Agent Visualization Tool

A web-based visualization tool for viewing agent execution traces, similar to UI-TARS showcase.

## Features

- **Left Panel**: Shows the complete agent trace with:
  - **Think**: Agent's reasoning/thought process
  - **Action**: Actions taken by the agent (browser, file, code, shell operations)
  - **Observation**: Feedback/results from each action

- **Right Panel**: 
  - **Content Viewer**: Displays detailed content for selected actions:
    - Browser screenshots
    - File contents
    - Code execution results
    - Shell command outputs
  - **Playback Controls**: 
    - Progress bar (draggable)
    - Play/Pause button
    - Previous/Next step navigation
    - Speed control (0.5x, 1x, 2x, 4x)
    - Reset button

## Usage

1. **Start the visualization server**:
   ```bash
   python visualizer/server.py --data-dir gpt-outputs/results.json --port 8085
   ```

2. **Open your browser** and navigate to:
   ```
   http://localhost:8085
   ```

3. **Select a result file** from the dropdown in the header

4. **Navigate through the trace**:
   - Click on any action/think block in the left panel to view details
   - Use playback controls to step through the execution
   - Drag the progress bar to jump to any step

## Data Format

The visualization tool expects result JSON files with a `visualization_data` field containing:

```json
{
  "visualization_data": {
    "task_description": "...",
    "iterations": [
      {
        "iteration": 1,
        "think": "Agent's reasoning...",
        "actions": [
          {
            "action": {
              "action_type": "browser_click",
              "x": 100,
              "y": 200
            },
            "observation": "Action executed successfully",
            "screenshot": "base64_encoded_image..."
          }
        ]
      }
    ]
  }
}
```

## Architecture

- **Backend** (`server.py`): Simple HTTP server that:
  - Serves the HTML/JS frontend
  - Provides API endpoints to load visualization data from JSON files
  - Lists available result files

- **Frontend** (`index.html`): Single-page application with:
  - Trace visualization
  - Content viewer
  - Playback controls

## Notes

- The visualization data is automatically collected during agent execution in `executor/__init__.py`
- Browser actions automatically trigger screenshots for visualization
- All screenshots are stored as base64-encoded strings in the visualization data



