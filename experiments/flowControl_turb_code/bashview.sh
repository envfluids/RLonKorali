pip install scikit-learn
pip install seaborn
for d in _result*/ ; do
    echo "$d"
    python3 -m korali.rlview --dir $d --output $d/history.png
done
#python3 -m korali.rlview --dir _result_vracerC1_N64_R_k1_State_enstrophy_Action_CL --output result.png

