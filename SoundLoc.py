import numpy as np
#import matplotlib.pyplot as plt
#from mpl_toolkits import mplot3d
import sys
import soundloc as sl
from scipy.io import wavfile

c = 343.8

def blockProcess(s, blocksize, hopsize):

    nchannels, slen = s.shape
    num_over = (slen - blocksize) % hopsize #how many extra samples are on the end of the signal for this block and hop size
    slen = slen-num_over
    nblocks = int((slen - blocksize) / hopsize + 1)

    ar = np.zeros((nchannels, blocksize, nblocks))

    for n in range(nblocks):
        ar[:, :, n] = s[:, n*hopsize:n*hopsize + blocksize]

    return ar

def hanningWindow(ar):
    
    _, width, _ = ar.shape
    ar = ar * np.hanning(width)[np.newaxis, :, np.newaxis]

    return ar

def createSpectralMask(csd, gain=0.05):
    '''
    csd - N array - cross spectral density 
    output - N array - spectral mask of 1s and 0s
    '''

    gamma = np.mean(csd, axis=1) + gain * np.max(csd, axis=1)
    mask = np.where(csd > gamma[:, np.newaxis, :], np.ones_like(csd), np.zeros_like(csd))

    return mask

def generateTestRegion(testpts, sz=0.15, numsamp = 4):
    '''
    testpts - q x 3 array of testpoints (e.g. bird locations)
    output - q x N x 3 array of points sampled from a region around the test points
    '''
    int_points = np.linspace(testpts - 0.5*sz, testpts + 0.5*sz, num=numsamp)
    dest = np.zeros((testpts.shape[0], numsamp**3, testpts.shape[1]))
    for i in range(testpts.shape[0]): 
        xx, yy, zz = np.meshgrid(int_points[:,i,0], int_points[:,i,1], int_points[:,i,2], indexing='ij')
        dest[i, :, :] = np.stack([xx.ravel(), yy.ravel(), zz.ravel()], axis=1)

    return dest

def calculateTimeDelays(pts, mic_pos, samplerate=1.0):
    '''
    pts - m x 3 array of points to evaluate time delay at
    mic_pos - n x 3 array of microphone positions
    sample_rate - to convert to samples
    output - m x n array of delay times
    '''

    return np.linalg.norm(pts[:, np.newaxis, :] - mic_pos[np.newaxis, :, :], axis=2) * samplerate / c

def filterAndSum(s, tds, padlen = 100):
    '''
    s - n x m x k array of blocked channel signals
        n - num of channels
        m - num of samples (in a block)
        k - num of blocks
    tds - p x n array of delay times
        p - number of grid points
    padlen - length of zero padding on beginning and end of signals
    output - p x k array of SRP-PHAT values corresponding to points in the same order as tds
    '''
    if s.ndim < 3:
        s = s[:, :, np.newaxis]

    #convert to Fourier Space
    N = s.shape[1] #+ np.round(s.shape[1] / 2).astype('int32')
    S = np.fft.fft(s, n=N, axis=1)

    #Phat transform filter in FT space
    phat = 1./ np.where(S != 0, np.abs(S), np.ones_like(S))
    S = S * phat

    gcc = np.zeros((S.shape[0], S.shape[0], S.shape[1], S.shape[2]), dtype='float64')

    for i in range(S.shape[0]):
        #Cross-correlation
        prod = np.multiply(S, np.conj(S[i, np.newaxis, :, :]))
        #IFFT
        gcc[i, :, :, :] = np.real(np.fft.ifft(prod, axis = 1))

    #Shift filter in FT space
    tdoas = -np.round(tds[:, np.newaxis, :] - tds[:, :, np.newaxis]).astype('int32')

    #Evaluate and sum
    srp = np.zeros((tdoas.shape[0], gcc.shape[3]), dtype='float')
    sl._filterAndSum(gcc, tdoas, srp)
    #These lines are the same as these:
    #P, r, c = np.ogrid[:tdoas.shape[0], :tdoas.shape[1], :tdoas.shape[2]]
    #srp = np.einsum('pijk->pk', gcc[c, r , tdoas])
    #This won't execute if you are block processing; See README.txt

    return srp


if __name__=='__main__':

    #usage: python3 SoundLoc.py <micpositions.txt> <cagedims.txt> <song.wav> <birdpos.txt>
    args = sys.argv[1:]
    mic_pos_txt = args[0]
    cage_dims_txt = args[1]
    song_wav= args[2]

    mic_pos = np.loadtxt(mic_pos_txt, delimiter=',')
    cagedims = np.loadtxt(cage_dims_txt, delimiter=',')
    signal = wavfile.read(song_wav)[1].T.astype('float64')

    samplerate = 48000.

    #generate grid of test points
    res = 0.05 #resolution of grid search in meters

    x = np.arange(cagedims[0,0], cagedims[0,1], res)
    y = np.arange(cagedims[1,0], cagedims[1,1], res)
    z = np.arange(cagedims[2,0], cagedims[2,1], res)

    xx, yy, zz = np.meshgrid(x, y, z, indexing='ij')
    #grid_shape = (xx.shape[0], xx.shape[1], xx.shape[2])
    gridpts = np.stack([xx.ravel(), yy.ravel(), zz.ravel()], axis = 1)

    #localization
    tds = calculateTimeDelays(gridpts, mic_pos, samplerate = samplerate)
    srp = filterAndSum(signal, tds)
    #srp = filterAndSum(blockProcess(signal, blocksize, hopsize), tds)
    #np.save('./srp_output.npy',srp)
    #np.save('./grid_points.npy',gridpts)
    max_ind = np.argmax(srp, axis = 0)
    max_pt = gridpts[max_ind, :] #point with max srp

    #Look for closest bird, Comment this out if you don't have locs
    bird_pos_txt = args[3]
    bird_pos = np.loadtxt(bird_pos_txt, delimiter=',')
    near_bird = np.argmin(np.linalg.norm(bird_pos - max_pt, axis = 1), axis = 0)
    near_bird_loc = bird_pos[near_bird, :]
    
    print("Max SRP point: {maxpt}, Singer: {singer}".format(maxpt = max_pt, singer = near_bird))

    #plt.matshow(np.sum(np.reshape(srp, grid_shape), axis = 1))
    #plt.show()
