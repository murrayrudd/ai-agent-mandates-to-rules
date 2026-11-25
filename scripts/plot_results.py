from pathlib import Path
import pandas as pd, numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.ticker import MultipleLocator
import argparse
parser = argparse.ArgumentParser(description='Render the paper figures from reproduced tables.')
parser.add_argument('tables', type=Path)
parser.add_argument('figures', type=Path)
args = parser.parse_args()
args.figures.mkdir(parents=True, exist_ok=True)
o=args.figures
t=args.tables
plt.rcParams.update({'font.family':'DejaVu Sans','font.size':9,'axes.spines.top':False,'axes.spines.right':False,'axes.linewidth':.7,'xtick.direction':'out','ytick.direction':'out','pdf.fonttype':42,'axes.axisbelow':True,'legend.frameon':False,'savefig.facecolor':'white'})
def export(fig,name):
 for ext in ['pdf','png']:fig.savefig(o/(name+'.'+ext),dpi=360,bbox_inches='tight',pad_inches=.08)
 plt.close(fig)
f=pd.read_csv(t/'followup_by_return.csv').query("recurrence=='high'").copy()
f['value']=f.loss_saved+f.reviews_saved
fig,ax=plt.subplots(figsize=(6.3,2.95));fig.subplots_adjust(bottom=.31,left=.11,right=.98,top=.96)
order=['trigger']+['return_'+str(i) for i in range(1,6)]
for op,style,ms in [('O1','-','o'),('O2','--','s')]:
 v=f.loc[f.operator==op].groupby('stage').value.mean().loc[order];ax.plot(range(6),v,ls=style,marker=ms,color='0.13' if op=='O1' else '0.40',mfc='white' if op=='O2' else '0.13',lw=1.65,ms=5,label=('2¢' if op=='O1' else '10¢')+' value of control')
ax.axhline(2,color='.4',ls=':',lw=1.2);ax.text(.07,2.10,'2¢ drafting cost',ha='left',fontsize=8,color='.28')
ax.set(xlim=(-.10,5.12),ylim=(-.14,4.0),ylabel='Cumulative gross savings (¢)',xlabel='Custody choices after the first qualifying ruling',xticks=range(6),xticklabels=['Ruling','1','2','3','4','5']);ax.yaxis.set_major_locator(MultipleLocator(1));ax.grid(axis='y',color='.90',lw=.6);ax.legend(loc='upper center',bbox_to_anchor=(.5,-.33),ncol=2,fontsize=8.5)
export(fig,'Figure_1_Rule_Savings')
s=pd.read_csv(t/'sequence_outcomes.csv').query("recurrence=='high'").groupby('policy')[['L','N','M']].mean()
x=np.linspace(0,2.25,1001);fig,ax=plt.subplots(figsize=(6.35,3.55));fig.subplots_adjust(left=.11,right=.98,top=.95,bottom=.34)
curves={}
styles=[('REVIEW_ALL','Full operator approval','-', '.48'),('CASE','Case ruling','--','.10'),('RULE','Reusable rule','-.','.15'),('UPFRONT','Advance rule',':','.1'),('STANDING','Mandate only',(0,(6,2,1,2)),'.44')]
for pol,label,ls,c in styles:
 row=s.loc[pol];curves[pol]=row.L+(4 if pol=='UPFRONT' else 2*row.M)+x*row.N
 ax.plot(x,curves[pol],label=label,ls=ls,color=c,lw=1.65)
a=pd.read_csv(t/'least_cost_intervals.csv').query("population=='all' and operator=='both' and recurrence=='high' and draft_c==2 and setup_c==0 and exception_ratio==1 and upfront_ratio==2")
for r in a.iloc[1:].itertuples():
 z=r.review_c_from;yy=np.interp(z,x,curves[r.above_boundary]);ax.scatter(z,yy,color='black',s=17,zorder=4);ax.annotate(f'{z:.3f}¢',(z,yy),xytext=(15,-2) if z<.1 else (4,-13),textcoords='offset points',fontsize=8,va='top',bbox=dict(boxstyle='square,pad=.1',facecolor='white',edgecolor='none',alpha=.88))
ax.set(xlim=(0,2.25),ylim=(0,6),xlabel='Cost of one operator review (¢)',ylabel='Mean total cost per sequence (¢)');ax.yaxis.set_major_locator(MultipleLocator(1));ax.xaxis.set_major_locator(MultipleLocator(.5));ax.grid(axis='y',lw=.6,color='.89');ax.legend(loc='upper center',bbox_to_anchor=(.5,-.30),ncol=3,fontsize=8.2,columnspacing=1.5,handlelength=2.8);export(fig,'Figure_2_Review_Prices')
