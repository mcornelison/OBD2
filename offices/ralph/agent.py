import json
import os
import re
import sys

# Get the directory where this script is located
script_dir = os.path.dirname(os.path.abspath(__file__))
json_path = os.path.join(script_dir, "ralph_agents.json")
stories_path = os.path.join(script_dir, "sprint.json")
blockers_dir = os.path.join(os.path.dirname(script_dir), "pm", "blockers")


def printUsage():
    print("Usage: python agent.py [command]")
    print("")
    print("Commands:")
    print("  getNext      Get the next available agent (default if no command)")
    print("  list         List all agents and their status")
    print("  sprint       Show sprint status (complete, blocked, available stories)")
    print("  clear <id>   Clear agent with specified ID (set to unassigned)")
    print("  clear all    Clear all agents (set all to unassigned)")


def loadAgents():
    with open(json_path, "r") as f:
        return json.load(f)


def saveAgents(data):
    with open(json_path, "w") as f:
        json.dump(data, f, indent=2)


def getNext():
    data = loadAgents()
    max_id = data.get("max_agent", 0)

    # Find the first unassigned agent
    agent = next((a for a in data["agents"] if a["status"] == "unassigned"), None)
    if not agent or agent["id"] > max_id:
        print(0)
        return

    agent_id = agent["id"]
    # Update status to active
    agent["status"] = "active"

    saveAgents(data)

    # Print only the agent id
    print(agent_id)


def listAgents():
    data = loadAgents()
    max_id = data.get("max_agent", 0)

    print(f"Max agents: {max_id}")
    print("")
    print(f"{'ID':<4} {'Name':<10} {'Type':<12} {'Status':<12} {'Task':<16} {'Note'}")
    print("-" * 80)

    for agent in data["agents"]:
        agentId = agent.get("id", "?")
        name = agent.get("name", "")
        agentType = agent.get("type", "")
        status = agent.get("status", "")
        taskid = agent.get("taskid", "")
        note = agent.get("note", "")
        # Truncate note for display
        noteDisplay = (note[:40] + "...") if len(note) > 43 else note
        print(f"{agentId:<4} {name:<10} {agentType:<12} {status:<12} {taskid:<16} {noteDisplay}")


def getBlockedStories():
    """Get list of story IDs that have documented blockers."""
    blocked = set()
    if os.path.exists(blockers_dir):
        for filename in os.listdir(blockers_dir):
            if filename.endswith(".md") and filename != "README.md":
                filepath = os.path.join(blockers_dir, filename)
                try:
                    with open(filepath, "r", encoding="utf-8") as f:
                        content = f.read()
                        # Look for US-XXX patterns in blocker files
                        matches = re.findall(r"US-\w+-\d+", content)
                        blocked.update(matches)
                except Exception:
                    pass
    return blocked


def sprintStatus():
    """Show sprint status: complete, blocked, and available stories."""
    if not os.path.exists(stories_path):
        print("Error: sprint.json not found")
        return

    with open(stories_path, "r", encoding="utf-8") as f:
        prd = json.load(f)

    stories = prd.get("userStories", [])
    if not stories:
        print("No user stories found in sprint.json")
        return

    # Get documented blockers
    documented_blockers = getBlockedStories()

    # Build dependency map
    completed_ids = {s["id"] for s in stories if s.get("passes") is True}

    # Categorize stories
    complete = []
    blocked = []
    available = []

    for story in stories:
        story_id = story.get("id", "?")
        title = story.get("title", "")[:50]
        passes = story.get("passes")
        deps = story.get("dependencies", [])

        if passes is True:
            complete.append((story_id, title))
        else:
            # Check if blocked
            unmet_deps = [d for d in deps if d not in completed_ids]
            is_documented_blocker = story_id in documented_blockers

            if unmet_deps:
                blocked.append((story_id, title, f"deps: {', '.join(unmet_deps)}"))
            elif is_documented_blocker:
                blocked.append((story_id, title, "documented blocker"))
            else:
                available.append((story_id, title))

    # Print report
    print("=== Sprint Status ===")
    print("")

    print(f"[DONE] Complete ({len(complete)}):")
    if complete:
        for sid, title in complete:
            print(f"  {sid}: {title}")
    else:
        print("  (none)")

    print("")
    print(f"[BLOCKED] Blocked ({len(blocked)}):")
    if blocked:
        for sid, title, reason in blocked:
            print(f"  {sid}: {title}")
            print(f"         -> {reason}")
    else:
        print("  (none)")

    print("")
    print(f"[TODO] Available ({len(available)}):")
    if available:
        for sid, title in available:
            print(f"  {sid}: {title}")
    else:
        print("  (none)")

    print("")
    print("-" * 50)
    total = len(stories)
    pct = 100 * len(complete) // total if total > 0 else 0
    print(f"Progress: {len(complete)}/{total} complete ({pct}%)")

    if available:
        next_story = available[0]
        print(f"Next available: {next_story[0]} - {next_story[1]}")
    elif blocked:
        print("Next available: NONE - all remaining stories are blocked")
        print("Action required: Check pm/blockers/ for details")
    else:
        print("Sprint complete!")


def clearAgent(agentId):
    data = loadAgents()
    max_id = data.get("max_agent", 0)

    # Validate agent ID is within max_agent limit
    if agentId > max_id:
        print(f"Error: Agent {agentId} exceeds max_agent limit ({max_id})")
        return

    # Find the agent by ID
    agent = next((a for a in data["agents"] if a["id"] == agentId), None)
    if not agent:
        print(f"Error: Agent {agentId} not found")
        return

    agent["status"] = "unassigned"
    agent["taskid"] = ""

    saveAgents(data)
    print(f"Agent {agentId} cleared")


def clearAll():
    data = loadAgents()

    for agent in data["agents"]:
        agent["status"] = "unassigned"
        agent["taskid"] = ""

    saveAgents(data)
    print(f"All agents cleared ({len(data['agents'])} agents)")


def main():
    args = sys.argv[1:]

    # No arguments or "getNext" -> get next available agent
    if len(args) == 0 or (len(args) == 1 and args[0].lower() == "getnext"):
        getNext()
        return

    # Handle "list" command
    if len(args) == 1 and args[0].lower() == "list":
        listAgents()
        return

    # Handle "sprint" command
    if len(args) == 1 and args[0].lower() == "sprint":
        sprintStatus()
        return

    # Handle "clear" command
    if args[0].lower() == "clear":
        if len(args) < 2:
            print("Error: 'clear' requires an argument (agent ID or 'all')")
            printUsage()
            return

        if args[1].lower() == "all":
            clearAll()
        else:
            try:
                agentId = int(args[1])
                clearAgent(agentId)
            except ValueError:
                print(f"Error: Invalid agent ID '{args[1]}' (must be a number or 'all')")
                printUsage()
        return

    # Invalid command
    print(f"Error: Unknown command '{args[0]}'")
    printUsage()


if __name__ == "__main__":
    main()
