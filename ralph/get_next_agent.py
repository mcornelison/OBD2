import json
import os

# Get the directory where this script is located
script_dir = os.path.dirname(os.path.abspath(__file__))
json_path = os.path.join(script_dir, "ralph_agents.json")

def main():
    # Read the JSON file
    with open(json_path, "r") as f:
        data = json.load(f)

    max_id = data.get("max_agent", 0)
    # Find the first unassigned agent
    agent = next((a for a in data["agents"] if a["status"] == "unassigned"), None)
    if not agent or agent["id"] > max_id:
        print(0)
        return

    agent_id = agent["id"]
    # Update status to active
    agent["status"] = "active"

    # Save the updated JSON
    with open(json_path, "w") as f:
        json.dump(data, f, indent=2)

    # Print only the agent id
    print(agent_id)

if __name__ == "__main__":
    main()
