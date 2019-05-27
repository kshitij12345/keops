"""
=================================
Linking KeOps with GPytorch
=================================

Out-of-the-box, KeOps only provides :ref:`limited support <interpolation-tutorials>` for
`Kriging <https://en.wikipedia.org/wiki/Kriging>`_ 
or `Gaussian process regression <https://scikit-learn.org/stable/modules/gaussian_process.html>`_:
the :class:`KernelSolve <pykeops.torch.KernelSolve>` operator
implements a straightforward conjugate gradient solver for kernel linear systems...
and that's about it.

Fortunately though, KeOps can easily be used
as a scalable GPU backend for versatile, high-level libraries such
as `GPytorch <https://gpytorch.ai/>`_: in this notebook,
we show how to plug KeOps' :mod:`LazyTensor <pykeops.LazyTensor>`
within the first `regression tutorial <https://gpytorch.readthedocs.io/en/latest/examples/01_Simple_GP_Regression/Simple_GP_Regression.html>`_
of GPytorch's documentation.

Due to hard-coded constraints within the structure of GPytorch,
the syntax below is pretty verbose... But **we're working on it**!
Needless to say, feel free to `let us know <https://github.com/getkeops/keops/issues>`_
if you encounter any unexpected behavior with this KeOps-GPytorch interface.

"""

#####################################################################
# Setup 
# -----------------
# Standard imports, including `gpytorch <https://gpytorch.ai/>`_:

import math
import torch
import gpytorch
from matplotlib import pyplot as plt

use_cuda = torch.cuda.is_available()
dtype = torch.cuda.FloatTensor if use_cuda else torch.FloatTensor

#####################################################################
# Toy dataset: some regularly spaced samples on the unit interval,
# and a sinusoid signal corrupted by a small Gaussian noise.

N = 100
train_x = torch.linspace(0, 1, N).type(dtype)
train_y = torch.sin(train_x * (2 * math.pi)) \
        + .2 * torch.randn(train_x.size()).type(dtype)


#####################################################################
# Defining a new KeOps RBF kernel 
# ---------------------------------
# 
# Internally, GPytorch relies on `LazyTensors  <https://gpytorch.readthedocs.io/en/latest/lazy.html>`_
# parameterized by explicit **torch Tensors** - and **nothing** else.
# To let GPytorch use our KeOps CUDA routines, we should thus create
# a new 
# 
# .. note::
#   Ideally, we'd like to be able to **export KeOps LazyTensors** directly as
#   GPytorch objects, but the reliance of the latter's engine on
#   explicit **torch.Tensor** variables is a hurdle that we could not bypass
#   easily. Working on this problem with the GPytorch team, 
#   we hope to provide a simpler syntax for this interface in future releases. 


from pykeops import LazyTensor

class KeOpsRBFLazyTensor(gpytorch.lazy.LazyTensor):
    def __init__(self, x_i, y_j):
        """Creates a symbolic Gaussian RBF kernel out of two point clouds `x_i` and `y_j`."""
        super().__init__( x_i, y_j )
        
        self.x_i, self.y_j = x_i, y_j

        # Compute the kernel matrix symbolically...
        x_i, y_j = LazyTensor( self.x_i[:,None,:] ), LazyTensor( self.y_j[None,:,:] )
        K_xy = ( - ((x_i - y_j)**2).sum(-1) / 2).exp()
        self.K = K_xy  # ... and store it for later use

    def _matmul(self, M):
        """Kernel-Matrix multiplication."""
        return self.K@M
      
    def _size(self):
        """Shape attribute."""
        return torch.Size( self.K.shape )
      
    def _transpose_nonbatch(self):
        """Symbolic transpose operation."""
        return KeOpsRBFLazyTensor( self.y_j, self.x_i )
      
    def _get_indices(self, row_index, col_index, *batch_indices):
        """Returns a (small) explicit sub-matrix, used e.g. for Nystroem approximation."""
        X_i = self.x_i[row_index]
        Y_j = self.y_j[col_index]
        return ( - ((X_i - Y_j)**2).sum(-1) / 2).exp()

    def _quad_form_derivative(self, left_vecs, right_vecs):
        """Given u (left_vecs) and v (right_vecs), computes the derivatives of (u^t K v) w.r.t. K."""
        from collections import deque
        from torchviz import make_dot

        args = tuple(self.representation())
        args_with_grads = tuple(arg for arg in args if arg.requires_grad)

        # Easy case: if we don't require any gradients, then just return!
        if not len(args_with_grads):
            return tuple(None for _ in args)

        # Normal case: we'll use the autograd to get us a derivative
        with torch.autograd.enable_grad():
            loss = (left_vecs * self._matmul(right_vecs)).sum()
            print(loss.grad_fn)
            loss.requires_grad_(True)
            actual_grads = deque(torch.autograd.grad(loss, [self.x_i, self.y_j], allow_unused=True))
            print(args_with_grads[1] is self.y_j)
            # actual_grads = deque(torch.autograd.grad(loss, args_with_grads, allow_unused=True))

        print(self.x_i.requires_grad)
        print(actual_grads)

        # Now make sure that the object we return has one entry for every item in args
        grads = []
        for arg in args:
            if arg.requires_grad:
                grads.append(actual_grads.popleft())
            else:
                grads.append(None)

        return tuple(grads)


#####################################################################
# We can now create a new GPytorch **Kernel** object, wrapped around
# our KeOps+GPytorch LazyTensor:

class KeOpsRBFKernel(gpytorch.kernels.Kernel):
    """Simple KeOps re-implementation of 'gpytorch.kernels.RBFKernel'."""
    def __init__(self, **kwargs):
        super().__init__(has_lengthscale=True, **kwargs)
        
    def forward(self, x1, x2, **params):
        # Rescale the input data and wrap it in a KeOps LazyTensor:
        if x1.dim() == 1: x1 = x1.view(-1,1)
        if x2.dim() == 1: x2 = x2.view(-1,1)
        x_i, y_j = x1.div(self.lengthscale), x2.div(self.lengthscale)
        return KeOpsRBFLazyTensor(x_i, y_j)  # ... and return it as a gyptorch.lazy.LazyTensor

#####################################################################
# And use it to define a new Gaussian Process model:

# We will use the simplest form of GP model, exact inference
class KeOpsGPModel(gpytorch.models.ExactGP):
    def __init__(self, train_x, train_y, likelihood):
        super().__init__(train_x, train_y, likelihood)
        self.mean_module = gpytorch.means.ConstantMean()
        self.covar_module = gpytorch.kernels.ScaleKernel(KeOpsRBFKernel())

    def forward(self, x):
        mean_x = self.mean_module(x)
        covar_x = self.covar_module(x)
        return gpytorch.distributions.MultivariateNormal(mean_x, covar_x)


##########################################################
# **N.B., for the sake of comparison:** the GPytorch documentation went with
# the code below, using the standard ``gpytorch.kernels.RBFKernel()`` 
# instead of our custom ``KeOpsRBFKernel()``:

class ExactGPModel(gpytorch.models.ExactGP):
    def __init__(self, train_x, train_y, likelihood):
        super(ExactGPModel, self).__init__(train_x, train_y, likelihood)
        self.mean_module = gpytorch.means.ConstantMean()
        self.covar_module = gpytorch.kernels.ScaleKernel(gpytorch.kernels.RBFKernel())

    def forward(self, x):
        mean_x = self.mean_module(x)
        covar_x = self.covar_module(x)
        return gpytorch.distributions.MultivariateNormal(mean_x, covar_x)


##########################################################
# **That's it!** We can now initialize our likelihood and model, as recommended by the documentation:

if use_cuda:
    likelihood = gpytorch.likelihoods.GaussianLikelihood().cuda()
    model = KeOpsGPModel(train_x, train_y, likelihood).cuda()
else:
    likelihood = gpytorch.likelihoods.GaussianLikelihood()
    model = KeOpsGPModel(train_x, train_y, likelihood)

#####################################################################
# GP training
# -----------------
# The code below is now a direct copy-paste from the
# `GPytorch 101 tutorial <https://gpytorch.readthedocs.io/en/latest/examples/01_Simple_GP_Regression/Simple_GP_Regression.html>`_:

# Find optimal model hyperparameters
model.train()
likelihood.train()

# Use the adam optimizer
optimizer = torch.optim.Adam([
    {'params': model.parameters()},  # Includes GaussianLikelihood parameters
], lr=0.1)

# "Loss" for GPs - the marginal log likelihood
mll = gpytorch.mlls.ExactMarginalLogLikelihood(likelihood, model)

training_iter = 50
for i in range(training_iter):
    # Zero gradients from previous iteration
    optimizer.zero_grad()
    # Output from model
    output = model(train_x)
    # Calc loss and backprop gradients
    loss = -mll(output, train_y)
    loss.backward()
    if i % 10 == 0:
      print('Iter %d/%d - Loss: %.3f   lengthscale: %.3f   noise: %.3f' % (
          i + 1, training_iter, loss.item(),
          model.covar_module.base_kernel.lengthscale.item(),
          model.likelihood.noise.item()
      ))
    optimizer.step()

#####################################################################
# Prediction and display
# -------------------------
# Get into evaluation (predictive posterior) mode
#

model.eval()
likelihood.eval()

#####################################################################
# Test points are regularly spaced along [0,1].
# We make predictions by feeding our ``model`` through the ``likelihood``:

with torch.no_grad(), gpytorch.settings.fast_pred_var():
    test_x = torch.linspace(0, 1, 51).type(dtype)
    observed_pred = likelihood(model(test_x))

#####################################################################
# Display:
#

with torch.no_grad():
    # Initialize plot
    f, ax = plt.subplots(1, 1, figsize=(12, 9))

    # Get upper and lower confidence bounds
    lower, upper = observed_pred.confidence_region()
    # Plot training data as black stars
    ax.plot(train_x.cpu().numpy(), train_y.cpu().numpy(), 'k*')
    # Plot predictive means as blue line
    ax.plot(test_x.cpu().numpy(), observed_pred.mean.cpu().numpy(), 'b')
    # Shade between the lower and upper confidence bounds
    ax.fill_between(test_x.cpu().numpy(), lower.cpu().numpy(), upper.cpu().numpy(), alpha=0.5)
    ax.set_ylim([-3, 3])
    ax.legend(['Observed Data', 'Mean', 'Confidence'])

plt.show()