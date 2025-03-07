from nmr_std_function.nmr_class import nmr_system_2022
from nmr_std_function.nmr_functions import compute_multiexp_anc
from nmr_std_function.nmr_functions import compute_multiexp

sav_fig = True
show_fig = True
expt_num = 0 # experiment number is always 0 for a single experiment

# import default measurement configuration
from sys_configs.phenc_conf_halbach_v06_230503_test import phenc_conf_halbach_v06_230503_test
phenc_conf = phenc_conf_halbach_v06_230503_test()

# set local folder
client_data_folder = "D:/NMR_DATA/cpmg_241009_183549"
nmrObj = nmr_system_2022( client_data_folder )

compute_multiexp( nmrObj, phenc_conf, expt_num, sav_fig, show_fig )
#compute_multiexp_anc( nmrObj, phenc_conf, expt_num, sav_fig, show_fig )