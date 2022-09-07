import csv
import math
import os

import matplotlib
from scipy.optimize import curve_fit

import matplotlib.pyplot as plt
from nmr_std_function import data_parser
from nmr_std_function.data_parser import convert_to_prospa_data_t1
from nmr_std_function.signal_proc import down_conv, nmr_fft, butter_lowpass_filter
import numpy as np


def plot_echosum( nmrObj, filepath, samples_per_echo, echoes_per_scan, en_fig ):

    dat1 = np.array( data_parser.read_data( filepath ) )  # use ascii representation
    dat2 = np.reshape(dat1, ( echoes_per_scan, samples_per_echo))
    dat3 = np.mean(dat2,0)
    
    # plot the individual echoes
    plt.figure(0)
    for i in range(echoes_per_scan):
        plt.plot(dat2[i,:], color='y')
    
    # plot the echo sum
    # plt.figure(1)    
    plt.plot(dat3, color='blue')
    
    plt.show()
    
def compute_multiple( nmrObj, data_parent_folder, meas_folder, file_name_prefix, en_fig, en_ext_param, thetaref, echoref_avg, direct_read, datain, dconv_lpf_ord, dconv_lpf_cutoff_kHz ):

    # variables to be input
    # nmrObj            : the hardware definition
    # data_parent_folder : the folder for all datas
    # meas_folder        : the specific folder for one measurement
    # filename_prefix   : the name of data prefix
    # Df                : data frequency
    # Sf                : sample frequency
    # tE                : echo spacing
    # total_scan        : number_of_iteration
    # en_fig            : enable figure
    # en_ext_param      : enable external parameter for data signal processing
    # thetaref          : external parameter : rotation angle
    # echoref_avg        : external parameter : echo average reference
    # datain            : the data captured direct reading. data format: AC,averaged scans, phase-cycled
    # direct_read        : perform direct reading from SDRAM/FIFO

    data_folder = ( data_parent_folder + '/' + meas_folder + '/' )

    # variables local to this function the setting file for the measurement
    mtch_fltr_sta_idx = 0  # 0 is default or something referenced to SpE, e.g. SpE/4; the start index for match filtering is to neglect ringdown part from calculation 
    perform_rotation = 1 # perform rotation to the data -> required for reference data for t1 measurement
    proc_indv_data = 0 # process individual raw data, otherwise it'll load a sum file generated by C
    binary_OR_ascii = 0 # put 1 if the data file uses binary representation, otherwise it is in ascii format
    ignore_echoes = 16  # ignore initial echoes #

    # simulate decimation in software (DO NOT use this for normal operation, only for debugging purpose)
    sim_dec = 0
    sim_dec_fact = 32

    compute_figure = True  # compute the figure and save the figure to file. To show it in runtime, enable the en_fig  
    
    # variables from NMR settings
    ( param_list, value_list ) = data_parser.parse_info( 
        data_folder, 'acqu.par' )  # read file
    SpE = int( data_parser.find_value( 'nrPnts', param_list, value_list ) )
    NoE = int( data_parser.find_value( 'nrEchoes', param_list, value_list ) )
    en_ph_cycle_proc = int (data_parser.find_value( 'usePhaseCycle', param_list, value_list ))
    tE = data_parser.find_value( 'echoTimeRun', param_list, value_list )
    Sf = data_parser.find_value( 'adcFreq', param_list, value_list ) * 1e6
    Df = data_parser.find_value( 'b1Freq', param_list, value_list ) * 1e6
    total_scan = int( data_parser.find_value( 'nrIterations', param_list, value_list ) )
    fpga_dconv = data_parser.find_value( 'fpgaDconv', param_list, value_list )
    dconv_fact = data_parser.find_value( 'dconvFact', param_list, value_list )
    echo_skip = data_parser.find_value( 'echoSkipHw', param_list, value_list )

    # account for skipped echoes
    NoE = int( NoE / echo_skip )
    tE = tE * echo_skip

    # compensate for dconv_fact if fpga dconv is used
    if fpga_dconv:
        SpE = int( SpE / dconv_fact )
        Sf = Sf / dconv_fact

    # ignore echoes
    if ignore_echoes:
        NoE = NoE - ignore_echoes

    # time domain for plot
    tacq = ( 1 / Sf ) * 1e6 * np.linspace( 1, SpE, SpE )  # in uS
    t_echospace = tE / 1e6 * np.linspace( 1, NoE, NoE )  # in uS

    if fpga_dconv:  # use fpga dconv
        # load IQ data
        file_path = ( data_folder + 'dconv' )

        if binary_OR_ascii:
            dconv = data_parser.read_hex_float( 
                file_path )  # use binary representation
        else:
            dconv = np.array( data_parser.read_data( file_path )
                             )  # use ascii representation

        if ignore_echoes:
            dconv = dconv[ignore_echoes * 2 * SpE:len( dconv )]

        # normalize the data
        # normalize with decimation factor (due to sum in the fpga)
        dconv = dconv / dconv_fact
        dconv = dconv / nmrObj.fir_gain  # normalize with the FIR gain in the fpga
        # convert to voltage unit at the probe
        dconv = dconv / nmrObj.totGain * nmrObj.uvoltPerDigit
        # scale all the data to magnitude of sin(45). The FPGA uses unity
        # magnitude (instead of sin45,135,225,315) to simplify downconversion
        # operation
        dconv = dconv * nmrObj.dconv_gain

        # combined IQ
        data_filt = np.zeros( ( NoE, SpE ), dtype = complex )
        for i in range( 0, NoE ):
            data_filt[i, :] = \
                dconv[i * ( 2 * SpE ):( i + 1 ) * ( 2 * SpE ):2] + 1j * \
                dconv[i * ( 2 * SpE ) + 1:( i + 1 ) * ( 2 * SpE ):2]

        if compute_figure:  # plot the averaged scan
            echo_space = ( 1 / Sf ) * np.linspace( 1, SpE, SpE )  # in s
            plt.figure( 1 )
            plt.clf()
            for i in range( 0, NoE ):
                plt.plot( ( ( i - 1 ) * tE * 1e-6 + echo_space ) * 1e3,
                         np.real( data_filt[i, :] ), linewidth = 0.4, color = 'b' )
                plt.plot( ( ( i - 1 ) * tE * 1e-6 + echo_space ) * 1e3,
                         np.imag( data_filt[i, :] ), linewidth = 0.4, color = 'r' )
            plt.title( "Averaged raw data (downconverted)" )
            plt.xlabel( 'time(ms)' )
            plt.ylabel( 'probe voltage (uV)' )
            plt.savefig( data_folder + '.png' )

        # raw average data
        echo_rawavg = np.mean( data_filt, axis = 0 )

        if compute_figure:  # plot echo rawavg
            plt.figure( 6 )
            plt.clf()
            plt.plot( tacq, np.real( echo_rawavg ), label = 'real' )
            plt.plot( tacq, np.imag( echo_rawavg ), label = 'imag' )
            plt.plot( tacq, np.abs( echo_rawavg ), label = 'abs' )
            plt.xlim( 0, max( tacq ) )
            plt.title( "Echo Average before rotation (down-converted)" )
            plt.xlabel( 'time(uS)' )
            plt.ylabel( 'probe voltage (uV)' )
            plt.legend()
            plt.savefig( data_folder + 'fig_echo_avg_dconv.png' )

        # simulate additional decimation (not needed for normal operqtion). For
        # debugging purpose
        if ( sim_dec ):
            SpE = int( SpE / sim_dec_fact )
            Sf = Sf / sim_dec_fact
            data_filt_dec = np.zeros( ( NoE, SpE ), dtype = complex )
            for i in range( 0, SpE ):
                data_filt_dec[:, i] = np.mean( 
                    data_filt[:, i * sim_dec_fact:( i + 1 ) * sim_dec_fact], axis = 1 )
            data_filt = np.zeros( ( NoE, SpE ), dtype = complex )
            data_filt = data_filt_dec
            tacq = ( 1 / Sf ) * 1e6 * np.linspace( 1, SpE, SpE )  # in uS

    else: # do down conversion locally
        if ( direct_read ):
            data = datain
        else:
            if ( proc_indv_data ):
                # read all datas and average it
                data = np.zeros( NoE * SpE )
                for m in range( 1, total_scan + 1 ):
                    file_path = ( data_folder + file_name_prefix +
                                 '{0:03d}'.format( m ) )
                    # read the data from the file and store it in numpy array
                    # format
                    one_scan = np.array( data_parser.read_data( file_path ) )
                    one_scan = ( one_scan - np.mean( one_scan ) ) / \
                        total_scan  # remove DC component
                    if ( en_ph_cycle_proc ):
                        if ( m % 2 ):  # phase cycling every other scan
                            data = data - one_scan
                        else:
                            data = data + one_scan
                    else:
                        data = data + one_scan
            else:
                # read sum data only
                file_path = ( data_folder + 'datasum.txt' )
                data = np.zeros( NoE * SpE )

                if binary_OR_ascii:
                    data = data_parser.read_hex_float( 
                        file_path )  # use binary representation
                else:
                    # use ascii representation
                    data = np.array( data_parser.read_data( file_path ) )

                dataraw = data
                data = ( data - np.mean( data ) )

        # ignore echoes
        if ignore_echoes:
            data = data[ignore_echoes * SpE:len( data )]

        # compute the probe voltage before gain stage
        data = data / nmrObj.totGain * nmrObj.uvoltPerDigit

        if compute_figure:  # plot the averaged scan
            echo_space = ( 1 / Sf ) * np.linspace( 1, SpE, SpE )  # in s
            plt.figure( 1 )
            plt.clf()
            for i in range( 1, NoE + 1 ):
                # plt.plot(((i - 1) * tE * 1e-6 + echo_space) * 1e3, data[(i - 1) * SpE:i * SpE], linewidth=0.4)
                plt.plot( ( ( i - 1 ) * tE * 1e-6 + echo_space ) * 1e3,
                         dataraw[( i - 1 ) * SpE:i * SpE], linewidth = 0.4 )
            plt.title( "Averaged raw data" )
            plt.xlabel( 'time(ms)' )
            plt.ylabel( 'probe voltage (uV)' )
            plt.savefig( data_folder + 'decay_raw.png' )

        # raw average data
        echo_rawavg = np.zeros( SpE, dtype = float )
        for i in range( 0, NoE ):
            echo_rawavg += ( data[i * SpE:( i + 1 ) * SpE] / NoE )

        if compute_figure:  # plot echo rawavg
            plt.figure( 6 )
            plt.clf()
            plt.plot( tacq, echo_rawavg, label = 'echo rawavg' )
            plt.xlim( 0, max( tacq ) )
            plt.title( "Echo Average (raw)" )
            plt.xlabel( 'time(uS)' )
            plt.ylabel( 'probe voltage (uV)' )
            plt.legend()
            plt.savefig( data_folder + 'echo_avg.png' )

        # filter the data
        data_filt = np.zeros( ( NoE, SpE ), dtype = complex )
        for i in range( 0, NoE ):
            data_filt[i, :] = down_conv( 
                data[i * SpE:( i + 1 ) * SpE], i, tE, Df, Sf, dconv_lpf_ord, dconv_lpf_cutoff_kHz * 1e3 )

        # simulate additional decimation (not needed for normal operation). For
        # debugging purpose
        if ( sim_dec ):
            SpE = int( SpE / sim_dec_fact )
            Sf = Sf / sim_dec_fact
            data_filt_dec = np.zeros( ( NoE, SpE ), dtype = complex )
            for i in range( 0, SpE ):
                data_filt_dec[:, i] = np.sum( 
                    data_filt[:, i * sim_dec_fact:( i + 1 ) * sim_dec_fact], axis = 1 )
            data_filt = np.zeros( ( NoE, SpE ), dtype = complex )
            data_filt = data_filt_dec
            tacq = ( 1 / Sf ) * 1e6 * np.linspace( 1, SpE, SpE )  # in uS

    # scan rotation
    if en_ext_param:
        data_filt = data_filt * np.exp( -1j * thetaref )
        theta = math.atan2( np.sum( np.imag( data_filt ) ),
                           np.sum( np.real( data_filt ) ) )
    else:
        theta = math.atan2( np.sum( np.imag( data_filt ) ),
                           np.sum( np.real( data_filt ) ) )
        if perform_rotation:
            data_filt = data_filt * np.exp( -1j * theta )

    if compute_figure:  # plot filtered data
        echo_space = ( 1 / Sf ) * np.linspace( 1, SpE, SpE )  # in s
        plt.figure( 2 )
        plt.clf()

        data_parser.write_text_overwrite( data_folder, "decay_filt.txt", "settings: NoE: %d, SpE: %d, tE: %0.2f, fs: %0.2f. Format: re(echo1), im(echo1), re(echo2), im(echo2), ... " % ( NoE, SpE, tE, Sf ) )

        for i in range( 0, NoE ):
            plt.plot( ( i * tE * 1e-6 + echo_space ) * 1e3,
                     np.real( data_filt[i, :] ), 'b', linewidth = 0.4 )
            plt.plot( ( i * tE * 1e-6 + echo_space ) * 1e3,
                     np.imag( data_filt[i, :] ), 'r', linewidth = 0.4 )

        for i in range ( 0, NoE ):
            data_parser.write_text_append_row( data_folder, "decay_filt.txt", np.real( data_filt[i, :] ) )
            data_parser.write_text_append_row( data_folder, "decay_filt.txt", np.imag( data_filt[i, :] ) )

        plt.legend()
        plt.title( 'Filtered data' )
        plt.xlabel( 'Time (mS)' )
        plt.ylabel( 'probe voltage (uV)' )
        plt.savefig( data_folder + 'decay_filt.png' )

    # find echo average, echo magnitude
    echo_avg = np.zeros( SpE, dtype = complex )
    for i in range( 0, NoE ):
        echo_avg += ( data_filt[i, :] / NoE )

    if compute_figure:  # plot echo shape
        plt.figure( 3 )
        plt.clf()
        plt.plot( tacq, np.abs( echo_avg ), label = 'abs' )
        plt.plot( tacq, np.real( echo_avg ), label = 'real part' )
        plt.plot( tacq, np.imag( echo_avg ), label = 'imag part' )
        plt.xlim( 0, max( tacq ) )
        plt.title( "Echo Shape" )
        plt.xlabel( 'time(uS)' )
        plt.ylabel( 'probe voltage (uV)' )
        plt.legend()
        plt.savefig( data_folder + 'echo_shape.png' )
        
        data_parser.write_text_overwrite( data_folder, "echo_shape.txt", "format: abs, real, imag, time_us" )
        data_parser.write_text_append_row( data_folder, "echo_shape.txt", np.abs( echo_avg ) )
        data_parser.write_text_append_row( data_folder, "echo_shape.txt", np.real( echo_avg ) )
        data_parser.write_text_append_row( data_folder, "echo_shape.txt", np.imag( echo_avg ) )
        data_parser.write_text_append_row( data_folder, "echo_shape.txt", tacq )

        # plot fft of the echosum
        plt.figure( 4 )
        plt.clf()
        zf = 100  # zero filling factor to get smooth curve
        ws = 2 * np.pi / ( tacq[1] - tacq[0] )  # in MHz
        wvect = np.linspace( -ws / 2, ws / 2, len( tacq ) * zf )
        echo_zf = np.zeros( zf * len( echo_avg ), dtype = complex )
        echo_zf[int( ( zf / 2 ) * len( echo_avg ) - len( echo_avg ) / 2 ): int( ( zf / 2 ) * len( echo_avg ) + len( echo_avg ) / 2 )] = echo_avg
        spect = zf * ( np.fft.fftshift( np.fft.fft( np.fft.ifftshift( echo_zf ) ) ) )
        spect = spect / len( spect )  # normalize the spectrum
        plt.plot( wvect / ( 2 * np.pi ), np.real( spect ),
                 label = 'real' )
        plt.plot( wvect / ( 2 * np.pi ), np.imag( spect ),
                 label = 'imag' )
        plt.xlim( 10 / max( tacq ) * -1, 10 / max( tacq ) * 1 )
        plt.title( "FFT of the echo-sum. " + "Peak:real@{:0.2f}kHz,abs@{:0.2f}kHz".format( wvect[np.abs( np.real( spect ) ) == max( 
            np.abs( np.real( spect ) ) )][0] / ( 2 * np.pi ) * 1e3, wvect[np.abs( spect ) == max( np.abs( spect ) )][0] / ( 2 * np.pi ) * 1e3 ) )
        plt.xlabel( 'offset frequency(MHz)' )
        plt.ylabel( 'Echo amplitude (a.u.)' )
        plt.legend()
        plt.savefig( data_folder + 'echo_spect.png' )
        
        data_parser.write_text_overwrite( data_folder, "echo_spect.txt", "format: real, imag, freq_MHz" )
        data_parser.write_text_append_row( data_folder, "echo_spect.txt", np.real( spect ) )
        data_parser.write_text_append_row( data_folder, "echo_spect.txt", np.imag( spect ) )
        data_parser.write_text_append_row( data_folder, "echo_spect.txt", wvect / ( 2 * np.pi ) )

    # matched filtering
    a = np.zeros( NoE, dtype = complex )
    for i in range( 0, NoE ):
        if en_ext_param:
            a[i] = np.mean( np.multiply( data_filt[i, mtch_fltr_sta_idx:SpE], np.conj( 
                echoref_avg[mtch_fltr_sta_idx:SpE] ) ) )  # find amplitude with reference matched filtering
        else:
            a[i] = np.mean( np.multiply( data_filt[i, mtch_fltr_sta_idx:SpE], np.conj( 
                echo_avg[mtch_fltr_sta_idx:SpE] ) ) )  # find amplitude with matched filtering

    a_integ = np.sum( np.real( a ) )

    # def exp_func(x, a, b, c, d):
    #    return a * np.exp(-b * x) + c * np.exp(-d * x)
    def exp_func( x, a, b ):
        return a * np.exp( -b * x )

    # average the first 5% of datas
    a_guess = np.mean( np.real( a[0:int( np.round( SpE / 20 ) )] ) )
    # c_guess = a_guess
    # find min idx value where the value of (a_guess/exp) is larger than
    # real(a)
    # b_guess = np.where(np.real(a) == np.min(
    #    np.real(a[np.real(a) > a_guess / np.exp(1)])))[0][0] * tE / 1e6
    # this is dummy b_guess, use the one I made above this for smarter one
    # (but sometimes it doesn't work)
    b_guess = 0.01
    # d_guess = b_guess
    # guess = np.array([a_guess, b_guess, c_guess, d_guess])
    guess = np.array( [a_guess, b_guess] )

    try:  # try fitting data
        popt, pocv = curve_fit( exp_func, t_echospace, np.real( a ), guess )

        # obtain fitting parameter
        a0 = popt[0]
        T2 = 1 / popt[1]

        # Estimate SNR/echo/scan
        f = exp_func( t_echospace, *popt )  # curve fit
        noise = np.std( np.imag( a ) )
        res = np.std( np.real( a ) - f )
        snr_imag = a0 / ( noise * math.sqrt( total_scan ) )
        snr_res = a0 / ( res * math.sqrt( total_scan ) )
        snr = snr_imag

        # plot fitted line
        plt.figure( 5 )
        plt.clf()
        plt.cla()
        plt.plot( t_echospace * 1e3, f, label = "fit" )  # plot in milisecond
        plt.plot( t_echospace * 1e3, np.real( a ) - f, label = "residue" )

    except:
        print( 'Problem in fitting. Set a0 and T2 output to 0\n' )
        a0 = 0
        T2 = 0
        noise = 0
        res = 0
        snr = 0
        snr_res = 0
        snr_imag = 0

    if compute_figure:
        # plot data
        plt.figure( 5 )
        # plot in milisecond
        plt.plot( t_echospace * 1e3, np.real( a ), label = "real" )
        # plot in milisecond
        plt.plot( t_echospace * 1e3, np.imag( a ), label = "imag" )

        # plt.set(gca, 'FontSize', 12)
        plt.legend()
        plt.title( 'Matched filtered data. SNRim:{:03.2f} SNRres:{:03.2f}.\na:{:0.3f} n_im:{:0.4f} n_res:{:0.4f} T2:{:0.2f}msec'.format( 
            snr, snr_res, a0, ( noise * math.sqrt( total_scan ) ), ( res * math.sqrt( total_scan ) ), T2 * 1e3 ) )
        plt.xlabel( 'Time (mS)' )
        plt.ylabel( 'probe voltage (uV)' )
        plt.savefig( data_folder + 'decay_sum.png' )

        data_parser.write_text_overwrite( data_folder, "decay_sum.txt", "output params: noise std: %0.5f, res std: %0.5f, snr_imag: %0.3f, snr_res: %0.3f, a0: %0.3f, T2: %0.3f ms. Format: a_real, a_imag, fit, time(s) " % ( noise, res, snr_imag, snr_res, a0, T2 * 1e3 ) )
        data_parser.write_text_append_row( data_folder, "decay_sum.txt", np.real( a ) )
        data_parser.write_text_append_row( data_folder, "decay_sum.txt", np.imag( a ) )
        data_parser.write_text_append_row( data_folder, "decay_sum.txt", f )
        data_parser.write_text_append_row( data_folder, "decay_sum.txt", t_echospace )

    if en_fig and compute_figure:
        plt.show()

    print( 'a0 = ' + '{0:.2f}'.format( a0 ) )
    print( 'SNR/echo/scan = ' +
          'imag:{0:.2f}, res:{1:.2f}'.format( snr, snr_res ) )
    print( 'T2 = ' + '{0:.4f}'.format( T2 * 1e3 ) + ' msec' )

    return ( a, a_integ, a0, snr, T2, noise, res, theta, data_filt, echo_avg, t_echospace )
    
def compute_in_bw_noise( en_filt, bw_kHz, Df_MHz, minfreq, maxfreq, data_parent_folder, plotname, en_fig ):

    # variables to be input
    # en_filt            : enable the software post-processing filter to limit the measurement bandwidth
    # data_parent_folder : the folder for all datas
    # en_fig            : enable figure

    # compute settings

    data_folder = ( data_parent_folder + '/' )
    fig_num = 200

    # variables from NMR settings
    ( param_list, value_list ) = data_parser.parse_info( 
        data_folder, 'acqu.par' )  # read file
    adcFreq = data_parser.find_value( 
        'adcFreq', param_list, value_list )
    nrPnts = int( data_parser.find_value( 
        'samples', param_list, value_list ) )

    # parse file and remove DC component
    nmean = 0
    file_path = ( data_folder + 'noise.txt' )
    one_scan_raw = np.array( data_parser.read_data( file_path ) )
    nmean = np.mean( one_scan_raw )
    one_scan = ( one_scan_raw - nmean )

    # compute in-bandwidth noise
    Sf = adcFreq * 1e6
    # filter parameter
    filt_ord = 2
    filt_lpf_cutoff = bw_kHz * 1e3  # in Hz

    T = 1 / Sf
    t = np.linspace( 0, T * ( len( one_scan ) - 1 ), len( one_scan ) )

    

    # filter one_scan when filter is enabled. Otherwise, leave one_scan
    if (en_filt):
        # down-conversion
        sReal = one_scan * np.cos( 2 * math.pi * Df_MHz * 1e6 * t )
        sImag = one_scan * np.sin( 2 * math.pi * Df_MHz * 1e6 * t )
        r = butter_lowpass_filter( sReal + 1j * sImag, filt_lpf_cutoff, Sf, filt_ord, False ) # filtered value
        # upconversion
        one_scan = np.real( r ) * np.cos( 2 * math.pi * Df_MHz * 1e6 * t ) + np.imag( r ) * np.sin( 2 * math.pi * Df_MHz * 1e6 * t )  # r * e^(j*w0*t)
        # one_scan = np.real( one_scan ) # not needed, the result above contains only real values

    # filter profile
    filt_prfl = np.random.randn( len( one_scan ) )  # generate ones
    filt_prfl_ori = filt_prfl  # noise data with no filter process
    sfiltReal = filt_prfl * np.cos( 2 * math.pi * Df_MHz * 1e6 * t )  # real downconversion
    sfiltImag = filt_prfl * np.sin( 2 * math.pi * Df_MHz * 1e6 * t )  # imag downconversion
    filt_out = butter_lowpass_filter( sfiltReal + 1j * sfiltImag, filt_lpf_cutoff, Sf, filt_ord, False )  # filter
    filt_prfl = np.real( filt_out ) * np.cos( 2 * math.pi * Df_MHz * 1e6 * t ) + np.imag( filt_out ) * np.sin( 2 * math.pi * Df_MHz * 1e6 * t )  # upconversion
    # filt_prfl = np.real( filt_prfl ) # no need. the value is already real

    # compute fft
    spectx, specty = nmr_fft( one_scan, adcFreq, 0 )
    specty = abs( specty )
    fft_range = [i for i, value in enumerate( spectx ) if ( 
        value >= minfreq and value <= maxfreq )]  # limit fft display

    # compute fft for the filter profile
    filtspectx, filtspecty = nmr_fft( filt_prfl, adcFreq, 0 )
    filtspecty = abs( filtspecty )
    filtorispecx, filtorispecty = nmr_fft( filt_prfl_ori, adcFreq, 0 )  # noise data with no filter process
    filtorispecty = abs( filtorispecty )

    # compute std
    nstd = np.std( one_scan )

    if en_fig:
        plt.ion()
        fig = plt.figure( fig_num )

        # maximize window
        plot_backend = matplotlib.get_backend()
        mng = plt.get_current_fig_manager()
        if plot_backend == 'TkAgg':
            # mng.resize(*mng.window.maxsize())
            mng.resize( 1400, 800 )
        elif plot_backend == 'wxAgg':
            mng.frame.Maximize( True )
        elif plot_backend == 'Qt4Agg':
            mng.window.showMaximized()

        fig.clf()
        ax = fig.add_subplot( 311 )

        filtnorm = sum( specty[fft_range] ) / sum( filtspecty[fft_range] )

        line1, = ax.plot( spectx[fft_range], specty[fft_range], 'b-', label = 'data', linewidth = 0.5 )
        # line2, = ax.plot( filtspectx[fft_range], filtspecty[fft_range] * filtnorm, 'r.', markersize = 0.8, label = 'synth. noise' )  # amplitude is normalized with the max value of specty
        # line3, = ax.plot(filtorispecx[fft_range], filtorispecty[fft_range]*(filtnorm/2), 'y.', markersize=2.0, label='synth. noise unfiltered') # amplitude is normalized with the max value of specty

        # ax.set_ylim(0, 60)
        ax.set_xlabel( 'Frequency (MHz)' )
        ax.set_ylabel( 'Amplitude (a.u.)' )
        ax.set_title( "Spectrum" )
        ax.grid()
        ax.legend()
        # plt.ylim( [-0.2, 5] )

        # plot time domain data
        ax = fig.add_subplot( 312 )
        x_time = np.linspace( 1, len( one_scan_raw ), len( one_scan_raw ) )
        x_time = np.multiply( x_time, ( 1 / adcFreq ) )  # in us
        x_time = np.multiply( x_time, 1e-3 )  # in ms
        line1, = ax.plot( x_time, one_scan, 'b-' , linewidth = 0.5 )
        ax.set_xlabel( 'Time(ms)' )
        ax.set_ylabel( 'Amplitude (a.u.)' )
        ax.set_title( "Amplitude. std=%0.2f. mean=%0.2f." % ( nstd, nmean ) )
        ax.grid()
        '''
        if (en_filt):
            plt.ylim( [-2000, 2000] )
        else:
            plt.ylim( [-2000, 2000] )
        '''

        # plot histogram
        n_bins = 200
        ax = fig.add_subplot( 313 )
        n, bins, patches = ax.hist( one_scan, bins = n_bins )
        ax.set_title( "Histogram" )
        # plt.ylim( [0, 2000] )

        plt.tight_layout()
        fig.canvas.draw()
        fig.canvas.flush_events()

        # fig = plt.gcf() # obtain handle
        plt.savefig( data_folder + plotname )

    # standard deviation of signal
    print( '\t\t: rms= ' + '{0:.4f}'.format( nstd ) +
          ' mean= {0:.4f}'.format( nmean ) )
    return nstd, nmean

def calcP90( Vpp, rs, L, f, numTurns, coilLength, coilFactor ):

    # estimates the 90 degree pulse length based on voltage output at the coil
    # Vpp: measured voltage at the coil
    # rs: series resitance of coil
    # L: inductance of coil
    # f: Larmor frequency in Hz
    # numTurns: Number of turns in coil
    # coilLength: Length of coil in m
    # coilFactor: obtained by measurement compensation with KeA, will be coil geometry
    # dependant

    import math
    import numpy as np

    gamma = 42.58e6  # MHz/Tesla
    u = 4 * np.pi * 10 ** -7
    Q = 2 * np.pi * f * L / rs
    Vrms = Vpp / ( 2 * math.sqrt( 2 ) )
    Irms = Vrms / ( math.sqrt( Q ** 2 + 1 ** 2 ) * rs )

    # extra factor due to finite coil length (geometry)
    B1 = u * ( numTurns / ( 2 * coilLength ) ) * Irms / coilFactor
    P90 = ( 1 / ( gamma * B1 ) ) * ( 90 / 360 )
    Pwatt = ( Irms ** 2 ) * rs

    return P90, Pwatt

