#include <mex.h>
#include "cuda_conv.cu"

#define UseCudaOnDoubles USE_DOUBLE_PRECISION

//////////////////////////////////////////////////////////////////
///////////////// MEX ENTRY POINT ////////////////////////////////
//////////////////////////////////////////////////////////////////


/* the gateway function */
void mexFunction( int nlhs, mxArray *plhs[],
        int nrhs, const mxArray *prhs[])
    //plhs: double *gamma
    //prhs: double *x, double *y, double *beta, double sigma

{ 

    // register an exit function to prevent crash at matlab exit or recompiling
    mexAtExit(ExitFcn);

    /*  check for proper number of arguments */
    if(nrhs != 4) 
        mexErrMsgTxt("4 inputs required.");
    if(nlhs < 1 | nlhs > 1) 
        mexErrMsgTxt("One output required.");

    //////////////////////////////////////////////////////////////
    // Input arguments
    //////////////////////////////////////////////////////////////

    int argu = -1;

    //----- the first input argument: x--------------//
    argu++;
    /*  create a pointer to the input vectors srcs */
    double *x = mxGetPr(prhs[argu]);
    /*  input sources */
    int dimpoint = mxGetM(prhs[argu]); //mrows
    int nx = mxGetN(prhs[argu]); //ncols

    //----- the second input argument: y--------------//
    argu++;
    /*  create a pointer to the input vectors trgs */
    double *y = mxGetPr(prhs[argu]);
    /*  get the dimensions of the input targets */
    int ny = mxGetN(prhs[argu]); //ncols
    /* check to make sure the first dimension is dimpoint */
    if( mxGetM(prhs[argu])!=dimpoint ) {
        mexErrMsgTxt("Input y must have same number of rows as x.");
    }

    //------ the third input argument: beta---------------//
    argu++;
    /*  create a pointer to the input vectors wts */
    double *beta = mxGetPr(prhs[argu]);
    /*  get the dimensions of the input weights */
    int dimvect = mxGetM(prhs[argu]);
    /* check to make sure the second dimension is ny */
    if( mxGetN(prhs[argu])!=ny ) {
        mexErrMsgTxt("Input beta must have same number of columns as y.");
    }

    //----- the fourth input argument: sigma-------------//
    argu++;
    /* check to make sure the input argument is a scalar */
    if( !mxIsDouble(prhs[argu]) || mxIsComplex(prhs[argu]) ||
            mxGetN(prhs[argu])*mxGetM(prhs[argu])!=1 ) {
        mexErrMsgTxt("Input sigma must be a scalar.");
    }
    /*  get the scalar input sigma */
    double sigma = mxGetScalar(prhs[argu]);
    if (sigma <= 0.0)
        mexErrMsgTxt("Input sigma must be a positive number.");
    double oosigma2 = 1.0f/(sigma*sigma);

    //////////////////////////////////////////////////////////////
    // Output arguments
    //////////////////////////////////////////////////////////////

    /*  set the output pointer to the output result(vector) */
    plhs[0] = mxCreateDoubleMatrix(dimvect,nx,mxREAL);

    /*  create a C pointer to a copy of the output result(vector)*/
    double *gamma = mxGetPr(plhs[0]);

    //////////////////////////////////////////////////////////////
    // Call Cuda codes
    //////////////////////////////////////////////////////////////

#if UseCudaOnDoubles   
    GaussGpuEvalConv<double>(oosigma2,x,y,beta,gamma,dimpoint,dimvect,nx,ny);
#else
    // convert to float
    float *x_f = new float[nx*dimpoint];
    float *y_f = new float[ny*dimpoint];
    float *beta_f = new float[ny*dimvect];
    float *gamma_f = new float[nx*dimvect];
    for(int i=0; i<nx*dimpoint; i++)
        x_f[i] = x[i];
    for(int i=0; i<ny*dimpoint; i++)
        y_f[i] = y[i];
    for(int i=0; i<ny*dimvect; i++)
        beta_f[i] = beta[i];


    // function calls;
    GaussGpuEvalConv(oosigma2,x_f,y_f,beta_f,gamma_f,dimpoint,dimvect,nx,ny);

    for(int i=0; i<nx*dimvect; i++)
        gamma[i] = gamma_f[i];

    delete [] x_f;
    delete [] y_f;
    delete [] beta_f;
    delete [] gamma_f;
#endif

    return;

}
