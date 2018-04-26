# To test, first compile the kernel via :
# ./compile "GaussKernel<P<0,1>,X<1,3>,Y<2,3>,Y<3,3>>"
#
# This will compile the isotropic Gaussian kernel in dimension 3,
# which takes as input :
# - a scalar parameter P<0,1>, inverse of the variance
# - an array X_1 (x_i) of dimension N-by-3
# - an array Y_2 (y_j) of dimension M-by-3
# - an array Y_3 (b_j) of dimension M-by-3

import numpy as np

import torch

import ctypes
from ctypes import POINTER, c_float, c_int, cast

import os.path

from hashlib import sha256

from pykeops.common.compile_routines import compile_generic_routine
from pykeops import build_folder, script_folder, dll_prefix, dll_ext

# GENERIC FORMULAS DLLs =========================================================================

__cuda_convs_generic = {}


def get_cuda_conv_generic(aliases, formula, cuda_type, sum_index, backend):
    """
    Returns the appropriate CUDA routine, given:
    - a list of aliases (strings)
    - a formula         (string)
    - a cuda_type       ("float" or "double")
    - a sum index       ( 0 for a sum over j, result indexed by i,
                          1 for a sum over i, result indexed by j)
    - a backend         (one of "CPU", "GPU_1D_host",   "GPU_2D_host",
                                       "GPU_2D_device", "GPU_2D_device" )

    If it is not already in __cuda_convs_generic, load it from the appropriate "build" folder.
    If the .dll/.so cannot be found, compile it on-the-fly (and store it for later use).
    """

    # Compose the DLL name ----------------------------------------------------------------------
    formula = formula.replace(" ", "")  # Remove spaces
    aliases = [alias.replace(" ", "") for alias in aliases]

    # Since the OS prevents us from using arbitrary long file names, an okayish solution is to call
    # a standard hash function, and hope that we won't fall into a non-injective nightmare case...
    dll_name = ",".join(aliases + [formula]) + "_" + cuda_type
    dll_name = sha256(dll_name.encode("utf-8")).hexdigest()

    if dll_name in __cuda_convs_generic:  # If this formula has already been loaded in memory...
        return __cuda_convs_generic[dll_name][backend][sum_index]
    else:  # Otherwise :
        # Load the DLL --------------------------------------------------------------------------

        dllabspath = build_folder + dll_name + dll_ext

        try:
            dll = ctypes.CDLL(dllabspath , mode=ctypes.RTLD_GLOBAL)
        except OSError:
            compile_generic_routine(aliases, formula, dll_name, cuda_type)
            dll = ctypes.CDLL(dllabspath, mode=ctypes.RTLD_GLOBAL)
            print("Loaded.")

        # These are all the C++ routines defined in "link_autodiff.cu" :
        routine_CPU_i = dll.CpuConv
        routine_CPU_j = dll.CpuTransConv

        routine_CPU_i.argtypes = [c_int, c_int, POINTER(c_float), POINTER(POINTER(c_float))]
        routine_CPU_j.argtypes = [c_int, c_int, POINTER(c_float), POINTER(POINTER(c_float))]

        # Add our new functions to the module's dictionnary :
        __cuda_convs_generic[dll_name] = {"CPU": [routine_CPU_i, routine_CPU_j]}

        # Avoid error if the lib was not compiled with cuda
        try: 
            # These are all the CUDA routines defined in "link_autodiff.cu" :
            routine_GPU_host_1D_i = dll.GpuConv1D
            routine_GPU_host_1D_j = dll.GpuTransConv1D
            routine_GPU_host_2D_i = dll.GpuConv2D
            routine_GPU_host_2D_j = dll.GpuTransConv2D
            routine_GPU_device_1D_i = dll.GpuConv1D_FromDevice
            routine_GPU_device_1D_j = dll.GpuTransConv1D_FromDevice
            routine_GPU_device_2D_i = dll.GpuConv2D_FromDevice
            routine_GPU_device_2D_j = dll.GpuTransConv2D_FromDevice
            
            routine_GPU_host_1D_i.argtypes = [c_int, c_int, POINTER(c_float), POINTER(POINTER(c_float))]
            routine_GPU_host_1D_j.argtypes = [c_int, c_int, POINTER(c_float), POINTER(POINTER(c_float))]
            routine_GPU_host_2D_i.argtypes = [c_int, c_int, POINTER(c_float), POINTER(POINTER(c_float))]
            routine_GPU_host_2D_j.argtypes = [c_int, c_int, POINTER(c_float), POINTER(POINTER(c_float))]
            routine_GPU_device_1D_i.argtypes = [c_int, c_int, POINTER(c_float), POINTER(POINTER(c_float))]
            routine_GPU_device_1D_j.argtypes = [c_int, c_int, POINTER(c_float), POINTER(POINTER(c_float))]
            routine_GPU_device_2D_i.argtypes = [c_int, c_int, POINTER(c_float), POINTER(POINTER(c_float))]
            routine_GPU_device_2D_j.argtypes = [c_int, c_int, POINTER(c_float), POINTER(POINTER(c_float))]

            __cuda_convs_generic[dll_name].update({
                 "GPU_1D_host": [routine_GPU_host_1D_i, routine_GPU_host_1D_j],
                 "GPU_2D_host": [routine_GPU_host_2D_i, routine_GPU_host_2D_j],
                 "GPU_1D_device": [routine_GPU_device_1D_i, routine_GPU_device_1D_j],
                 "GPU_2D_device": [routine_GPU_device_2D_i, routine_GPU_device_2D_j] })
        except AttributeError:
            # we do not have the Cuda routines, this is ok only if the backend is "CPU"
            if backend != "CPU":
                raise ValueError('Cuda routines are not available.')
            
        return __cuda_convs_generic[dll_name][backend][sum_index]  # And return it.


# Ideally, this routine could be implemented by Joan :
def cuda_conv_generic(formula, signature, result, *args,
                      backend="auto",
                      aliases=[], sum_index=0,
                      cuda_type="float", grid_scheme="2D"):
    """
    Executes the "autodiff" kernel associated to "formula".
    Backend is one of "auto", "GPU_1D" or "GPU_2D",
        and will be reassigned to "CPU", "GPU_1D_host",   "GPU_2D_host",
        "GPU_1D_device", "GPU_2D_device", depending on input data (see below)

    Aliases can be given as a list of strings.
    sum_index specifies whether the summation should be done over "I/X" (sum_index=1) or "J/Y" (sum_index=0).
    The arguments are given as :
        variables, sorted in the order specified by the "Var<index,dimension,I-or-J-or-P>" syntax.
    For instance,
        ```
        aliases = [ "DIMPOINT = 3", "DIMVECT = 4", "DIMOUT = 5",
                    "X = Var<1,DIMPOINT,0>" ,
                    "Y = Var<2,DIMPOINT,1>" ,
                    "U = Var<3,DIMVECT ,0>" ,
                    "V = Var<4,DIMVECT ,1>" ,
                    "B = Var<5,DIMOUT  ,1>" ,
                    "C = Param<0,1>"          ]
        formula = "Scal< Square<Scalprod<U,V>>, " \
                + "Scal< Exp< Scal<C, Minus<SqNorm2<Subtract<X,Y>>> > >,  B> >"
        cuda_conv_generic( formula, signature,
                           R, C, X, Y, U, V, B,
                           aliases = aliases )
        ```
    is a legal call, where :
    - R is a nx-by-5 float array (the output array)
    - C is a scalar
    - X is a nx-by-3 float array
    - Y is a ny-by-3 float array
    - U is a nx-by-4 float array
    - V is a ny-by-4 float array
    - B is a ny-by-5 float array

    (nx and ny are automatically inferred from the data;
    an error is thrown if the lengths of the input arrays are not compatible with each other)

    If the CUDA kernel associated to the given formula is not found in the "build/" folder,
    the routine is compiled on-the-fly using the "compile" script.

    N.B.: additional examples documenting the use of symbolic differentiation :

    Gradient with respect to X : ---------------------------------------------------------------
        ```
        aliases_gx = aliases + [ "Eta = Var<5,DIMOUT,0>" ]
        formula_gx = "Grad< " + formula + ", X, Eta>"
        cuda_conv_generic( formula,
                           R, C, X, Y, U, V, B, E,
                           aliases = aliases, sum_index = 0 )
        ```
    where :
    - R is a nx-by-3 float array (same as X)
    - E is a nx-by-5 float array (same as the output of "formula")


    Gradient with respect to V : ---------------------------------------------------------------
        ```
        aliases_gv = aliases + [ "Eta = Var<5,DIMOUT,0>" ]
        formula_gv = "Grad< " + formula + ", V, Eta>"
        cuda_conv_generic( formula,
                           R, C, X, Y, U, V, B, E,
                           aliases = aliases, sum_index = 1 )
        ```
    where :
    - R is a ny-by-4 float array (same as V)
    - E is a nx-by-5 float array (same as the output of "formula")

    """
    # Infer if we're working with numpy arrays or torch tensors from result's type :

    if hasattr(result, "ctypes"):  # Assume we're working with numpy arrays

        device = "CPU"

        def assert_contiguous(x):
            """Non-contiguous arrays are a mess to work with,
            so we require contiguous arrays from the user."""
            if not x.flags.c_contiguous: raise ValueError("Please provide 'C-contiguous' numpy arrays.")

        def ndims(x):
            return x.ndim

        def size(x):
            return x.size

        def to_ctype_pointer(x):
            assert_contiguous(x)
            return x.ctypes.data_as(POINTER(c_float))

        def vect_from_list(l):
            return np.hstack(l)

    elif hasattr(result, "data_ptr"):  # Assume we're working with torch tensors

        device = "GPU" if result.is_cuda else "CPU"

        def assert_contiguous(x):
            """Non-contiguous arrays are a mess to work with,
            so we require contiguous arrays from the user."""
            if not x.is_contiguous():
                print(x)
                raise ValueError("Please provide 'contiguous' torch tensors.")

        def ndims(x):
            return len(x.size())

        def size(x):
            return x.numel()

        def to_ctype_pointer(x):
            assert_contiguous(x)
            return cast(x.data_ptr(), POINTER(c_float))

        def vect_from_list(l):
            return torch.cat(l)

    else:
        raise TypeError("result should either be a numpy array or a torch tensor.")

    # Check that *args matches the given signature ----------------------------------------------
    variables = [];
    nx = -1;
    ny = -1
    for (arg, sig) in zip(args, signature[1:]):  # Signature = [ Result, *Args]

        if sig[1] == 0:  # If the current arg is an "X^n_i" variable
            if not (ndims(arg) == 2):          raise ValueError("Generic CUDA routines require 2D-arrays as variables.")
            if nx == -1: nx = arg.shape[0]  # First "X^0_i" variable encountered
            if not (nx == arg.shape[0]): raise ValueError(
                "CAT=0 variables (X_i) lengths are not compatible with each other.")
            if not (sig[0] == arg.shape[1]): raise ValueError(
                "The size of a CAT=0 variable does not match the signature.")
            variables.append(arg)  # No worries : arg is in fact a pointer, so no copy is done here

        elif sig[1] == 1:  # If the current arg is an "Y^m_j" variable
            if not (ndims(arg) == 2):          raise ValueError("Generic CUDA routines require 2D-arrays as variables.")
            if ny == -1: ny = arg.shape[0]  # First "Y^0_j" variable encountered
            if not (ny == arg.shape[0]): raise ValueError(
                "CAT=1 variables (Y_j) lengths are not compatible with each other.")
            if not (sig[0] == arg.shape[1]): raise ValueError(
                "The size of a CAT=1 variable does not match the signature.")
            variables.append(arg)  # No worries : arg is in fact a pointer, so no copy is done here

        elif sig[1] == 2:  # If the current arg is a parameter
            if not (sig[0] == arg.shape[0]): raise ValueError(
                "The size of a CAT=2 variable does not match the signature.")
            variables.append(arg)

    # Assert that we won't make an "empty" convolution :
    if not nx > 0: raise ValueError("There should be at least one (nonempty...) 'X_i' variable as input.")
    if not ny > 0: raise ValueError("There should be at least one (nonempty...) 'Y_j' variable as input.")

    # Check the result's shape :
    sig = signature[0]  # Signature = [ Result, *Args]
    if sig[1] == 2: raise ValueError("Derivatives wrt. parameters have not been implemented yet.")
    if not ndims(result) == 2: raise ValueError("The result array should be bi-dimensional.")
    if not sig[0] == result.shape[1]: raise ValueError("The width of the result array does not match the signature.")

    if sum_index == 0:  # Sum wrt. j, final result index by i
        if not sig[1] == 0: raise ValueError("The result's signature does not indicate an indexation by 'i'...")
        if not nx == result.shape[0]: raise ValueError(
            "The result array does not have the correct number of lines wrt. the 'X_i' inputs given.")

    if sum_index == 1:  # Sum wrt. i, final result index by j
        if not sig[1] == 1: raise ValueError("The result's signature does not indicate an indexation by 'j'...")
        if not ny == result.shape[0]: raise ValueError(
            "The result array does not have the correct number of lines wrt. the 'Y_j' inputs given.")

    # From python to C float pointers and int : -------------------------------------------------
    vars_p = tuple(to_ctype_pointer(var) for var in variables)
    vars_p = (POINTER(c_float) * len(vars_p))(*vars_p)

    result_p = to_ctype_pointer(result)
    
    
    
    # Try to make a good guess for the backend...
    # available methods are: (host means Cpu, device means Gpu)
    #   CPU : computations performed with the host from host arrays
    #   GPU_1D_device : computations performed on the device from device arrays, using the 1D scheme
    #   GPU_2D_device : computations performed on the device from device arrays, using the 2D scheme
    #   GPU_1D_host : computations performed on the device from host arrays, using the 1D scheme
    #   GPU_2D_host : computations performed on the device from host data, using the 2D scheme
    
    # first determine where is located the data ; all arrays should be on the host or all on the device  
    VarsAreOnGpu = tuple(map(lambda x:x.is_cuda,(result,)+tuple(variables))) 
    if all(VarsAreOnGpu):
        MemType = "device"
    elif not any(VarsAreOnGpu):
        MemType = "host"
    else:
        raise ValueError("At least two input variables have different memory locations (Cpu/Gpu).")
    
    # rules in this part:
    #  - data on the host will be processed on the host, unless GPU is specified
    #  - default scheme for GPU is the 1D scheme
    if backend == "auto":
        if MemType == "host":
            backend = "CPU" 
        else: 
            backend = "GPU_1D_device"
    elif backend == "GPU":
        if MemType == "host":
            backend = "GPU_1D_host" 
        else:
            backend = "GPU_1D_device"
    elif backend == "GPU_1D" or backend == "GPU_2D":
        backend += "_" + MemType # gives GPU_1D_host, GPU_1D_device, GPU_2D_host, GPU_2D_device
    else:
        raise ValueError('Invalid backend specified. Should be one of "auto", "GPU", "GPU_1D", "GPU_2D"')

    # Let's use our GPU, which works "in place" : -----------------------------------------------
    # N.B.: depending on sum_index, we're going to load "GpuConv" or "GpuTransConv",
    #       which make a summation wrt. 'j' or 'i', indexing the final result with 'i' or 'j'.
    routine = get_cuda_conv_generic(aliases, formula, cuda_type, sum_index, backend)
    routine(nx, ny, result_p, vars_p)


if __name__ == '__main__':
    """
    testing, benchmark convolution with two naive python implementations of the Gaussian convolution
    """
    np.set_printoptions(linewidth=200)

    sizeX = int(500)
    sizeY = int(100)
    dimPoint = int(3)
    dimVect = int(3)
    sigma = float(2)

    if True:  # Random test
        x = np.random.rand(sizeX, dimPoint).astype('float32')
        y = np.random.rand(sizeY, dimPoint).astype('float32')
        beta = np.random.rand(sizeY, dimVect).astype('float32')
    else:  # Deterministic one
        x = np.ones((sizeX, dimPoint)).astype('float32')
        y = np.ones((sizeY, dimPoint)).astype('float32')
        beta = np.ones((sizeY, dimVect)).astype('float32')

    ooSigma2 = np.array([float(1 / (sigma * sigma))]).astype('float32')  # Compute this once and for all
    # Call cuda kernel
    gamma = np.zeros(dimVect * sizeX).astype('float32')
    cuda_conv(x, y, beta, gamma, ooSigma2)  # In place, gamma_i = k(x_i,y_j) @ beta_j
    gamma = gamma.reshape((sizeX, dimVect))

    # A first implementation, with (shock horror !) a bunch of "for" loops
    oosigma2 = 1 / (sigma * sigma)
    gamma_py = np.zeros((sizeX, dimVect)).astype('float32')

    for i in range(sizeX):
        for j in range(sizeY):
            rij2 = 0.
            for k in range(dimPoint):
                rij2 += (x[i, k] - y[j, k]) ** 2
            for l in range(dimVect):
                gamma_py[i, l] += np.exp(-rij2 * oosigma2) * beta[j, l]

    # A second implementation, a bit more efficient
    r2 = np.zeros((sizeX, sizeY)).astype('float32')
    for i in range(sizeX):
        for j in range(sizeY):
            for k in range(dimPoint):
                r2[i, j] += (x[i, k] - y[j, k]) ** 2

    K = np.exp(-r2 * oosigma2)
    gamma_py2 = np.dot(K, beta)

    # compare output
    print("\nCuda convolution :")
    print(gamma)

    print("\nPython convolution 1 :")
    print(gamma_py)

    print("\nPython convolution 2 :")
    print(gamma_py2)

    print("\nIs everything okay ? ")
    print(np.allclose(gamma, gamma_py))
    print(np.allclose(gamma, gamma_py2))