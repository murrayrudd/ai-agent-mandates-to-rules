"""Write the displayed Results tables and the counts behind the text from the main data."""
import argparse
from pathlib import Path

import pandas as pd


ARRANGEMENTS = {
    "REVIEW_ALL": "Full operator approval",
    "STANDING": "Mandate-only delegation",
    "CASE": "Referral with case ruling",
    "RULE": "Referral with reusable rule",
    "UPFRONT": "Delegation with advance rule",
}


def table3(seq):
    values = seq.groupby(["operator_code", "policy", "recurrence"])[["L", "N"]].mean()
    rows = []
    for operator, premium in [("O1", 2), ("O2", 10)]:
        for policy, name in ARRANGEMENTS.items():
            row = [name, premium]
            for recurrence in ["low", "high"]:
                point = values.loc[operator, policy, recurrence]
                row.extend(f"{point[var]:.2f}" for var in ["L", "N"])
            rows.append(row)
    return pd.DataFrame(rows, columns=["Governance arrangement", "Control value (¢)", "One case Loss (¢)",
                                       "One case Reviews", "Six cases Loss (¢)", "Six cases Reviews"])


def table4(interactions):
    estimates = interactions.query("population == 'all'").set_index(["operator", "measure"])
    rows = []
    for operator, label in [("O1","2¢"), ("O2","10¢"), ("both","Equal-weight mean")]:
        row = [label]
        for measure in ["N", "L"]:
            est = estimates.loc[operator, measure]
            row.append(f"{est['mean']:.2f} [{est.lower:.2f}, {est.upper:.2f}]".replace("-", "−"))
        rows.append(row)
    return pd.DataFrame(rows, columns=["Value of control", "Reviews saved", "Purchase loss avoided (¢)"])


def table5(seq):
    means = seq.groupby(["policy", "recurrence"])[["L","N","M"]].mean()
    rows = []
    for policy, name in ARRANGEMENTS.items():
        row = [name]
        for recurrence, advance_price in [("low", 2), ("high", 2), ("high", 4)]:
            s = means.loc[policy, recurrence]
            total = s.L + s.N + 2*s.M + (advance_price if policy == "UPFRONT" else 0)
            row.append(f"{total:.2f}¢")
        rows.append(row)
    return pd.DataFrame(rows, columns=["Governance arrangement", "One case 2¢ in advance",
                                       "Six cases 2¢ in advance", "Six cases 4¢ in advance"])


def diagnostics(data, analysis):
    events = pd.read_json(data / "events.jsonl.gz", lines=True)
    menus = pd.read_csv(data / "menu_roles.csv.gz")
    e = events.merge(menus, on=["family","recurrence","period"], validate="many_to_one")
    high = e.query("recurrence == 'high'")
    low_premium = high.query("operator_code == 'O1'")
    advance = e.query("policy == 'UPFRONT'")
    transfer = high.query("role == 'custody' and cell == 'transfer'")
    case = e.query("policy == 'CASE'")
    valid = e.valid_first_attempt.eq(True)
    q = pd.read_csv(analysis / "clause_recovery.csv").query("review_c == 1 and draft_c == 2")
    high_rec = q.query("recurrence == 'high'")
    high_reviews = high.groupby("policy").review_count.sum()
    stats = {
        "high_recurrence_review_reduction_pct": 100*(1-high_reviews.RULE/high_reviews.CASE),
        "low_premium_first_rulings_confirmed_high": len(low_premium.query("policy == 'RULE' and later_clause_issued == 1 and immediate_recovered_100th_c == 0")),
        "low_premium_reviews_saved_high": low_premium.query("policy == 'CASE'").review_count.sum()-low_premium.query("policy == 'RULE'").review_count.sum(),
        "low_premium_case_loss_high_c": low_premium.query("policy == 'CASE'").loss_100th_c.sum()/100,
        "low_premium_rule_loss_high_c": low_premium.query("policy == 'RULE'").loss_100th_c.sum()/100,
        "low_premium_rule_loss_failed_high_c": low_premium[low_premium.policy.eq("RULE") & low_premium.valid_first_attempt.eq(False)].loss_100th_c.sum()/100,
        "transfer_rule_already_in_force_optimal_unreviewed": len(transfer.query("policy == 'RULE' and carry_rule_before == True and review_count == 0 and loss_100th_c == 0")),
        "transfer_rule_trigger_and_review": len(transfer.query("policy == 'RULE' and later_clause_issued == 1 and review_count == 1")),
        "advance_valid_optimal": len(advance[advance.valid_first_attempt.eq(True) & advance.loss_100th_c.eq(0)]),
        "advance_failed_optimal_to_decline": len(advance[advance.valid_first_attempt.eq(False) & advance.best_value_100th_c.eq(0)]),
        "case_reviews_all": case.review_count.sum(),
        "case_reviews_with_zero_immediate_gain": len(case.query("review_count == 1 and immediate_recovered_100th_c == 0")),
        "case_valid_unreviewed_losses": len(e[valid].query("policy == 'CASE' and review_count == 0 and loss_100th_c > 0")),
        "rule_valid_unreviewed_losses": len(e[valid].query("policy == 'RULE' and review_count == 0 and loss_100th_c > 0")),
        "low_recurrence_rules_issued": len(q.query("recurrence == 'low'")),
        "high_recurrence_above_or_at_break_even_at_end": high_rec.final_net_c.ge(0).sum(),
        "high_recurrence_subsequent_reversals": high_rec.later_reversal.sum(),
    }
    for k, value in high_rec.first_cross.value_counts().items():
        stats["high_recurrence_first_break_even_" + k] = value
    return pd.DataFrame(stats.items(), columns=["quantity","value"])


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("data", type=Path)
    parser.add_argument("analysis", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    seq = pd.read_csv(args.analysis / "sequence_outcomes.csv")
    interactions = pd.read_csv(args.analysis / "recurrence_interactions.csv")
    for name, df in [("table_3_loss_and_reviews", table3(seq)), ("table_4_recurrence", table4(interactions)),
                     ("table_5_total_cost", table5(seq)), ("text_diagnostics", diagnostics(args.data, args.analysis))]:
        df.to_csv(args.output / (name + ".csv"), index=False, float_format="%.8f")
