# Data guide

## Follow a purchase

Start with family M001, period 2, the worked example in the paper. Look up its row in `design/reserved/main_sequences.csv.gz` using the family, recurrence condition, and period. The `A` and `B` columns identify physical offers in `main_offers.csv.gz`. The O1 and O2 operators faced those same alternatives. In the event file, the two operators are distinguished by `operator_code` and the five governance arrangements by `policy`. For an agent decision, join the event’s `attempt_id` to the `id` in the attempts file. The request contains the complete system and user messages. The response contains the agent’s provisional choice and, where permitted, its decision to act or refer.

In the offer bank, fees are in tenths of a US cent, the reserve-loss probability is in basis points, and reimbursement is in whole cents conditional on nondelivery. The evaluator computes expected values in hundredths of a cent with integer arithmetic. Choice loss is the best available expected value minus the value of the executed option. Declining has value zero. A failed response has zero executed value and a separate execution code. Dividing the stored loss by 100 gives the loss in cents used throughout the results.

## Stages and units

| Family IDs | Location | Arrangements |
| --- | --- | --- |
| P001–P002 | [Pilot](../development/pilot/) | Four primary arrangements and the advance rule. Qualification requests Q1–Q8 precede the purchases. |
| D001–D016 | [Calibration](../development/calibration/) | Four primary arrangements. The frozen instrument calls this stage `precision`. |
| M001–M048 | [Main study](../data/main/) | Four primary arrangements and the advance rule. M049–M128 are reserved menu designs. The last observed family is M048. |

One event identifies one purchase opportunity under one arrangement. The unique key is `family, recurrence, period, operator_code, policy`. The statistical resampling unit is the matched family. The field `recurrence` takes the value `low` for one focal custody choice or `high` for six. O1 values holding the keys at 2¢ and O2 at 10¢.

| Manuscript arrangement | Data value | Decision authority |
| --- | --- | --- |
| Full operator approval | `REVIEW_ALL` | The simulated operator decides all 12 purchases. The event has no model attempt ID. |
| Mandate-only delegation | `STANDING` | The agent decides using the original mandate. |
| Referral with case ruling | `CASE` | The agent can ask. The operator’s ruling settles the current choice. |
| Referral with reusable rule | `RULE` | The first qualifying referral also authorizes use of the operator’s control premium on later purchases. |
| Delegation with advance rule | `UPFRONT` | The agent receives the same numerical rule before period 1 and decides each purchase. |

## Reading the records

Each compressed JSON Lines file contains one UTF-8 JSON object per line. A CSV reader with gzip support can open the menu assignments and reserved offer banks directly. For example, `pandas.read_json("data/main/events.jsonl.gz", lines=True)` loads the main events.

| File or field | Interpretation |
| --- | --- |
| `attempts.jsonl.gz` | One row per submitted first request, in original dispatch order. `request` contains the recorded model options and messages. `content` is the visible first response, `decision` its parsed JSON, and `state` the instructions in effect. `http_status` and `status` identify collection outcomes. Model, provider, and token counts are retained where available. |
| `events.jsonl.gz` | Complete scientific event records exported from each original collection journal. The replay checks every field against the frozen menus and archived responses. |
| `skipped_slots.csv` | Scheduled conditional calls skipped because the branch had not opened. A skipped slot generated no model request. |
| `menu_roles.csv.gz` | One row per main family, recurrence condition, and period. `role` distinguishes focal custody choices, their replacement controls, and common controls. `cell` identifies the comparison, including the transfer purchase. |
| `attempt_id`, `fork_attempt_id` | Study-defined identifiers. Before the first qualifying referral, CASE and RULE consume the same first response. The fork ID identifies the common ruling where their future instruction paths separate. |
| `carry_rule_before`, `carry_rule_after`, `later_clause_issued` | Rule in force before or after this purchase, and one-time issuance on a qualifying referral. An advance rule is already in force at period 1. |
| `review_count`, `qualified_first_referral`, `operator_ruling` | Whether the operator decided this purchase, whether it triggered the common qualifying ruling, and the option chosen on review. |
| `offer_A`, `offer_B`, `pair_id`, `best_physical_set` | Physical offer IDs, their orientation-independent pair, and the set of options tied for best operator value. |
| `provisional_label`, `executed_label`, `executed_physical` | Agent’s initial choice, executed option, and physical offer or outside-option identifier. `NO_EXECUTION` marks a technical failure. |
| `valid_first_attempt` | True for a valid model response, false for a failed response, and null for deterministic full operator approval. |
| `*_value_100th_c`, `loss_100th_c`, `immediate_recovered_100th_c` | Expected option values, purchase loss, and immediate gain from review, measured in hundredths of a cent. |

The public attempt export preserves the exact submitted messages and returned decision text. The original journals also served as operational logs. Account balances, credentials, provider receipt identifiers, and private provider reasoning are outside the public data export. The [collection source](../collection/) records how the original online runs were conducted, including checks against private billing ledgers. The [offline replay](../scripts/replay.py) uses the public files and covers every observed decision, including failed requests, qualification responses, shared first rulings, and deterministic approvals.

## From data to results

| Output under `results/analysis/` | Unit and interpretation |
| --- | --- |
| `sequence_outcomes.csv` | One family × operator × recurrence × arrangement over 12 opportunities. L is purchase loss in cents, N is the review count, and M counts rules issued after referral. Additional columns record failures, loss events, and review diagnostics. |
| `paired_contrasts.csv` | Signed within-family differences between arrangements for loss and reviews. The direction is `from_policy` minus `to_policy`. |
| `recurrence_interactions.csv` | CASE minus RULE under high recurrence, minus that same difference under low recurrence. Positive values indicate an additional saving from reuse when the tradeoff returns. Source for Table 4. |
| `net_cost_differences.csv` | Paired cost differences after assigning a review and drafting price. At the reference prices, an advance rule incurs one drafting charge at the start. |
| `least_cost_intervals.csv` | Changes in the least-cost arrangement across nonnegative review prices for each scenario. `at_boundary` lists ties at a crossing and `above_boundary` identifies the winner immediately above it. Source for Figure 2. |
| `followup_by_return.csv` | Cumulative differences from the common ruling to each later focal opportunity and the final period. The accumulation includes intervening purchases. Source for Figure 1. |
| `clause_recovery.csv` | First observed break-even point, subsequent reversal, and final net saving. Includes sequences with a qualifying ruling. |
| `menu_diagnostics.csv` | Counts, purchase losses, and failures by arrangement, menu role, and comparison cell. |

The `all` population retains every assigned main family. `valid_core` retains families with valid responses across all four primary arrangements. `valid_full` also requires valid advance-rule responses. The `both` operator category gives the two operators equal weight within each family. Choice losses measure forgone expected value under the specified operator preferences. Review and drafting costs enter after the choices have been scored.

[Tables 1 and 2](../results/manuscript/) transcribe the design definitions and attribute levels. Tables 3–5 are generated from the analysis tables and compared with CSV transcriptions from the working manuscript. The additional file `text_diagnostics.csv` recovers the failed-request decomposition, transfer-choice counts, review counts, and drafting-cost recovery counts. Figure 3A uses CASE minus RULE from the net-cost table. Figure 3B is a conceptual drawing. Its peak is illustrative, and the experiment estimates the return to one specified custody rule.
