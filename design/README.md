# Paper 3 pre-experiment design v1.0.1

The protocol covers Steps 1–10 of the modeling plan. Read Paper_3_Experimental_Protocol.docx for the design decisions. This package contains the instruments and assignments for future collection. Its checks use enumerated offer attributes and prescribed fixture responses. It contains no observed purchase choices or live dispatch code.

| Chunk | Materials | Purpose |
| --- | --- | --- |
| 1 · Operators and authority | spec/design.json, prompts/, spec/response.schema.json | Defines the two operator utility functions, common mandate, purchase task, eligible exception, one-case ruling, and reusable clause. |
| 2 · Purchase sequences | menus/, reserved/, checks/build_menus.py, spec/paper2_exclusions.json | Supplies the two pilot families, paired low/high schedules, reproducible generation rules, and separate material for precision planning and confirmation. |
| 3 · Scoring and validation | spec/analysis.json, spec/attempt.schema.json, spec/path_event.schema.json, checks/ | Specifies estimands, cash accounting, uncertainty, cost curves, model-response parsing, and scripted fixture checks. |
| 4 · Pilot and later freeze | spec/collection.json, menus/pilot_dispatch.csv, spec/freeze.json | Sets qualification, request order, candidate-call ceilings, technical fallbacks, sample-size decision rules, and later collection conditions. |

## Purchasing model

Precollection amendment A1 specifies GPT-6.2 Sol for qualification and every live purchase decision. Request `openai/gpt-6.2-sol` through OpenRouter on the standard OpenAI route and verify the dated endpoint `OpenAI | openai/gpt-6.2-sol-20261117`. Set medium reasoning and an 8,192-token output limit. The two synthetic operators and the full-approval benchmark use the specified utility functions. The run manifest records the requested ID, dated endpoint and actual provider. See spec/collection.json and spec/freeze.json for the version evidence and amendment. [OpenRouter release](https://openrouter.ai/openai/gpt-6.2-sol-20261117) · [OpenAI model documentation](https://developers.openai.com/api/docs/models/gpt-6.2-sol).

## Pilot API budget

The proposed pilot ceiling is US$3. Paper 2 recorded US$1.523458 across 531 completed Sol 6.1 requests. At that usage, all 372 pilot slots would cost about US$1.07. Check actual charges after period 3, when both families have seen their first custody choice. Up to 84 requests by then would cost about US$0.24 at the historical mean. The Sol 6.2 pilot will measure actual token use and cost per purchase decision. See spec/collection.json for the calculation and the spending rule.

At the same per-call rate and maximum scheduled call counts, the pilot, precision calibration, and main study together would cost US$19.75 for 24 main families, US$32.28 for 48, or US$74.06 for all 128 reserved families. If the secondary upfront-clause comparison were deferred for both pilot and main, the corresponding totals would be US$16.17, US$25.40, and US$56.15. The independent calibration sets the required main sample. Recalculate costs using pilot usage before any later spending decision.

## Reading the assignments

Each family has 24 sequence rows. The two 12-purchase variants share seven physical menus and the remaining five have financial twins with a different key holder. The same design is used for both operators and all policies. All public offer terms are in the stage offer dictionary. In the CSVs a fee unit is a tenth of a cent, reserve risk is in basis points, and the refund is conditional cents. Each event score uses hundredths of a cent. Labels in the columns cell, role, family, recurrence, economic_root, policy, and operator are for researchers. Only the rendering function’s public fields may reach the purchasing agent.

Opening and closing a gzip file leaves the inputs intact. The precision and main files are reserved by design stage. A reserve contains menu assignments only. Pilot responses cannot enter a main estimate. Stage membership is hashed on the pair of financial/identity profiles after stripping key ownership and orientation. Individual offer profiles can recur. None of the economic pairs in the three archived Paper 2 design inputs listed in paper2_exclusions.json enters any bank. Fees, attributes, and context therefore carry forward from Paper 2 without reusing those offer pairs or model responses.

## Collecting the main sample in blocks

The independent calibration determines the final sample before main collection. M001–M024 are the first main observations. After every assigned path in those 24 families closes, pause to verify coverage, accounting, routing and billing. Resume with M025–M048 or the frozen endpoint if sooner. If the target exceeds 48, M049 onward form the final block. The run can span several sessions. All planned policies and both operator and recurrence conditions run in each block.

The offline schedule generator yields one complete family range and its candidate slots at a time. For instance, after the ledger verifies closure of family block M001–M024 in a 48-family run, `dispatch_blocks("main", 48, completed_through=24)` yields M025–M048. The same first block applies at 128. The production collector must restore the frozen target and completed boundary from durable records, reconcile any in-flight receipt, and restore branch state before continuing inside a partially completed block. The checkpoint report covers operational quality. Comparative results remain masked until the fixed target is complete. See `spec/collection.json` for the close, resume and correction rules.

## Offline checks

Use Python 3.12 and the standard library. From the extracted package run:

```
python checks/validate_design.py
```

This verifies the delivered banks, every permitted offer valuation against an independent four-state ledger, the hand-worked fixtures, selected state transitions, and the proposed call limits. To reproduce the menu CSVs from the release inputs, use the following in a working copy:

```
python checks/build_menus.py
python checks/validate_design.py
```

spec/schedule_inventory.json records the input-bank hashes. SHA256SUMS.txt covers the release files except the checksum list. audit.txt records the checks performed during design. checks/example_messages.json displays the public messages for a specified pilot menu before referral and after an explicitly assumed rule. It is an illustration of formatting, independent of any observed response.

## Reading the records

A paid purchase attempt has one unique attempt_id. Save the actual request and first response/error, membership data, model identifiers and costs using attempt.schema.json. The separate path_event.schema.json schema is a projection for each (stage, family, operator, recurrence, policy, period). A common referral attempt can appear in both CASE and RULE projections. REVIEW_ALL has no paid attempt and a review on each period. An upfront clause is initial preparation and has later_clause_issued = 0. On an API or format failure, retain an explicit NO_EXECUTION record, value zero and state unchanged. Keep DECLINE for an agent or operator who actually chose it.

The response schema describes the general referral format. Standing and upfront authorities additionally require ACT/NONE. The parser rejects duplicate keys, markdown fences, trailing prose, extra fields and unknown values. A well-formed CONTROL referral on a same-custody menu is a valid case referral and cannot issue a rule. The operator always executes its ruling on a referred purchase, even if the provisional action is DECLINE. The branch parent remains one physical call for billing and repeats as one economically charged review in each projection. See the protocol and collection specification for budgeting, checkpointing, invalid attempts, and main-stage entry.

## Scientific sources

- Rudd, M. A. (2026). AI agents and digital payment competition. [Paper 2 replication package](https://github.com/murrayrudd/ai-agent-digital-payment-competition).
- Rudd, M. A. (2026). Predictable choices, uncertain valuations. [Paper 1 preprint](https://doi.org/10.2139/ssrn.7674922).

