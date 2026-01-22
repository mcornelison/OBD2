# Project Specifications

This folder contains the project's documentation, standards, and planning artifacts.

## Contents

### Core Documentation

| Document | Description |
|----------|-------------|
| [architecture.md](architecture.md) | System architecture, technology stack, and design decisions |
| [methodology.md](methodology.md) | Development methodology, workflows, and processes |
| [standards.md](standards.md) | Coding standards, naming conventions, and best practices |
| [glossary.md](glossary.md) | Terms, acronyms, and domain language definitions |
| [anti-patterns.md](anti-patterns.md) | Common mistakes and what NOT to do |
| [backlog.json](backlog.json) | Task backlog with priorities and status tracking |
| [plan.md](plan.md) | Implementation roadmap and phase breakdown |

### Skills

| Document | Description |
|----------|-------------|
| [prd_skill.md](prd_skill.md) | How to create Product Requirements Documents |
| [ralph_skill.md](ralph_skill.md) | How to convert PRDs to Ralph JSON format |
| [knowledge_update_skill.md](knowledge_update_skill.md) | How to update the agent handbook and specs with learnings |

### Subfolders

| Folder | Description |
|--------|-------------|
| [tasks/](tasks/) | PRD markdown files for features |
| [user-stories/](user-stories/) | Ralph-formatted JSON user stories |

## Backlog Management

### Backlog Structure

Tasks in `backlog.json` follow this structure:

```json
{
  "id": 1,
  "title": "Task title",
  "category": "category-name",
  "description": "Detailed description",
  "priority": "high|medium|low",
  "status": "pending|in_progress|completed|blocked",
  "steps": ["Step 1", "Step 2"],
  "testing": "How to verify completion",
  "passed": false,
  "completedDate": null,
  "notes": "Additional context"
}
```

### Categories

- **config** - Configuration and environment setup
- **core** - Core functionality and business logic
- **api** - API integrations and clients
- **database** - Database operations and schemas
- **testing** - Test development and coverage
- **observability** - Logging, monitoring, metrics
- **security** - Security implementations
- **documentation** - Documentation tasks
- **deployment** - Deployment and CI/CD

### Priorities

- **high** - Critical path, blocks other work
- **medium** - Important but not blocking
- **low** - Nice to have, can be deferred

## How to Use

1. **Starting a new feature**: Create entry in `backlog.json`
2. **Planning work**: Reference `plan.md` for implementation order
3. **Writing code**: Follow `standards.md` conventions
4. **Architecture decisions**: Document in `architecture.md`
5. **Process questions**: Refer to `methodology.md`

## PRD Workflow

For larger features, use the PRD workflow:

1. **Create PRD**: Use `prd_skill.md` to generate `tasks/prd-[feature].md`
2. **Convert to Ralph**: Use `ralph_skill.md` to create `user-stories/[feature]-prd.json`
3. **Execute**: Copy JSON to `ralph/prd.json` and run `./ralph/ralph.sh`

This workflow breaks features into bite-sized user stories that Ralph can execute autonomously.

## Updating Documentation

When updating specs:
1. Keep documents concise and actionable
2. Include examples where helpful
3. Update the modification history in each file
4. Cross-reference related documents
