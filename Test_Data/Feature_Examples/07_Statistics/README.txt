STATISTICS WORKBENCH
====================
Replay run_example.py with this directory as input; start an empty project.
study.csv contains 60 rows, three groups of 20, seeded noisy value measurements,
paired repeated values, and an exact control relation linear=3*index+2.

GUI: Analysis > Statistics. Try each scope with the following mappings:
- Single, Complete report: primary value (summary/quantiles/normality/outliers/CI).
- Two columns, Complete comparison: value versus paired (agreement/correlations,
  paired and independent tests). Paired rows correspond by position.
- Two columns, Linear regression: index versus linear; slope=3, intercept=2,
  R-squared=1. Use the exact relation only as a numerical control.
- Multiple columns, Complete report: value, paired, index (correlations/PCA).
- Grouped, Complete report: primary value, group column group (summaries,
  assumptions, ANOVA, Kruskal-Wallis, Tukey and adjusted pairwise comparisons).
Select a companion histogram/normal curve, scatter/regression, box/violin,
correlation heatmap or PCA variance according to scope. Replay also creates normal
and grouped companion data and exports a histogram.

Expected: 60 complete numeric samples, three groups of 20, and group means near
2,4,6. The exact seeded overall mean is in expected.json. Inspect diagnostics,
not only p-values; the complete-report menu does not mean every listed test is
scientifically suitable for the same question. Noise-free controls are not used
as evidence for hypothesis-test assumptions. Tables include their operation keys.
