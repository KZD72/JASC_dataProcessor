DATA PREPARATION
================
Replay run_example.py with this directory as input; start an empty project.
GUI: import dirty.csv and labels.csv. Use the corresponding Data menu operations.

1. Missing Values: measurement, drop rows. Remove Duplicates: id, keep first. Sort: id
   ascending. The ten raw rows become seven clean rows: id=1,2,3,5,6,7,8.
2. Filter/Query: measurement > 50 gives id=6,7,8.
3. Extract Subset: odd visible rows gives id=1,3,6,8 (positions are 1-based).
4. Group/Aggregate: group by group, value column measurement, count/mean/sum. A has
   count=3, mean=20, sum=60; B has count=4, mean=65, sum=260.
5. Merge/Join: left join Clean with Labels on group; all seven rows receive a label.
6. Reshape: melt measurement and repeat_value, retaining id; expect fourteen rows.
   Avoid an input column named value, which conflicts with the current melt output.
7. Bin/Average: id, measurement, two bins; sample counts are three and four.

Results are new worksheets. Raw is retained with its duplicates and missing value.
Replay exports Clean, Filtered, Odd rows, Grouped, Joined, Long form and Binned.
Use these simple known values to check settings before applying them to real data.
