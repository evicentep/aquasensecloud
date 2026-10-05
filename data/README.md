# Synthetic example data

`sample_temperatures.csv` was created for this curated edition. It is not a measurement dataset from the academic project.

With the retained processing rules it produces:

| Month | Mean temperature | Maximum weekly temperature | Maximum deviation | Difference from prior available maximum |
| --- | --- | --- | --- | --- |
| 2025-01 | 16.0 | 17.0 | 0.7 | Empty |
| 2025-02 | 19.0 | 19.0 | 0.2 | 2.0 |

The week beginning 2025/01/13 exceeds the 0.5 alert threshold. The offline tests simulate delivery only.
