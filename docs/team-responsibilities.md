# Team responsibilities

This document records the team's current task allocation, as set out in the Project Management document. Update it whenever roles or responsibilities change.

> **v2 note.** The project direction changed after new instructor feedback (see the [v2 architecture report](societytwin-v2-architecture.md)). The roles below are unchanged except Sam's, which moved from Literature Research to Environment + Scenario/Task. **Ownership of the new v2 modules** (for example the generator, sampling, experiments, and AI-agent runtime) **has not been assigned** and is an OPEN DECISION for the team.

How the five research streams come together is described in [research-integration.md](research-integration.md).

## Summary

| Team member | Role | Main research responsibility | Expected deliverable |
|---|---|---|---|
| Bejan | Project Manager / System Architect | Define the system and integrate the team's work | Integrated system definition, architecture, scope, presentation structure, and TÜBİTAK form |
| Sam | Environment + Scenario/Task (previously Literature Research) | What world agents operate in and what situation they respond to; MatrAIx practical testing | SocietyTwin Scenario/Task/Environment experiment contract and first Türkiye-specific controlled experiment (earlier: 8–10 reviewed sources) |
| Pakhlavon | Technical Architecture / Technologies | How the system could technically be built | Technology assessment in which every technology is justified |
| Azra | Existing Systems / Similar Projects | Existing academic, industry, and open-source systems | Comparison of existing systems leading to SocietyTwin's gap and contribution |
| Koray | Data + Population + Simulation Research | How the population, agents, simulation, and evaluation could work | Population Schema + Agent Schema + Simulation Concept |

## Bejan

**Role:** Project Manager / System Architect

**Main research responsibility:** Define the system and integrate the team's work.

**Responsibilities:**

- Project objective
- Target users
- Main problem
- System boundaries
- Main capabilities
- Overall system architecture
- Integration of everyone's research
- Presentation structure
- IN SCOPE / OUT OF SCOPE definition
- Final GitHub structure
- Coordination of the TÜBİTAK form

**Expected deliverable:** An integrated SocietyTwin system definition, combining the four research streams into the final system definition, architecture, scope, presentation, and TÜBİTAK proposal.

**Related documents:** [project-overview.md](project-overview.md), [architecture.md](architecture.md)

## Sam

**Current role:** Environment + Scenario/Task

**Research question:** What world are agents operating inside, and what situation are they being asked to respond to?

- **Scenario** — what is happening (event, policy change, condition).
- **Task** — what the agent is supposed to do (response, decision, action).
- **Environment** — where/how the action happens (controlled interface, observations, allowed actions, rules).

**Current work:**

- MatrAIx investigation and practical testing (persona-conditioned survey runs; see [experiments/matraix_simulation/](../experiments/matraix_simulation/)).
- Repository-level trace of how MatrAIx loads personas, creates jobs, executes trials, and writes results.
- Defining SocietyTwin's versioned Scenario/Task/Environment experiment contract.
- Preparing the first Türkiye-specific controlled experiment (e.g. Ankara public transport fare increase).

### Previous role: Literature Research

**Main research responsibility:** Research the academic foundations behind the project.

**Research areas:**

- Digital twins
- Social / digital society twins
- Agent-based modeling
- Synthetic populations
- Generative agents
- Social simulation
- LLM-based agents
- Socio-technical systems
- Population-level simulation

**Expected deliverable:** Approximately 8–10 strong academic or technical sources, each recorded with Paper Title, Year, Problem, Method, Data, Model / Architecture, Results, Limitations, and Relevance to SocietyTwin. The team will select at least 5 of the strongest for the presentation.

**Related document:** [sources.md](sources.md), which contains verified sources grouped as core methodology, reference systems, data sources, and future-research sources, plus further research targets.

## Pakhlavon

**Role:** Technical Architecture / Technologies

**Main research responsibility:** Research how the system could technically be built.

**Research areas:**

- Programming languages
- Agent frameworks
- AI / LLM technologies
- Simulation frameworks
- Databases
- APIs
- Data processing
- Visualization
- Backend
- Frontend
- Testing
- GitHub workflow

**Guiding rule:** Technologies should not be selected simply because they sound impressive. Every proposed technology must answer the question:

> "Why does SocietyTwin actually need this technology?"

**Expected deliverable:** A technology assessment covering the areas above. A suggested format for each entry:

| Area | Candidate technology | Why SocietyTwin needs it | Alternatives considered | Status |
|---|---|---|---|---|

**Related documents:** [architecture.md](architecture.md), [requirements.txt](../requirements.txt)

## Azra

**Role:** Existing Systems / Similar Projects

**Main research responsibility:** Research existing academic, industry, and open-source systems related to:

- Social digital twins
- Socio-technical digital twins
- Synthetic population systems
- Agent-based society simulations
- Generative-agent systems

**For each system, record:**

| System name | What it does | Technology | Strengths | Limitations | What SocietyTwin can learn from it |
|---|---|---|---|---|---|

**Expected deliverable:** A comparison of existing systems that establishes:

```text
Existing Work
      ↓
Existing Limitation / Gap
      ↓
Our Contribution
```

**Related document:** [research-integration.md](research-integration.md)

## Koray

**Role:** Data + Population + Simulation Research

**Main research responsibility:** Research how SocietyTwin could represent the population and agents, run simulations, and evaluate them.

**Population representation (research categories):**

- Age
- Occupation
- Location
- Socioeconomic characteristics
- Relationships
- Preferences
- Behavior

> These are research categories only. The v2 persona schema includes only attributes with a defensible official source (mainly TÜİK) or a documented assumption; see [persona-schema.md](persona-schema.md). Relationships, preferences, and behaviour are not part of the MVP schema.

**Agent research:** agent attributes, agent states, agent behavior, agent interactions, social networks, and the environment.

**Simulation research:** how agents interact, how scenarios are introduced, how society changes over time, and how simulation outputs are measured.

**Evaluation research:** historical validation, statistical similarity, aggregate-level evaluation, model comparison, and scenario consistency.

**Expected deliverable:**

```text
Population Schema
        +
Agent Schema
        +
Simulation Concept
```

**Related documents:** [methodology.md](methodology.md), [data/README.md](../data/README.md)
