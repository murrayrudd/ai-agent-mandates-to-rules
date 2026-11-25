"""Reproduce the Paper 3 working-paper tables from the unmodified 48-family archive.
Usage: python analyze.py EXTRACTED_ARCHIVE OUTPUT_DIRECTORY
Requires Python 3.10+, numpy and pandas. No network access.
"""
from pathlib import Path
import argparse
import itertools
import json
import sqlite3

import numpy as np
import pandas as pd

args = argparse.ArgumentParser(description=__doc__)
args.add_argument("archive", type=Path)
args.add_argument("output", type=Path)
opt = args.parse_args()
opt.output.mkdir(parents=True, exist_ok=True)
def save(name, records):
    frame = records if isinstance(records, pd.DataFrame) else pd.DataFrame(records)
    frame.to_csv(opt.output / (name + ".csv"), index=False, float_format="%.8f")

if (opt.archive / "data/journal.sqlite").exists():
    with sqlite3.connect((opt.archive / "data/journal.sqlite").resolve().as_uri()+"?mode=ro",uri=True) as db:
        events = pd.DataFrame([json.loads(b) for b, in db.execute("select body from event")])
    menus = pd.read_csv(opt.archive / "design/reserved/main_sequences.csv.gz")
else:
    events = pd.read_json(opt.archive / "events.jsonl.gz", lines=True, dtype={"family":str})
    menus = pd.read_csv(opt.archive / "menu_roles.csv.gz")
event_keys = ["family","recurrence","period"]
e = events.merge(menus[event_keys+["cell","role"]],on=event_keys,validate="many_to_one")
keys = ["family","operator_code","recurrence","policy"]
assert len(e)==48*2*2*5*12 and e.groupby(keys).size().eq(12).all()
e["L"] = e.loss_100th_c / 100
e["N"] = e.review_count
e["M"] = e.later_clause_issued
e["failed"] = e.valid_first_attempt.eq(False)
e["loss_choice"] = e.L.gt(0)
e["unreferred_loss"] = e.L.gt(0) & e.N.eq(0) & ~e.failed
e["unreferred_ge_2c"] = e.L.ge(2) & e.N.eq(0) & ~e.failed
e["zero_gain_review"] = e.N.gt(0) & e.immediate_recovered_100th_c.eq(0)
e["gain_cents"] = e.immediate_recovered_100th_c.fillna(0)/100
e["missed_purchase"] = e.executed_label.eq("DECLINE") & e.best_value_100th_c.gt(0)
e["needless_purchase"] = e.executed_label.isin(["A","B"]) & e.executed_value_100th_c.lt(0) & e.best_value_100th_c.eq(0)
measures = ["L","N","M","failed","loss_choice","unreferred_loss","unreferred_ge_2c","zero_gain_review","gain_cents","missed_purchase","needless_purchase"]
g=e.groupby(keys)[measures].sum()
save("sequence_outcomes",g.reset_index())
save("menu_diagnostics",e.groupby(["policy","role","cell"]).agg(periods=("L","size"),positive_loss=("loss_choice","sum"),total_loss_c=("L","sum"),failed=("failed","sum")).reset_index())
policies=["REVIEW_ALL","STANDING","CASE","RULE","UPFRONT"]
valid_core=set(e.family)-set(e.loc[e.failed & e.policy.ne("UPFRONT"),"family"])
valid_full=valid_core-set(e.loc[e.failed & e.policy.eq("UPFRONT"),"family"])
intervals=[]; interactions=[]; costs=[]; envelopes=[]
def draws(ids):
    nums=np.array([int(v[1:]) for v in ids])
    rng=np.random.default_rng(20261119)
    blocks=[np.where(nums%2==p)[0] for p in [1,0]]
    return np.concatenate([rng.choice(b,(5000,len(b))) for b in blocks],axis=1)
def interval(a,ix):
    a=np.asarray(a); lo,hi=np.quantile(a[ix].mean(axis=1),[0.025,0.975])
    return {"mean":a.mean(),"lower":lo,"upper":hi}
def strata(frame):
    for k,v in frame.groupby(level=["operator_code","recurrence"]):
        yield k,v.droplevel(["operator_code","recurrence"])
    for r,v in frame.groupby(level="recurrence"):
        yield ("both",r),v.groupby(level=["family","policy"]).mean()

for population,families in [("all",set(e.family)),("valid_core",valid_core),("valid_full",valid_full)]:
    sample=g[g.index.get_level_values("family").isin(families)]
    for (op,rec),part in strata(sample):
        data={v:part[v].unstack().reindex(columns=policies) for v in ["L","N","M"]}
        ix=draws(data["L"].index)
        info={"population":population,"operator":op,"recurrence":rec,"families":len(families)}
        allowed=policies[:4] if population=="valid_core" else policies
        for a,b in itertools.combinations(allowed,2):
            for v in ["L","N"]:
                diff=data[v][a]-data[v][b]
                intervals.append(dict(info,from_policy=a,to_policy=b,measure=v,**interval(diff,ix)))
        if population!="all":
            continue
        # Paired cost differences for every review/drafting price on the reference grid.
        for c,d in itertools.product([0,1,2,5,10,25,50,100],[0,2,10,25,50]):
            G=data["L"]+c*data["N"]+d*data["M"]
            G["UPFRONT"]+=d
            for a,b in itertools.combinations(policies,2):
                costs.append(dict(info,review_c=c,draft_c=d,from_policy=a,to_policy=b,**interval(G[a]-G[b],ix)))
        # Exact lower envelope over all nonnegative routine review prices.
        means=part.groupby(level="policy").mean()
        for d,s,rho,eta in itertools.product([0,2,10,25,50],[0,5,25],[0.5,1,2],[0.5,1,2]):
            K=means.L+d*means.M
            K.loc[["CASE","RULE"]]+=s
            K.loc["UPFRONT"]+=eta*d
            V=means.N.copy();V.loc[["CASE","RULE"]]*=rho
            edges={0.0}
            for a,b in itertools.combinations(policies,2):
                if abs(V[a]-V[b])>1e-10:
                    x=(K[b]-K[a])/(V[a]-V[b])
                    if x>0: edges.add(round(x,12))
            edges=sorted(edges)
            def winners(x):
                score=K+x*V
                return "|".join(p for p in policies if np.isclose(score[p],score.min(),rtol=0,atol=1e-9))
            for i,x in enumerate(edges):
                y=edges[i+1] if i+1<len(edges) else np.inf
                a=winners(x); b=winners((x+y)/2 if np.isfinite(y) else x+1)
                if i==0 or a!=last or b!=last:
                    envelopes.append(dict(info,draft_c=d,setup_c=s,exception_ratio=rho,upfront_ratio=eta,review_c_from=x,at_boundary=a,above_boundary=b))
                last=b
    for op in ["O1","O2","both"]:
        for v in ["L","N"]:
            m=sample[v] if op=="both" else sample[v].xs(op,level="operator_code")
            q=m.groupby(level=["family","recurrence","policy"]).mean().unstack("policy")
            x=(q.CASE-q.RULE).unstack()
            interactions.append(dict(population=population,operator=op,measure=v,**interval(x.high-x.low,draws(x.index))))
save("paired_contrasts",intervals)
save("recurrence_interactions",interactions)
save("net_cost_differences",costs)
save("least_cost_intervals",envelopes)

# Follow both observed continuations from the common trigger. Keep intervening controls.
follow=[]; recovery=[]
for (family,op,rec),part in e[e.policy.isin(["CASE","RULE"])].groupby(keys[:3]):
    rule=part[part.policy.eq("RULE")].set_index("period").sort_index()
    case=part[part.policy.eq("CASE")].set_index("period").sort_index()
    t=rule.index[rule.M.gt(0)]
    if len(t)==0: continue
    t=t.item()
    late=rule.index[(rule.index>t) & rule.role.eq("custody")].tolist()
    labels=["trigger"]+["return_"+str(j+1) for j in range(len(late))]+["end"]
    stages=[t]+late+[12]
    info=dict(family=family,operator=op,recurrence=rec,trigger_period=t,future_focal=len(late),immediate_gain=rule.loc[t,"gain_cents"])
    sums=(case[["L","N"]]-rule[["L","N"]]).loc[t:].cumsum()
    for tag,j in zip(labels,stages):
        follow.append(dict(info,stage=tag,period=j,loss_saved=sums.loc[j,"L"],reviews_saved=sums.loc[j,"N"]))
    for c,d in itertools.product([0,1,2,5,10,25,50,100],[0,2,10,25,50]):
        net=(sums.L+c*sums.N-d).loc[stages].to_numpy()
        cross=np.flatnonzero(net>=-1e-8)
        k=cross[0] if cross.size else None
        recovery.append(dict(info,review_c=c,draft_c=d,first_cross=labels[k] if k is not None else "never",later_reversal=bool(k is not None and np.any(net[k+1:] < -1e-8)),final_net_c=net[-1]))
save("followup_by_return",follow)
save("clause_recovery",recovery)
