from pathlib import Path
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import pandas as pd
import numpy as np
from matplotlib.ticker import FixedLocator
import argparse
parser = argparse.ArgumentParser(description='Render the paper figures from reproduced tables.')
parser.add_argument('tables', type=Path)
parser.add_argument('figures', type=Path)
args = parser.parse_args()
args.figures.mkdir(parents=True, exist_ok=True)
out=args.figures
data=pd.read_csv(args.tables / 'net_cost_differences.csv')
r=data.query("population=='all' and operator=='both' and review_c==1 and draft_c==2 and from_policy=='CASE' and to_policy=='RULE'").set_index('recurrence').loc[['low','high']]
plt.rcParams.update({'font.family':'DejaVu Sans','font.size':8.2,'axes.labelsize':8.2,'axes.titlesize':9.15,'axes.linewidth':.7,'axes.spines.top':False,'axes.spines.right':False,'xtick.labelsize':7.9,'ytick.labelsize':7.9,'xtick.direction':'out','pdf.fonttype':42,'savefig.facecolor':'white'})
fig,(a,b)=plt.subplots(1,2,figsize=(6.65,2.88),gridspec_kw={'width_ratios':[.92,1.12]})
fig.subplots_adjust(left=.104,right=.979,top=.855,bottom=.265,wspace=.38)
a.set_title('A   Observed return to one rule',loc='left',fontweight='bold',pad=9)
a.set_axisbelow(True);a.grid(axis='y',linestyle='-',color='.90',lw=.5);a.axhline(0,ls='-',lw=.8,color='.48')
for i,row in enumerate(r.itertuples()):
 y=row.mean
 a.errorbar(i,y,yerr=[[y-row.lower],[row.upper-y]],fmt='o',color='.12',ms=4,capsize=3,lw=1.15,zorder=3)
 a.annotate(f'{y:+.2f}¢'.replace('-','−'),(i,y),xytext=((9,0) if i==0 else (-10,1)),textcoords='offset points',ha='left' if i==0 else 'right',va='center',fontsize=8.2)
a.set(xlim=(-.43,1.43),ylim=(-2.4,2),xticks=[0,1],xticklabels=['Once','Six times'],yticks=[-2,-1,0,1,2],ylabel='Mean net saving per sequence (¢)',xlabel='Occurrences of the custody tradeoff')
b.set_title('B   Hypothesized return to more rules',loc='left',fontweight='bold',pad=9)
x=np.linspace(0,1,401); peak=.59;y=1-((x-peak)/peak)**2
b.plot(x,y,color='.15',ls=(0,(5,2)),lw=1.7)
b.set(xlim=(0,1),ylim=(-.045,1.2),xticks=[0,1],xticklabels=['Fewer','More'],yticks=[],ylabel='Expected net value to the operator',xlabel='Tradeoffs covered by adopted rules')
for lbl,align in zip(b.get_xticklabels(),['left','right']):lbl.set_ha(align)
b.plot(peak,1,marker='o',ms=4,mec='.12',mfc='white',zorder=3);b.annotate('Illustrative peak',(peak,1),xytext=(0,9),textcoords='offset points',ha='center',fontsize=8)
for ax in (a,b):ax.xaxis.labelpad=7;ax.yaxis.labelpad=5
for ext in ('png','pdf'):fig.savefig(out/f'Figure_3_Value_of_Mandate_Specification.{ext}',dpi=375,bbox_inches='tight',pad_inches=.06)
plt.close(fig)
