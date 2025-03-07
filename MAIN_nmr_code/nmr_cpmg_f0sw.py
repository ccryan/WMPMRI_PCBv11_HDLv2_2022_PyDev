'''
Created on May 24, 2022

@author: David Ariando

'''

#!/usr/bin/python

import os
import time
from datetime import datetime
import pydevd
from scipy import signal
import matplotlib.pyplot as plt
import numpy as np

from nmr_std_function.data_parser import parse_csv_float2col
from nmr_std_function.data_parser import parse_simple_info
from nmr_std_function.nmr_class import nmr_system_2022
from nmr_std_function.ntwrk_functions import cp_rmt_file, cp_rmt_folder, exec_rmt_ssh_cmd_in_datadir
from nmr_std_function.nmr_functions import plot_echosum
from nmr_std_function.time_func import time_meas
from nmr_std_function.expts_functions import cpmg


# get the current time
now = datetime.now()
datatime = now.strftime("%y%m%d_%H%M%S")

# create folder for measurements
data_parent_folder = 'D:\\NMR_DATA'
meas_folder = '\\cpmg_'+datatime

# variables
expt_num = 0 # set to 0 for a single experiment
sav_fig = 1 # save figures
show_fig = 1  # show figures

# enable time measurement
tmeas = time_meas(True)

# instantiate nmr object
client_data_folder = data_parent_folder+'\\'+meas_folder
nmrObj = nmr_system_2022( client_data_folder )

# report time
tmeas.reportTimeSinceLast("### load libraries")

# import default measurement configuration
from sys_configs.phenc_conf_halbach_v06_230503_test import phenc_conf_halbach_v06_230503_test
phenc_conf = phenc_conf_halbach_v06_230503_test()

# modify the config
phenc_conf.en_fit = True
#phenc_conf.a_est = [20] # array of amplitude estimate for fitting
#phenc_conf.t2_est = [40e-3] # array of t2 estimate for fitting
#----------------
val_sw = np.linspace(2.38, 2.40, 21)
echo_avg_rms_list = np.zeros(len(val_sw));

for i,val_curr in enumerate(val_sw):
    
    if (i==len(val_sw)-1):
        phenc_conf.en_lcs_dchg = 1 # enable discharging at the last iteration to dump vpc voltage
    
    print("\t\t\t\texpt: %d/%d ----- Freq Sweep = %0.10f MHz" % (i,len(val_sw)-1,val_curr) )
    phenc_conf.cpmg_freq = val_curr
    expt_num = i
       
    # run the experiment
    asum_re, asum_im, a0, snr, T2, noise, res, theta, echo_avg, fpeak, spect, wvect = cpmg(nmrObj, phenc_conf, expt_num, sav_fig, show_fig)
    echo_avg_rms_list[i] =  snr
    time.sleep(1)


plt.figure( 10 )
plt.clf()
plt.plot( val_sw, echo_avg_rms_list )
plt.legend()
plt.title( 'Freq Sweep' )
plt.xlabel( 'freq (MHz)' )
plt.savefig( nmrObj.client_data_folder + '\\freq_sweep.png' )

tmeas.reportTimeSinceLast("### processing")

# clean up
nmrObj.exit()