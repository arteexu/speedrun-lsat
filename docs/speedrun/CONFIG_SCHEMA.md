# Speedrun config JSON schema (v0.3)

Shared between desktop (`speedrun/config.json`) and iOS companion. Future sync will copy this file verbatim.

## File location

- Desktop: `speedrun/config.json` (repo root package)
- iOS: bundle or app-group copy (same keys)

## Schema

```json
{
    "version": "0.3.0",
    "latency_budget_ms": {
        "default": 90000,
        "LR": 84000,
        "RC": 96000,
        "LG": 84000
    },
    "daily_study_goal_cards": 20,
    "daily_study_goal_minutes": null,
    "interleaving_enabled": true,
    "ai_enabled": false,
    "section_filter": null,
    "schema_drill_count": 3
}
```

## Fields

| Key                        | Type                               | Description                                                    |
| -------------------------- | ---------------------------------- | -------------------------------------------------------------- |
| `version`                  | string                             | Config format version                                          |
| `latency_budget_ms`        | object                             | Per-section time budgets in milliseconds                       |
| `daily_study_goal_cards`   | integer                            | Target reviews per calendar day                                |
| `daily_study_goal_minutes` | integer \| null                    | Optional minutes goal from revlog latency sum                  |
| `interleaving_enabled`     | boolean                            | `true` = schema-weighted queue; `false` = plain Anki due order |
| `ai_enabled`               | boolean                            | LLM features (off by default)                                  |
| `section_filter`           | `"LR"` \| `"RC"` \| `"LG"` \| null | Limit queue/dashboard to one section                           |
| `schema_drill_count`       | integer                            | Weakest N schemas for drill mode                               |

## Validation

`speedrun.config.validate_config()` returns errors for invalid values. `speedrun/tools/health_check.py` includes config validation.

## iOS mapping

Swift `SpeedrunConfig` in `ios/App/ContentView.swift` uses the same snake_case JSON keys via `CodingKeys`.
