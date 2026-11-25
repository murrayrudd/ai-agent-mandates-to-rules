"""Estimate the main sample from the 16 reserved calibration families only."""
import collections
import csv
import itertools
import json
import math
from fractions import Fraction
from pathlib import Path
import gzip
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'design' / 'checks'))
import instrument

FAMILIES = tuple(f'D{i:03d}' for i in range(1, 17))
CORE = ('REVIEW_ALL', 'STANDING', 'CASE', 'RULE')

DESIGN_ANALYSIS=instrument.D['sampling']
MULTIPLIER=Fraction(DESIGN_ANALYSIS['preliminary_size_t975_df14'])
H={'loss_cents':Fraction(DESIGN_ANALYSIS['half_width_loss_c']),
   'review_count':Fraction(DESIGN_ANALYSIS['half_width_review_count'])}
OPERATORS=tuple(instrument.PREMIUM)
RECURRENCE=('low','high')

def write_csv(path,rows):
    with path.open('w',encoding='utf8',newline='') as stream:
        writer=csv.DictWriter(stream,fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)

def families_by_parity(families):
    return [[f for f in families if int(f[1:])%2==k] for k in (1,0)]

def pooled_variance(values):
    blocks=families_by_parity(tuple(values))
    if [len(b) for b in blocks]!=[8,8]:
        raise ValueError('The variance rule requires all 16 balanced, complete calibration families.')
    total=Fraction(0)
    for block in blocks:
        mean=sum((values[f] for f in block),Fraction(0))/len(block)
        total+=sum((values[f]-mean)**2 for f in block)
    return total/14

def grouped_sequences(events):
    groups=collections.defaultdict(list)
    for event in events:
        if event['stage']!='precision' or event['family'] not in FAMILIES:
            raise ValueError('Calibration-only analysis received a different stage or family.')
        groups[(event['family'],event['operator_code'],event['recurrence'],event['policy'])].append(event)
    expected=set(itertools.product(FAMILIES,OPERATORS,RECURRENCE,CORE))
    if set(groups)!=expected: raise ValueError('A core sequence is absent.')
    result={}
    for key,ev in groups.items():
        if sorted(e['period'] for e in ev)!=list(range(1,13)):
            raise ValueError('A sequence repeats or lacks a purchase period.')
        result[key]={'loss_cents':sum(Fraction(x['loss_100th_c'],100) for x in ev),
                     'review_count':sum(Fraction(x['review_count']) for x in ev)}
    return result

def selection(events,out_dir):
    seq=grouped_sequences(events)
    rows=[];differences=[];raw_requirements=[]
    def add(name,operator,rec,outcome,vs):
        v=pooled_variance(vs)
        needed=MULTIPLIER**2*v/H[outcome]**2
        raw_requirements.append(needed)
        id_=f'{operator}/{rec}/{name}/{outcome}'
        row={'contrast_id':id_,'comparison':name,'operator':operator,'recurrence':rec,'outcome':outcome,
             'families':len(vs),'df':14,'mean_family_difference':float(sum(vs.values())/16),
             'pooled_within_parity_variance':float(v),'pooled_within_parity_sd':math.sqrt(v),
             'target_halfwidth':float(H[outcome]),'unrounded_required_families':float(needed),
             'required_families_ceiling':math.ceil(needed)}
        rows.append(row)
        for f,vf in vs.items():differences.append({'contrast_id':id_,'family':f,'parity':'odd' if int(f[1:])%2 else 'even','difference':float(vf)})
    def diff(f,op,r,pair,x):
        return seq[(f,op,r,pair[0])][x]-seq[(f,op,r,pair[1])][x]
    for op in OPERATORS:
        for rec in RECURRENCE:
            for pair in itertools.combinations(CORE,2):
                for measure in H:
                    add(pair[0]+' minus '+pair[1],op,rec,measure,
                        {f:diff(f,op,rec,pair,measure) for f in FAMILIES})
        for measure in H:
            add('High minus low difference in CASE minus RULE',op,'high minus low',measure,
                {f:diff(f,op,'high',('CASE','RULE'),measure)-diff(f,op,'low',('CASE','RULE'),measure) for f in FAMILIES})
    if len(rows)!=52 or len(differences)!=832: raise ValueError('Incomplete primary contrast grid.')
    most=max(raw_requirements)
    nmin=DESIGN_ANALYSIS['main_minimum']; step=DESIGN_ANALYSIS['main_round_up_multiple']
    n=math.ceil(Fraction(max(nmin,math.ceil(most)),step))*step
    binding=[r for r,raw in zip(rows,raw_requirements,strict=True) if raw==most]
    options=sorted(set([24,48,128,n]))
    precision=[]
    for sample in options:
        data={'main_families':sample}
        for x in H:
            max_sd=max(v['pooled_within_parity_sd'] for v in rows if v['outcome']==x)
            data['largest_planning_halfwidth_'+x]=float(MULTIPLIER)*max_sd/math.sqrt(sample)
        precision.append(data)
    result={'planning_families':16,'odd':8,'even':8,'within_parity_df':14,'multiplier':float(MULTIPLIER),
            'contrasts_and_outcomes':52,'largest_unrounded_requirement':float(most),
            'largest_requirement_rounded_up_to_integer':math.ceil(most),'design_minimum':nmin,
            'rounding_multiple':step,'indicated_main_families':n,'within_existing_reserve':n<=128,
            'binding_contrasts':binding,'planned_halfwidths':precision}
    out_dir.mkdir(parents=True,exist_ok=True)
    write_csv(out_dir/'primary_contrast_variances.csv',rows)
    write_csv(out_dir/'primary_family_differences.csv',differences)
    write_csv(out_dir/'family_policy_sequences.csv',[{'family':f,'operator':op,'recurrence':r,'policy':p,
              'loss_cents':float(v['loss_cents']),'reviews':int(v['review_count'])}
              for (f,op,r,p),v in sorted(seq.items())])
    (out_dir/'main_sample_size.json').write_text(json.dumps(result,indent=2)+'\n')
    return result


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('events', type=Path)
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    with gzip.open(args.events, 'rt', encoding='utf8') as stream:
        selection((json.loads(line) for line in stream), args.output)
