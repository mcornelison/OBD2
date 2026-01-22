import sys
import json
import os

# Get the directory where this script is located
script_dir = os.path.dirname(os.path.abspath(__file__))
json_path = os.path.join(script_dir, "ralph_agents.json")

def main():
    if len(sys.argv) != 2:
        print("Usage: set_agent_free.py <agent_id>")
        return
    try:
        agent_id = int(sys.argv[1])
    except ValueError:
        print("Input must be an integer.")
        return
    if agent_id <= 0:
        print("Agent ID must be greater than 0.")
        return
    # Read the JSON file
    with open(json_path, "r") as f:
        data = json.load(f)
    max_agent = data.get("max_agent", 0)
    if agent_id > max_agent:
        print(f"Agent ID must be less than or equal to max_agent ({max_agent}).")
        return
    # Find the agent with matching id
    agent = next((a for a in data["agents"] if a["id"] == agent_id), None)
    if not agent:
        print("Agent not found.")
        return
    # Update status to unassigned
    agent["status"] = "unassigned"
    # Save the updated JSON
    with open(json_path, "w") as f:
        json.dump(data, f, indent=2)

if __name__ == "__main__":
    main()
