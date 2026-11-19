# snow-kit intent manifest

Plain-English routing metadata behind `snow-kit help <intent>` and the MCP `help` tool. Generated from the registry and Snow-owned routing configuration; do not edit by hand. Run `uv run python -m snow_kit.aliases_gen`.

Resolution is deterministic server-side. Cursor/model selection of the initial tool remains model-dependent. Help performs no Snowflake query, context retrieval, or write.

## Common intents

| Intent | Operation | CLI |
|--------|-----------|-----|
| analyze this sql | `query.analyze` | `snow-kit query analyze` |
| describe this table | `catalog.describe_table` | `snow-kit catalog describe_table` |
| discover governed analytics definitions | `context.search` | `snow-kit context search` |
| execute bounded select sql | `query.execute` | `snow-kit query execute` |
| explain this query | `query.analyze` | `snow-kit query analyze` |
| find a column | `catalog.search_columns` | `snow-kit catalog search_columns` |
| find the authoritative metric definition | `context.search` | `snow-kit context search` |
| inspect table columns | `catalog.describe_table` | `snow-kit catalog describe_table` |
| read this approved context section | `context.get` | `snow-kit context get` |
| retrieve governed context | `context.get` | `snow-kit context get` |
| run this read-only query | `query.execute` | `snow-kit query execute` |
| search analytics context | `context.search` | `snow-kit context search` |
| search scoped column metadata | `catalog.search_columns` | `snow-kit catalog search_columns` |

## Operation triggers

Strong operation/curated/alias/keyword cues rank above weak service synonyms. Ambiguous requests return candidates and reasons without an executable recommendation.

| Operation | Posture | CLI | Triggers |
|-----------|---------|-----|----------|
| `catalog.check_write_access` | read | `snow-kit catalog check_write_access` | access, catalog, check, column, columns, database, grants, metadata, permissions, schema, table, tables, write |
| `catalog.describe_table` | read | `snow-kit catalog describe_table` | catalog, column, columns, database, describe, inspect, metadata, schema, table, tables |
| `catalog.get_table_stats` | read | `snow-kit catalog get_table_stats` | catalog, column, columns, database, get, metadata, schema, stats, table, tables |
| `catalog.list_tables` | read | `snow-kit catalog list_tables` | catalog, column, columns, database, list, metadata, schema, table, tables |
| `catalog.preview_table` | read | `snow-kit catalog preview_table` | catalog, column, columns, database, metadata, preview, schema, table, tables |
| `catalog.search_columns` | read | `snow-kit catalog search_columns` | catalog, column, columns, database, find, metadata, schema, scoped, search, table, tables |
| `context.get` | read | `snow-kit context get` | analytics, approved, authoritative, business, context, definition, get, governed, metric, provenance, read, retrieve, section |
| `context.search` | read | `snow-kit context search` | analytics, authoritative, business, context, definition, definitions, discover, find, governed, metric, provenance, search, tables |
| `query.analyze` | read | `snow-kit query analyze` | analyze, execute, explain, performance, query, read, snowflake, sql |
| `query.execute` | read | `snow-kit query execute` | analyze, bounded, execute, explain, only, query, read, run, select, snowflake, sql |
| `query.execute_write` | write | `snow-kit query execute_write` | analyze, execute, explain, query, read, snowflake, sql, write |

## Configured workflows

### `analytics.context_first_query` — Context-first analytical query

Resolve governed definitions and narrow metadata scope before proposing bounded read-only analytical SQL.

Qualifies when at least 2 cue groups match; required groups: `analytical_measure`.

| Cue group | Approved cues | Weight |
|-----------|---------------|--------|
| analytical_measure | metric, measure, gmv, revenue, volume, rate | 2 |
| breakdown_or_visualization | chart, plot, bar, line, stacked, segment, segments, breakdown, group, grouped | 2 |
| time_definition | date, day, week, month, quarter, year, window, period | 2 |

| Step | Kind | Tool | Instruction | Preconditions | Stop if |
|------|------|------|-------------|---------------|---------|
| 1 | call_tool | context_search | Search the configured governed analytics corpus for the metric, segment, date-window, timezone, and grain definitions. | A configured governed context source is available. | The context source is unavailable.; No relevant governed result matches. |
| 2 | call_tool | context_get | Read only the selected relevant section using the opaque document_id and exact revision returned by context_search. | A context_search result is semantically relevant to the requested analysis. | The result is stale, ambiguous, irrelevant, or outside approved paths. |
| 3 | clarify | — | Clarify every unresolved metric, segment, date-window, timezone, and chart-grain definition before metadata inspection. | Treat provenance validity and semantic relevance as separate checks. | Any required analytical definition remains unresolved. |
| 4 | call_tool | catalog_describe_table | Inspect a fully qualified table candidate narrowly; use catalog_search_columns only within a known database plus schema. | Relevant context identifies a fully qualified table candidate. | Only database-wide or broad INFORMATION_SCHEMA exploration is possible. |
| 5 | call_tool | query_analyze | Optionally analyze the proposed bounded SELECT/WITH statement. | The SQL uses confirmed definitions and observed catalog metadata. | — |
| 6 | call_tool | query_execute | Execute bounded read-only SELECT/WITH SQL and return chart-ready rows. | Context references are provenance-valid and semantically relevant.; Catalog scope, joins, finite time predicate, timezone, and grain are confirmed.; SQL validation, permissions, and returned-row limits all pass. | The proposal requires USE, writes, guessed schema, or irrelevant context. |
| 7 | external | — | Hand chart-ready rows to a caller-provided visualization surface. | Query results are complete enough for the requested chart. | — |

Limitations:
- Snow-kit does not render charts.
- max_rows caps returned rows; it does not reduce warehouse scanning.
- USE changes shared session context and is not recommended by this workflow.

## Safety boundaries

- Workflows are conditional recommendations, not execution orchestration.
- Valid context provenance does not prove semantic relevance.
- Missing context never authorizes broad `INFORMATION_SCHEMA` discovery.
- Existing context modes, SQL validation, permissions, and row caps remain authoritative.
- `max_rows` caps returned rows, not warehouse scanning; `USE` changes session state.
- Snow-kit returns rows and does not render charts.
