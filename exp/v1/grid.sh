#!/bin/bash
run() { .venv/bin/python exp/pipeline.py "$@" 2>&1 | grep -e done -e Error; }
run p1 & run p2 w_e5=0 & run p3 w_e5=0.3 & wait
run p4 sel=facet & run p5 cap=2 & run p6 theme=0.68 & wait
run p7 rel=0.55 nrel=6 & run p8 kw=0.04 & run p9 w_e5=0.3 rel=0.55 nrel=6 & wait
.venv/bin/python exp/issuecov.py p1 p2 p3 p4 p5 p6 p7 p8 p9 c1_f5_cards oracle | sed 's/np.float64(\([0-9.]*\))/\1/g'
