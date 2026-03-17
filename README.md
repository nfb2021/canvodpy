# Repository Coverage

[Full report](https://htmlpreview.github.io/?https://github.com/nfb2021/canvodpy/blob/python-coverage-comment-action-data/htmlcov/index.html)

| Name                                                                            |    Stmts |     Miss |   Cover |   Missing |
|-------------------------------------------------------------------------------- | -------: | -------: | ------: | --------: |
| canvodpy/src/canvodpy/\_\_init\_\_.py                                           |       48 |        8 |     83% |248-249, 255-256, 262-263, 269-270 |
| canvodpy/src/canvodpy/api.py                                                    |      125 |       55 |     56% |105, 110-114, 119, 124, 183, 197-199, 202, 295-302, 359, 362, 365, 393-410, 442-447, 479-512, 529, 532, 592-598, 648-653, 677-678 |
| canvodpy/src/canvodpy/cli/\_\_init\_\_.py                                       |        0 |        0 |    100% |           |
| canvodpy/src/canvodpy/cli/run.py                                                |      158 |      158 |      0% |    21-366 |
| canvodpy/src/canvodpy/diagnostics/\_\_init\_\_.py                               |        2 |        2 |      0% |       7-9 |
| canvodpy/src/canvodpy/diagnostics/sbf\_timing\_diagnostics\_new\_api.py         |      100 |      100 |      0% |    13-229 |
| canvodpy/src/canvodpy/diagnostics/timing\_diagnostics\_new\_api.py              |      100 |      100 |      0% |    13-233 |
| canvodpy/src/canvodpy/diagnostics/timing\_diagnostics\_script.py                |      101 |      101 |      0% |     9-237 |
| canvodpy/src/canvodpy/factories.py                                              |       89 |       28 |     69% |234-257, 273-291 |
| canvodpy/src/canvodpy/fluent.py                                                 |      172 |      116 |     33% |124-126, 152-201, 216-282, 293-305, 327-364, 378-388, 401-412, 425-427, 432-440, 445-449 |
| canvodpy/src/canvodpy/functional.py                                             |       81 |       65 |     20% |88-98, 138-160, 204-210, 244-254, 305-317, 368-379, 420-435, 476-500, 560-580 |
| canvodpy/src/canvodpy/globals.py                                                |        9 |        9 |      0% |      8-50 |
| canvodpy/src/canvodpy/logging/\_\_init\_\_.py                                   |        6 |        0 |    100% |           |
| canvodpy/src/canvodpy/logging/context.py                                        |       11 |       11 |      0% |      3-37 |
| canvodpy/src/canvodpy/logging/logging\_config.py                                |      149 |       13 |     91% |68, 114, 128, 151, 196, 226-228, 430-435 |
| canvodpy/src/canvodpy/orchestrator/\_\_init\_\_.py                              |       14 |        7 |     50% |     38-46 |
| canvodpy/src/canvodpy/orchestrator/interpolator.py                              |      128 |        7 |     95% |175, 198-201, 321, 328, 334-340 |
| canvodpy/src/canvodpy/orchestrator/matcher.py                                   |       46 |       46 |      0% |     3-158 |
| canvodpy/src/canvodpy/orchestrator/pipeline.py                                  |      451 |      402 |     11% |27-29, 79-138, 150-160, 164-168, 171, 174, 193-205, 223-272, 283-313, 317-334, 359-376, 398-417, 442-538, 557, 581-591, 622-629, 660-1028, 1062-1097, 1131-1181, 1219-1226, 1233-1244, 1260-1292, 1301-1325 |
| canvodpy/src/canvodpy/orchestrator/processor.py                                 |     1632 |     1541 |      6% |17-20, 70, 133-307, 321-335, 345-368, 378-385, 395-403, 420-445, 460-478, 493-512, 560-626, 642-692, 705-707, 740, 752-912, 931-965, 995-1037, 1041-1047, 1078-1108, 1137-1181, 1227-1239, 1264-1372, 1389-1493, 1505-1534, 1554-1621, 1646-1939, 1966-2030, 2046-2355, 2375-2782, 2800-3043, 3059-3074, 3106-3243, 3274-3425, 3464-3691, 3713-3744, 3767-3867, 3870, 3899, 3902, 3918-4034, 4042-4167, 4181-4448, 4480-4609, 4613-4677 |
| canvodpy/src/canvodpy/orchestrator/resources.py                                 |       79 |       48 |     39% |38, 42, 46, 57-58, 98-99, 103-128, 173-200, 205, 209-221, 230-233, 236, 239 |
| canvodpy/src/canvodpy/utils/\_\_init\_\_.py                                     |        2 |        0 |    100% |           |
| canvodpy/src/canvodpy/utils/perf.py                                             |        2 |        0 |    100% |           |
| canvodpy/src/canvodpy/utils/telemetry.py                                        |      106 |       38 |     64% |43-45, 52-86, 132-157, 204-210, 259-262, 303, 349-352 |
| canvodpy/src/canvodpy/vod\_computer.py                                          |       87 |       71 |     18% |71-74, 110-125, 156-196, 228-247, 256-269, 281-296, 300-306, 315-319, 324-328, 331 |
| canvodpy/src/canvodpy/workflow.py                                               |       92 |       23 |     75% |132-134, 221-223, 285-286, 343-365, 456-462 |
| canvodpy/src/canvodpy/workflows/\_\_init\_\_.py                                 |        2 |        2 |      0% |      3-11 |
| canvodpy/src/canvodpy/workflows/tasks.py                                        |      292 |      292 |      0% |    19-785 |
| packages/canvod-audit/src/canvod/audit/\_\_init\_\_.py                          |        5 |        0 |    100% |           |
| packages/canvod-audit/src/canvod/audit/\_meta.py                                |        1 |        0 |    100% |           |
| packages/canvod-audit/src/canvod/audit/core.py                                  |      122 |       12 |     90% |59, 78-80, 141, 150, 186, 263, 268-269, 272-273 |
| packages/canvod-audit/src/canvod/audit/rinex\_trimmer.py                        |      194 |      141 |     27% |40-47, 55-77, 111-136, 156-217, 259-308, 358, 410-451, 496-529 |
| packages/canvod-audit/src/canvod/audit/runners/\_\_init\_\_.py                  |       11 |        0 |    100% |           |
| packages/canvod-audit/src/canvod/audit/runners/api\_levels.py                   |       32 |       26 |     19% |    72-115 |
| packages/canvod-audit/src/canvod/audit/runners/common.py                        |       56 |       25 |     55% |67-76, 85-89, 98-108, 113-116 |
| packages/canvod-audit/src/canvod/audit/runners/constellation\_filter.py         |       24 |       19 |     21% |    65-102 |
| packages/canvod-audit/src/canvod/audit/runners/ephemeris.py                     |       28 |       21 |     25% |   101-139 |
| packages/canvod-audit/src/canvod/audit/runners/idempotency.py                   |       20 |       15 |     25% |     61-85 |
| packages/canvod-audit/src/canvod/audit/runners/regression.py                    |       53 |       45 |     15% |67-94, 128-170 |
| packages/canvod-audit/src/canvod/audit/runners/round\_trip.py                   |       49 |       40 |     18% |56-100, 105-138 |
| packages/canvod-audit/src/canvod/audit/runners/sbf\_vs\_rinex.py                |       21 |       15 |     29% |   104-129 |
| packages/canvod-audit/src/canvod/audit/runners/temporal\_chunking.py            |       22 |       17 |     23% |     61-88 |
| packages/canvod-audit/src/canvod/audit/runners/vs\_gnssvod.py                   |      245 |      163 |     33% |156, 207, 271, 321-366, 433-436, 460-472, 482-501, 506-522, 538-582, 657-774 |
| packages/canvod-audit/src/canvod/audit/stats.py                                 |       64 |        0 |    100% |           |
| packages/canvod-audit/src/canvod/audit/tiers/\_\_init\_\_.py                    |        0 |        0 |    100% |           |
| packages/canvod-audit/src/canvod/audit/tiers/regression.py                      |       17 |        0 |    100% |           |
| packages/canvod-audit/src/canvod/audit/tolerances.py                            |       24 |        0 |    100% |           |
| packages/canvod-auxiliary/src/canvod/auxiliary/\_\_init\_\_.py                  |       26 |        4 |     85% |117-118, 140-141 |
| packages/canvod-auxiliary/src/canvod/auxiliary/\_internal/\_\_init\_\_.py       |        4 |        0 |    100% |           |
| packages/canvod-auxiliary/src/canvod/auxiliary/\_internal/logger.py             |        5 |        0 |    100% |           |
| packages/canvod-auxiliary/src/canvod/auxiliary/\_internal/units.py              |        5 |        1 |     80% |        16 |
| packages/canvod-auxiliary/src/canvod/auxiliary/augmentation.py                  |      205 |      114 |     44% |157, 168, 388-428, 443-463, 489-507, 529-581, 586-634, 642-646, 701-746, 751-771 |
| packages/canvod-auxiliary/src/canvod/auxiliary/clock/\_\_init\_\_.py            |        4 |        0 |    100% |           |
| packages/canvod-auxiliary/src/canvod/auxiliary/clock/parser.py                  |       48 |       41 |     15% |39-53, 82-128, 146-153 |
| packages/canvod-auxiliary/src/canvod/auxiliary/clock/reader.py                  |       49 |       28 |     43% |67-70, 74-78, 97-102, 118-135, 150-171, 188-207 |
| packages/canvod-auxiliary/src/canvod/auxiliary/clock/validator.py               |       32 |        0 |    100% |           |
| packages/canvod-auxiliary/src/canvod/auxiliary/container.py                     |       10 |        0 |    100% |           |
| packages/canvod-auxiliary/src/canvod/auxiliary/core/\_\_init\_\_.py             |        3 |        0 |    100% |           |
| packages/canvod-auxiliary/src/canvod/auxiliary/core/base.py                     |      110 |       75 |     32% |57-65, 99-100, 130-137, 169-171, 209-284, 300, 305, 310-314, 324-331, 336, 341 |
| packages/canvod-auxiliary/src/canvod/auxiliary/core/downloader.py               |      155 |      129 |     17% |29, 64, 87-107, 131-233, 239-262, 266-324, 340-371, 375-377, 381-383 |
| packages/canvod-auxiliary/src/canvod/auxiliary/ephemeris/\_\_init\_\_.py        |        5 |        0 |    100% |           |
| packages/canvod-auxiliary/src/canvod/auxiliary/ephemeris/parser.py              |       79 |       67 |     15% |29-30, 47-135, 155-156, 185-198, 202 |
| packages/canvod-auxiliary/src/canvod/auxiliary/ephemeris/provider.py            |      102 |       85 |     17% |115-120, 144-216, 242-289, 314-315, 323, 349-394 |
| packages/canvod-auxiliary/src/canvod/auxiliary/ephemeris/reader.py              |       79 |       55 |     30% |64-71, 75-79, 88-92, 108-124, 142-159, 163-173, 192-233, 240-247 |
| packages/canvod-auxiliary/src/canvod/auxiliary/ephemeris/validator.py           |       36 |        0 |    100% |           |
| packages/canvod-auxiliary/src/canvod/auxiliary/interpolation/\_\_init\_\_.py    |        2 |        0 |    100% |           |
| packages/canvod-auxiliary/src/canvod/auxiliary/interpolation/interpolator.py    |      129 |       53 |     59% |27, 90, 94, 123, 131-197, 231-247, 306, 368, 373, 393, 425-435 |
| packages/canvod-auxiliary/src/canvod/auxiliary/matching/\_\_init\_\_.py         |        2 |        0 |    100% |           |
| packages/canvod-auxiliary/src/canvod/auxiliary/matching/dataset\_matcher.py     |       38 |       28 |     26% |95-102, 128-135, 152-153, 172-173, 193-194, 222-251 |
| packages/canvod-auxiliary/src/canvod/auxiliary/pipeline.py                      |      107 |       25 |     77% |254, 309-320, 396-445 |
| packages/canvod-auxiliary/src/canvod/auxiliary/position/\_\_init\_\_.py         |        3 |        0 |    100% |           |
| packages/canvod-auxiliary/src/canvod/auxiliary/position/position.py             |       34 |        7 |     79% |    99-107 |
| packages/canvod-auxiliary/src/canvod/auxiliary/position/spherical\_coords.py    |       23 |        0 |    100% |           |
| packages/canvod-auxiliary/src/canvod/auxiliary/preprocessing.py                 |      161 |       56 |     65% |51-57, 148, 152-156, 162, 223, 265-336 |
| packages/canvod-auxiliary/src/canvod/auxiliary/products/\_\_init\_\_.py         |        3 |        0 |    100% |           |
| packages/canvod-auxiliary/src/canvod/auxiliary/products/models.py               |      103 |       19 |     82% |109, 167-176, 192-206 |
| packages/canvod-auxiliary/src/canvod/auxiliary/products/registry\_config.py     |       79 |        8 |     90% |29, 77, 112, 196-197, 205, 251, 256 |
| packages/canvod-grids/src/canvod/grids/\_\_init\_\_.py                          |       26 |        2 |     92% |  181, 186 |
| packages/canvod-grids/src/canvod/grids/\_internal/\_\_init\_\_.py               |        2 |        0 |    100% |           |
| packages/canvod-grids/src/canvod/grids/\_internal/logger.py                     |        5 |        1 |     80% |        26 |
| packages/canvod-grids/src/canvod/grids/aggregation.py                           |      194 |      119 |     39% |226-335, 453, 464, 480-484, 492-504, 513-530, 542-601, 613-625, 642-659 |
| packages/canvod-grids/src/canvod/grids/analysis/\_\_init\_\_.py                 |       16 |        2 |     88% |   126-130 |
| packages/canvod-grids/src/canvod/grids/analysis/filtering.py                    |      215 |      130 |     40% |133, 151-163, 171, 189-210, 218, 243-250, 258, 280-285, 311-312, 320, 365, 394, 460-462, 481-493, 516-639, 643-648, 663, 674 |
| packages/canvod-grids/src/canvod/grids/analysis/hampel\_filtering.py            |      183 |      169 |      8% |79-119, 177-333, 358-366, 397-426, 476-648 |
| packages/canvod-grids/src/canvod/grids/analysis/masking.py                      |      131 |      110 |     16% |58-60, 91-109, 136-144, 172-183, 199-203, 219-223, 254-269, 296-303, 342-358, 395-409, 437-451, 462-488, 499-500, 511-512, 544-559, 582-584 |
| packages/canvod-grids/src/canvod/grids/analysis/per\_cell\_analysis.py          |      272 |      242 |     11% |84-92, 100-104, 117-135, 142-171, 180-211, 224-242, 251-261, 265-282, 290-305, 315-334, 340-350, 366-405, 436-453, 474-476, 504-515, 533-534, 561-594, 611-617, 641 |
| packages/canvod-grids/src/canvod/grids/analysis/per\_cell\_filtering.py         |      150 |      119 |     21% |56, 112-150, 178-224, 241, 261-275, 286, 306-316, 327, 352-357, 368, 390-397, 428-430, 453-465, 486-526, 542, 559 |
| packages/canvod-grids/src/canvod/grids/analysis/sigma\_clip\_filter.py          |      151 |      135 |     11% |92-123, 167-204, 264-391, 438-525 |
| packages/canvod-grids/src/canvod/grids/analysis/solar.py                        |      146 |      123 |     16% |83-100, 124-129, 135-149, 158-249, 254-269, 291-292, 316-317, 353-413, 442-445, 465-477, 490-491, 522-524, 554-558 |
| packages/canvod-grids/src/canvod/grids/analysis/spatial.py                      |       65 |       53 |     18% |80-92, 137-199, 237-268 |
| packages/canvod-grids/src/canvod/grids/analysis/temporal.py                     |      311 |      289 |      7% |105-126, 171-205, 262-323, 334-347, 366-440, 476-568, 608-701, 727-751, 788-859, 886-914, 941-988 |
| packages/canvod-grids/src/canvod/grids/analysis/weighting.py                    |      239 |      209 |     13% |73-77, 116-140, 168-191, 206-217, 233-239, 250-252, 263, 274-284, 300-317, 321-327, 340-378, 382-428, 449-479, 500-531, 538-539, 563-588, 603-610, 635-647, 652-657, 679, 698-700 |
| packages/canvod-grids/src/canvod/grids/core/\_\_init\_\_.py                     |        4 |        0 |    100% |           |
| packages/canvod-grids/src/canvod/grids/core/grid\_builder.py                    |       40 |        2 |     95% |  112, 140 |
| packages/canvod-grids/src/canvod/grids/core/grid\_data.py                       |      118 |       57 |     52% |87-95, 99, 107, 141-165, 169-208, 240-249 |
| packages/canvod-grids/src/canvod/grids/core/grid\_types.py                      |        9 |        0 |    100% |           |
| packages/canvod-grids/src/canvod/grids/grids\_impl/\_\_init\_\_.py              |        8 |        0 |    100% |           |
| packages/canvod-grids/src/canvod/grids/grids\_impl/equal\_angle\_grid.py        |       33 |        0 |    100% |           |
| packages/canvod-grids/src/canvod/grids/grids\_impl/equal\_area\_grid.py         |       43 |        1 |     98% |       177 |
| packages/canvod-grids/src/canvod/grids/grids\_impl/equirectangular\_grid.py     |       22 |        0 |    100% |           |
| packages/canvod-grids/src/canvod/grids/grids\_impl/fibonacci\_grid.py           |       61 |       51 |     16% |125-134, 145, 172-252, 269-285 |
| packages/canvod-grids/src/canvod/grids/grids\_impl/geodesic\_grid.py            |      100 |        2 |     98% |  143, 227 |
| packages/canvod-grids/src/canvod/grids/grids\_impl/healpix\_grid.py             |       46 |       37 |     20% |118-142, 157, 182-234, 247 |
| packages/canvod-grids/src/canvod/grids/grids\_impl/htm\_grid.py                 |       74 |        0 |    100% |           |
| packages/canvod-grids/src/canvod/grids/operations.py                            |      327 |      124 |     62% |209-239, 356, 419-438, 445-465, 477-498, 561, 566-611, 741-758, 811 |
| packages/canvod-grids/src/canvod/grids/workflows/\_\_init\_\_.py                |        2 |        0 |    100% |           |
| packages/canvod-grids/src/canvod/grids/workflows/adapted\_workflow.py           |      187 |      163 |     13% |45-52, 71-73, 105-106, 132-136, 173-227, 277, 334-390, 426-489, 497-508, 517-529, 544-564, 617-695, 716, 735-763 |
| packages/canvod-ops/src/canvod/ops/\_\_init\_\_.py                              |        6 |        0 |    100% |           |
| packages/canvod-ops/src/canvod/ops/base.py                                      |       10 |        0 |    100% |           |
| packages/canvod-ops/src/canvod/ops/grid.py                                      |       55 |        0 |    100% |           |
| packages/canvod-ops/src/canvod/ops/pipeline.py                                  |       29 |        0 |    100% |           |
| packages/canvod-ops/src/canvod/ops/registry.py                                  |       17 |        5 |     71% |     27-32 |
| packages/canvod-ops/src/canvod/ops/temporal.py                                  |      109 |        3 |     97% |     25-27 |
| packages/canvod-readers/src/canvod/readers/\_\_init\_\_.py                      |        8 |        0 |    100% |           |
| packages/canvod-readers/src/canvod/readers/base.py                              |      147 |       32 |     78% |91, 96, 109, 153, 157-159, 163-173, 179-186, 193-195, 248, 328, 398, 467, 482 |
| packages/canvod-readers/src/canvod/readers/builder.py                           |       64 |        0 |    100% |           |
| packages/canvod-readers/src/canvod/readers/gnss\_specs/\_\_init\_\_.py          |        2 |        0 |    100% |           |
| packages/canvod-readers/src/canvod/readers/gnss\_specs/bands.py                 |      125 |       97 |     22% |164-413, 417-423 |
| packages/canvod-readers/src/canvod/readers/gnss\_specs/constants.py             |       13 |        0 |    100% |           |
| packages/canvod-readers/src/canvod/readers/gnss\_specs/constellations.py        |      116 |       13 |     89% |78-96, 422-423, 658-660 |
| packages/canvod-readers/src/canvod/readers/gnss\_specs/exceptions.py            |       19 |        3 |     84% |54, 100, 162 |
| packages/canvod-readers/src/canvod/readers/gnss\_specs/metadata.py              |       21 |        2 |     90% |  251, 254 |
| packages/canvod-readers/src/canvod/readers/gnss\_specs/models.py                |      269 |       54 |     80% |87-88, 90-91, 269-275, 355, 432-440, 466-475, 497-520, 633-638, 732-733, 794-795, 803-806, 814-817, 824, 830-831, 865, 868, 871-879, 907 |
| packages/canvod-readers/src/canvod/readers/gnss\_specs/satellite\_catalog.py    |      371 |       55 |     85% |317, 326-329, 333-338, 354-358, 378-379, 391-404, 409-424, 453, 552, 572, 674, 741-747, 800, 820, 827, 837, 845, 861, 869, 885, 893, 909, 918, 937 |
| packages/canvod-readers/src/canvod/readers/gnss\_specs/signals.py               |       17 |        0 |    100% |           |
| packages/canvod-readers/src/canvod/readers/gnss\_specs/utils.py                 |       21 |        0 |    100% |           |
| packages/canvod-readers/src/canvod/readers/gnss\_specs/validation\_constants.py |       32 |        0 |    100% |           |
| packages/canvod-readers/src/canvod/readers/matching/\_\_init\_\_.py             |        3 |        0 |    100% |           |
| packages/canvod-readers/src/canvod/readers/matching/dir\_matcher.py             |      107 |        5 |     95% |51, 360, 365, 378-379 |
| packages/canvod-readers/src/canvod/readers/matching/models.py                   |        7 |        0 |    100% |           |
| packages/canvod-readers/src/canvod/readers/rinex/\_\_init\_\_.py                |        2 |        0 |    100% |           |
| packages/canvod-readers/src/canvod/readers/rinex/v3\_04.py                      |      701 |      567 |     19% |102, 110-134, 197-202, 210-220, 242-387, 397-427, 444-449, 468-477, 494-501, 520-551, 570-578, 597-610, 629-661, 680-689, 694, 698, 706-707, 770-792, 804, 808, 817, 828-835, 847, 859, 871-876, 888-890, 902, 914-918, 936-949, 971-1046, 1054-1097, 1109, 1125-1145, 1172-1175, 1194, 1221-1232, 1239-1254, 1265-1279, 1297-1320, 1349-1376, 1402-1419, 1439-1504, 1519-1716, 1741-1746, 1784-1828, 1867-1893, 1896-1941, 1956-1957 |
| packages/canvod-readers/src/canvod/readers/sbf/\_\_init\_\_.py                  |        3 |        0 |    100% |           |
| packages/canvod-readers/src/canvod/readers/sbf/\_registry.py                    |       40 |        0 |    100% |           |
| packages/canvod-readers/src/canvod/readers/sbf/\_scaling.py                     |       70 |        0 |    100% |           |
| packages/canvod-readers/src/canvod/readers/sbf/models.py                        |       46 |        0 |    100% |           |
| packages/canvod-readers/src/canvod/readers/sbf/reader.py                        |      695 |      619 |     11% |59-60, 102-104, 114, 147-158, 468-482, 494-523, 575, 593-601, 616-617, 633-635, 651-656, 667, 680, 705-710, 730-752, 778-796, 835-993, 1021-1307, 1342-1774, 1802-1825, 1857-1866, 1889-1928, 1961-1989, 2007 |
| packages/canvod-store-metadata/src/canvod/store\_metadata/\_\_init\_\_.py       |        7 |        0 |    100% |           |
| packages/canvod-store-metadata/src/canvod/store\_metadata/collectors.py         |      133 |       29 |     78% |60-61, 81-83, 92-102, 108, 116, 131-132, 181, 183-185, 188, 192, 262, 302-315 |
| packages/canvod-store-metadata/src/canvod/store\_metadata/inventory.py          |       89 |       43 |     52% |56, 118-121, 136, 139-140, 168, 183-221, 245-253, 277-301 |
| packages/canvod-store-metadata/src/canvod/store\_metadata/io.py                 |       54 |        4 |     93% |37-38, 94-95 |
| packages/canvod-store-metadata/src/canvod/store\_metadata/schema.py             |      143 |        0 |    100% |           |
| packages/canvod-store-metadata/src/canvod/store\_metadata/show.py               |      251 |      221 |     12% |24, 28-29, 33-39, 43-52, 56-66, 70-80, 84-91, 95-103, 107-123, 127-142, 146-158, 162-189, 193-208, 212-229, 233-248, 252-259, 297-329, 334-348, 405-417, 436-441, 446-453 |
| packages/canvod-store-metadata/src/canvod/store\_metadata/validate.py           |       72 |       15 |     79% |12, 31, 55, 66, 76, 78, 80, 82, 84, 88, 103, 126, 137, 157, 171 |
| packages/canvod-store/src/canvod/store/\_\_init\_\_.py                          |        5 |        0 |    100% |           |
| packages/canvod-store/src/canvod/store/manager.py                               |      242 |      201 |     17% |68-91, 100, 105, 112, 125-127, 132, 156-159, 185-195, 207, 219-227, 245-281, 292, 303, 325-352, 377-402, 427-440, 465-482, 510-534, 563-591, 613-648, 659-727, 753-806, 816, 826-828, 847-849 |
| packages/canvod-store/src/canvod/store/reader.py                                |      293 |      261 |     11% |44-62, 85-105, 152-181, 187-190, 194-197, 213, 221-224, 228-231, 245-427, 451-629, 633-636, 641-653, 662-685, 696-703, 713-714 |
| packages/canvod-store/src/canvod/store/store.py                                 |     1047 |      729 |     30% |140-148, 168-169, 186, 205, 317-320, 339, 385, 400-423, 449-474, 548-549, 589-650, 655-670, 698-727, 738, 747, 754-755, 794-828, 853-902, 918-958, 990-1013, 1021-1027, 1056-1062, 1093-1111, 1141-1143, 1177-1196, 1201, 1207, 1213, 1219, 1235-1236, 1247-1271, 1284, 1292, 1317-1319, 1335, 1345, 1366-1383, 1512-1596, 1624, 1626, 1646-1661, 1800, 1845-1897, 1925-1961, 1979-1994, 2000-2002, 2026-2039, 2079-2133, 2170-2313, 2326-2331, 2335, 2339-2340, 2363-2621, 2639-2658, 2662-2666, 2683-2703, 2721-2727, 2756-2782, 2813-2927, 2944-2972, 3018-3056, 3090-3118, 3166-3185, 3190-3211 |
| packages/canvod-store/src/canvod/store/viewer.py                                |      265 |      232 |     12% |40-47, 68, 76, 384-404, 408-422, 427-450, 465-501, 525-547, 560-600, 604-625, 640-700, 708-773, 777-835, 846-929, 966-967, 976-981, 990, 1031-1042, 1059-1061 |
| packages/canvod-utils/src/canvod/utils/\_\_init\_\_.py                          |        2 |        0 |    100% |           |
| packages/canvod-utils/src/canvod/utils/\_meta.py                                |        5 |        0 |    100% |           |
| packages/canvod-utils/src/canvod/utils/config/\_\_init\_\_.py                   |        3 |        0 |    100% |           |
| packages/canvod-utils/src/canvod/utils/config/loader.py                         |       90 |       12 |     87% |44-55, 81-83, 260 |
| packages/canvod-utils/src/canvod/utils/config/models.py                         |      251 |        5 |     98% |405-409, 498, 748 |
| packages/canvod-utils/src/canvod/utils/diagnostics/\_\_init\_\_.py              |        7 |        0 |    100% |           |
| packages/canvod-utils/src/canvod/utils/diagnostics/\_store.py                   |      104 |       79 |     24% |89-104, 111-123, 128-150, 158-167, 172-182, 187, 192, 234-276, 283-284, 289-295 |
| packages/canvod-utils/src/canvod/utils/diagnostics/airflow.py                   |       57 |       38 |     33% |34, 83-125, 130-149 |
| packages/canvod-utils/src/canvod/utils/diagnostics/dataset.py                   |       60 |       43 |     28% |30, 44-78, 132-175 |
| packages/canvod-utils/src/canvod/utils/diagnostics/memory.py                    |       44 |       34 |     23% |39-43, 46-77, 80-84, 87-101 |
| packages/canvod-utils/src/canvod/utils/diagnostics/retry.py                     |        6 |        1 |     83% |        48 |
| packages/canvod-utils/src/canvod/utils/diagnostics/timing.py                    |      126 |       96 |     24% |52-55, 58-70, 73-74, 77-80, 106-120, 124-130, 135, 140, 144-153, 168-173, 212-264, 279-308, 326-339 |
| packages/canvod-utils/src/canvod/utils/tools/\_\_init\_\_.py                    |        6 |        0 |    100% |           |
| packages/canvod-utils/src/canvod/utils/tools/date\_utils.py                     |       96 |       12 |     88% |37, 44, 124, 138, 154, 171, 210, 226, 246, 328, 383-384 |
| packages/canvod-utils/src/canvod/utils/tools/hashing.py                         |        9 |        6 |     33% |     32-37 |
| packages/canvod-utils/src/canvod/utils/tools/validation.py                      |        7 |        5 |     29% |     29-33 |
| packages/canvod-utils/src/canvod/utils/tools/version.py                         |       16 |        2 |     88% |     39-40 |
| packages/canvod-virtualiconvname/src/canvod/virtualiconvname/\_\_init\_\_.py    |        9 |        0 |    100% |           |
| packages/canvod-virtualiconvname/src/canvod/virtualiconvname/catalog.py         |       84 |        4 |     95% |63-64, 75-76 |
| packages/canvod-virtualiconvname/src/canvod/virtualiconvname/config\_models.py  |       23 |        0 |    100% |           |
| packages/canvod-virtualiconvname/src/canvod/virtualiconvname/convention.py      |       73 |        0 |    100% |           |
| packages/canvod-virtualiconvname/src/canvod/virtualiconvname/mapping.py         |      178 |       16 |     91% |80-83, 145-146, 178-179, 212-214, 226, 233, 241, 260, 369 |
| packages/canvod-virtualiconvname/src/canvod/virtualiconvname/patterns.py        |       45 |        0 |    100% |           |
| packages/canvod-virtualiconvname/src/canvod/virtualiconvname/recipe.py          |      111 |        3 |     97% |256, 314-315 |
| packages/canvod-virtualiconvname/src/canvod/virtualiconvname/validator.py       |       61 |        6 |     90% |97, 109-110, 119, 147, 157 |
| packages/canvod-viz/src/canvod/viz/\_\_init\_\_.py                              |        6 |        0 |    100% |           |
| packages/canvod-viz/src/canvod/viz/hemisphere\_2d.py                            |      267 |      184 |     31% |108-109, 117, 186, 193-202, 226, 249-291, 299-335, 339-377, 381-418, 483, 529-530, 581-707 |
| packages/canvod-viz/src/canvod/viz/hemisphere\_3d.py                            |      275 |      210 |     24% |127-141, 195, 226-227, 253-288, 316-355, 383-432, 464-510, 534-556, 662-754, 785-828, 857-922, 980-991 |
| packages/canvod-viz/src/canvod/viz/styles.py                                    |      122 |        1 |     99% |       498 |
| packages/canvod-viz/src/canvod/viz/visualizer.py                                |       52 |        3 |     94% |246, 351-352 |
| packages/canvod-vod/src/canvod/vod/\_\_init\_\_.py                              |        3 |        0 |    100% |           |
| packages/canvod-vod/src/canvod/vod/\_internal/\_\_init\_\_.py                   |        2 |        0 |    100% |           |
| packages/canvod-vod/src/canvod/vod/\_internal/logger.py                         |        5 |        1 |     80% |        26 |
| packages/canvod-vod/src/canvod/vod/calculator.py                                |       67 |        7 |     90% |51, 65, 106-112 |
| **TOTAL**                                                                       | **17891** | **10675** | **40%** |           |


## Setup coverage badge

Below are examples of the badges you can use in your main branch `README` file.

### Direct image

[![Coverage badge](https://raw.githubusercontent.com/nfb2021/canvodpy/python-coverage-comment-action-data/badge.svg)](https://htmlpreview.github.io/?https://github.com/nfb2021/canvodpy/blob/python-coverage-comment-action-data/htmlcov/index.html)

This is the one to use if your repository is private or if you don't want to customize anything.

### [Shields.io](https://shields.io) Json Endpoint

[![Coverage badge](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/nfb2021/canvodpy/python-coverage-comment-action-data/endpoint.json)](https://htmlpreview.github.io/?https://github.com/nfb2021/canvodpy/blob/python-coverage-comment-action-data/htmlcov/index.html)

Using this one will allow you to [customize](https://shields.io/endpoint) the look of your badge.
It won't work with private repositories. It won't be refreshed more than once per five minutes.

### [Shields.io](https://shields.io) Dynamic Badge

[![Coverage badge](https://img.shields.io/badge/dynamic/json?color=brightgreen&label=coverage&query=%24.message&url=https%3A%2F%2Fraw.githubusercontent.com%2Fnfb2021%2Fcanvodpy%2Fpython-coverage-comment-action-data%2Fendpoint.json)](https://htmlpreview.github.io/?https://github.com/nfb2021/canvodpy/blob/python-coverage-comment-action-data/htmlcov/index.html)

This one will always be the same color. It won't work for private repos. I'm not even sure why we included it.

## What is that?

This branch is part of the
[python-coverage-comment-action](https://github.com/marketplace/actions/python-coverage-comment)
GitHub Action. All the files in this branch are automatically generated and may be
overwritten at any moment.