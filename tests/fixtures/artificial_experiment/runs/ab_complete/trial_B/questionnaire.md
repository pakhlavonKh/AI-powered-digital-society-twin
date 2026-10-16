# Artificial Survey

Use exact `questionId` and valid choice ids.

## q_pick

Prompt: Pick an invented option.

- Construct: `artificial`
- Type: `single_choice`
- Required: `true`

| choice_id | label |
|-----------|-------|
| `opt_a` | Invented option A. |
| `opt_b` | Invented option B. |

## q_scale

Prompt: Rate this invented thing.

- Construct: `artificial_scale`
- Type: `likert`
- Required: `true`
- Scale: `1`-`5`

## q_beta

Prompt: Invented yes/no.

- Type: `single_choice`

| choice_id | label |
|-----------|-------|
| `true` | Invented yes. |
| `false` | Invented no. |

## Answer envelope

Ignored section.
