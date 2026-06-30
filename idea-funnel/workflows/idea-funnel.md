# Workflow Spec: Idea Funnel

## Summary

An autonomous multi-agent system that continuously discovers, filters, and researches build-worthy ideas for a developer seeking to ship something that gets them hired at an AI company. Every 3 days, delivers 1-3 well-researched idea briefs to Telegram. The user makes the final build/pass decision — the system does not build.

## The Loop

Every 3 days, the system runs a 4-stage pipeline:

```
DISCOVER → FILTER → GO DEEP → BRIEF → DELIVER
```

1. **Discover** — scan sources for emerging ideas, tools, and problems in the AI/agent space
2. **Filter** — score ideas against criteria, drop noise, keep top candidates
3. **Go Deep** — research the surviving ideas: landscape, competitors, evidence, build path
4. **Brief** — write a structured brief for each surviving idea
5. **Deliver** — send briefs to Telegram as a DOCX

## Sources

The discovery agents scan these sources:

- **GitHub trending** — repos and topics in AI, agents, LLMs, Python
- **Hacker News** — threads about AI tools, agents, startups
- **Reddit** — r/LocalLLaMA, r/MachineLearning, r/artificial
- **ArXiv** — papers on multi-agent systems, LLM applications, tool use

Own friction points are **excluded** — the funnel stays wide open to external ideas.

## Filter Criteria

An idea survives filtering if it meets **all** of these:

- **Timely** — emerging right now, not a played-out trend
- **Python-buildable** — primary coding skill is Python; TypeScript-only ideas are dropped
- **Visible** — something an AI company would notice if shipped
- **Real problem** — not a solution looking for a problem
- **Not already solved** — if a dominant tool exists and the space is saturated, skip it

## Output: The Brief

Each brief follows this exact structure:

### 1. The Idea
One sentence. What it is.

### 2. The Problem
Who has it. Why it hurts. Concrete, not abstract.

### 3. Landscape
What exists already. Why it's not enough. Name specific tools/projects.

### 4. Your Angle
Why this person specifically could build this. Python skills, agent orchestration experience, Hermes infrastructure.

### 5. Evidence
Links, trends, signals that this is emerging right now. GitHub stars, HN upvotes, Reddit threads, paper citations.

### 6. Build Path
What a minimal version looks like. Rough complexity (weekend / week / month). Key libraries or APIs.

### 7. Why AI Companies Would Care
How shipping this gets noticed. Which companies would care and why.

## Delivery

- **Format**: DOCX file, one document containing 1-3 briefs
- **Destination**: Telegram (the user's chat)
- **Cadence**: Every 2 days
- **Accompanied by**: A short summary message — "3 ideas this cycle: [one-liner each]"

## What The System Does NOT Do

- Does not build anything
- Does not write code
- Does not create prototypes or spikes
- Does not track ideas after delivery
- Does not run more frequently than every 3 days

## Concurrency

- Max 2 parallel agents per wave (Hermes delegate_task limit)
- Semi-parallel waves: discover (2 agents) → filter (1 agent) → go deep (2 agents per batch) → brief (1 agent)

## Model

All agents use GLM-5.2 (inherited from parent). No model overrides.

## Checkpoints

**None.** This is fully autonomous. The user's only interaction is reading the briefs and deciding build/pass. The "push right" principle applies: the system does maximal work before the human is involved.

## Failure Modes

- If no ideas survive filtering → deliver a message: "No ideas met criteria this cycle. Widened filter for next run."
- If sources are unreachable → log the error, continue with available sources
- If all deep-research agents fail → deliver partial briefs with a note on what was missed

## File Paths

- Source script: `idea-funnel/run_idea_funnel.py`
- Output: `<ideas-root>/runs/{date}/briefs.docx`
- Archive: `<ideas-root>/archive/` (previous briefs kept for reference)

## Cron

- Schedule: every 2 days at 2 AM WIB
- Deliver to: Telegram (origin)
- The cron job runs the script, which handles the full pipeline end-to-end
