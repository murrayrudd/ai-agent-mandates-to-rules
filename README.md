# From mandates to rules

**When is it worth specifying how an AI purchasing agent should decide?**  
Murray A. Rudd · Futures Insight Research Ltd. · Working paper, November 2026  
Replication materials · Version 1.0.0

A purchasing agent can know that its operator prefers to hold the keys to a reserve and still have to decide how much extra to pay for control. This matched choice experiment gave two simulated operators the same general mandate and assigned them different values for control, 2¢ and 10¢ per purchase. Across five governance arrangements, the experiment varied who could settle the tradeoff, when the agent could ask, and whether the operator’s ruling could guide later purchases.

When the tradeoff arose six times in 12 opportunities, a reusable rule reduced reviews from 3.88 to 1.02 per sequence, a 74% reduction relative to case rulings. At 1¢ per review and 2¢ to draft a rule, reuse saved 1.22¢ per sequence on average. When the tradeoff arose once, reuse added 1.92¢ per sequence. The return to specifying the operator’s preference depended on how often the agent could use the answer. [Results tables](results/manuscript/) · [Figures](results/figures/)

## Reproduce the paper

Extract the repository and run these commands from its root. The tested environment used Python 3.12.14. The dependency installation needs access to the listed packages. All research calculations run offline from archived responses.

```sh
python -m pip install -r requirements.txt
python scripts/reproduce.py
```

The command verifies the release checksums, tests the design arithmetic, rebuilds the prompts and decisions for all three stages, and repeats the calibration sample-size calculation. It then reproduces the eight analysis tables, the three numerical manuscript tables, the supporting counts in the Results text, and Figures 1–3. Rebuilt files appear under `build/`. The checks compare CSV values with the archived tables and rendered PNG pixels with the reference figures. For exact figure rendering, use the pinned Matplotlib and Pillow versions with Matplotlib’s bundled DejaVu Sans font. Publication figures are supplied as PDF and PNG.

## Research basis

This is the third study in a series on AI purchasing agents. The first examined whether observed payment choices support reliable preference estimates. The second studied how operator mandates change choices among payment services. The present study asks when a ruling on a single purchase justifies writing a rule for subsequent purchases. It supplies the experiment’s full mandate, offer attributes, utility functions, and decision procedure. [Paper 1](https://doi.org/10.2139/ssrn.7674922) · [Paper 2 replication repository](https://github.com/murrayrudd/ai-agent-digital-payment-competition) · [Paper 3 protocol](design/Paper_3_Experimental_Protocol.docx)

The main experiment used GPT-6.2 Sol on the dated OpenAI route specified before collection. The two operator profiles were simulated and their values were assigned in the design. On each purchase, the agent chose between two offers and declining. Under full operator approval, the simulated operator chose directly. The analysis compares purchase loss and review requirements within matched families. Its pointwise 95% intervals resample families within the odd and even schedule groups using 5,000 draws. Review and drafting prices are assigned to the recorded decisions during analysis. [Mandate](design/prompts/mandate.txt) · [Decision and scoring code](design/checks/instrument.py) · [Analysis specification](design/spec/analysis.json)

| Stage | Matched families | First model requests | Scored purchase outcomes | Purpose |
| --- | ---: | ---: | ---: | --- |
| Pilot | 2 | 372 | 480 | Qualification and implementation checks. The request count includes eight qualification questions. |
| Calibration | 16 | 2,142 | 3,072 | Sample-size planning across the four primary arrangements. |
| Main | 48 | 8,695 | 11,520 | Reported estimates for all five arrangements. |

Each main family contained two operators, two recurrence conditions, five arrangements, and 12 opportunities. A request could contribute to both referral arrangements before their paths diverged. Full operator approval required no model request. The five failed main requests remain in the primary estimates under the prespecified fallback. [Stage records and field definitions](docs/data-guide.md) · [Precollection main sample decision](development/main_sample_amendment.json)

## Repository contents

| Location | What it contains |
| --- | --- |
| [design](design/) | Dated protocol, exact prompts, offer attributes, utility functions, menu banks, allocation rules, schemas, and instrument checks. |
| [data/main](data/main/) | First requests and visible responses, scored outcomes, menu-role assignments, and skipped conditional slots for M001–M048. |
| [development](development/) | Disjoint pilot and calibration records, family-level planning contrasts, and the prospective decision to use 48 main families. |
| [collection](collection/) | Original stage-specific collector and audit source preserved as implementation records. |
| [scripts](scripts/) | Offline replay, calibration, paired analysis, manuscript-table assembly, and figure production. |
| [results/manuscript](results/manuscript/) | Tables 1–5 as displayed in the working paper and the calculation details for key statements in the Results. |
| [results/analysis](results/analysis/) | Family-level outcomes, paired contrasts, recurrence interactions, cost comparisons, price thresholds, and rule recovery. |
| [results/figures](results/figures/) | Three figures in vector PDF and high-resolution PNG. Figure 3A reports the observed net return to one rule. Figure 3B illustrates a hypothesis about adopting additional rules. |

## Citation

> Rudd, M. A. (2026). *From mandates to rules: When is it worth specifying how an AI purchasing agent should decide?* Working paper, Futures Insight Research Ltd.

**Working-paper DOI:** Pending SSRN submission and assignment.

```bibtex
@unpublished{Rudd2026MandatesToRules,
  author = {Rudd, Murray A.},
  title = {From mandates to rules: When is it worth specifying how an {AI} purchasing agent should decide?},
  year = {2026},
  note = {Working paper, Futures Insight Research Ltd.}
}
```

Please cite the paper and identify the replication-package version and commit used. GitHub’s **Cite this repository** option uses the preferred paper citation in [CITATION.cff](CITATION.cff).

## License

The MIT License covers Murray A. Rudd’s original project code and associated software documentation. Archived model responses and third-party materials retain their applicable terms. [MIT License](LICENSE.md)

## Author

**Murray A. Rudd, Ph.D.**  
Institutional economist and policy researcher, Futures Insight Research Ltd.

- [ORCID 0000-0001-9533-5070](https://orcid.org/0000-0001-9533-5070)
- [SSRN author profile](https://papers.ssrn.com/sol3/cf_dev/AbsByAuth.cfm?per_id=5958022)
- [Google Scholar profile](https://scholar.google.co.uk/citations?hl=en&user=84qbofEAAAAJ)
