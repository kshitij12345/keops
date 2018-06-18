import torch
from torch.autograd import Variable

from pykeops import default_cuda_type
from pykeops.common.parse_type_old import parse_types
from pykeops.common.generic_reduction import genred, genred_fromdevice

class generic_sum :
    def __init__(self, formula, *types) :
        self.formula = formula
        self.aliases, self.signature, self.sum_index = parse_types( types )
        
    def __call__(self, *args, backend = "auto") :
        return pytorch_genred.apply(self.formula, self.aliases, self.signature, *args, self.sum_index, backend)


class generic_logsumexp :
    def __init__(self, formula, *types) :
        self.formula = "LogSumExp(" + formula + ")"
        self.aliases, self.signature, self.sum_index = parse_types( types )
        
    def __call__(self, *args, backend = "auto") :
        return pytorch_genred.apply(self.formula, self.aliases, self.signature, *args, self.sum_index, backend)


class pytorch_genred(torch.autograd.Function):
    """
    """

    @staticmethod
    def forward(ctx, formula, aliases, signature, *args, sum_index, backend):
        # Save everything to compute the gradient -----------------------------------------------
        # N.B.: relying on the "ctx.saved_variables" attribute is necessary
        #       if you want to be able to differentiate the output of the backward
        #       once again. It helps pytorch to keep track of "who is who".
        ctx.save_for_backward(*args)  # Call at most once in the "forward".
        ctx.backend = backend
        ctx.aliases = aliases
        ctx.formula = formula
        ctx.signature = signature
        ctx.sum_index = sum_index

        if args[0].is_cuda:
            genred_fromdevice( formula, aliases, *vars_p, sum_index= sum_index, backend = backend)
        else:
            vars_p = tuple(var.data.numpy() for var in args) # no copy!
            result = torch.from_numpy(genred( formula, aliases, *vars_p, sum_index= sum_index, backend = backend))
        return result

    @staticmethod
    def backward(ctx, G):
        backend = ctx.backend
        aliases = ctx.aliases
        formula = ctx.formula
        signature = ctx.signature
        sum_index = ctx.sum_index
        args = ctx.saved_tensors  # Unwrap the saved variables

        # number of arguments (including parameters)
        nvars = 0;
        for sig in signature[1:]:
            nvars += 1

        # If formula takes 5 variables (numbered from 0 to 4), then the gradient
        # wrt. the output, G, should be given as a 6-th variable (numbered 5),
        # with the same dim-cat as the formula's output.
        eta = "Var(" + str(nvars) + "," + str(signature[0][0]) + "," + str(signature[0][1]) + ")"
        grads = []  # list of gradients wrt. args;
        arg_ind = 5  # current arg index (4 since backend, ... are in front of the tensors); 
        var_ind = 0  # current Variable index;

        for sig in signature[1:]:  # Run through the actual parameters, given in *args in the forward.
            if not ctx.needs_input_grad[arg_ind]:  # If the current gradient is to be discarded immediatly...
                grads.append(None)  # Don't waste time computing it.
            else:  # Otherwise, the current gradient is really needed by the user:
                # adding new aliases is waaaaay too dangerous if we want to compute
                # second derivatives, etc. So we make explicit references to Var<ind,dim,cat> instead.
                var = "Var(" + str(var_ind) + "," + str(sig[0]) + "," + str(sig[1]) + ")"  # V
                formula_g = "Grad(" + formula + "," + var + "," + eta + ")"  # Grad<F,V,G>
                args_g = args + (G,)  # Don't forget the gradient to backprop !
                
                # N.B.: if I understand PyTorch's doc, we should redefine this function every time we use it?
                genconv = pytorch_genred().apply

                if sig[1] == 2:  # we're referring to a parameter, so we'll have to sum both wrt 'i' and 'j'
                    sumindex_g  = 1  # The first sum will be done wrt 'i'
                    signature_g = [ [sig[0],1] ] + signature[1:] + signature[:1]
                    grad = genconv(backend, aliases, formula_g, signature_g, sumindex_g, *args_g)
                    # Then, sum 'grad' wrt 'j' :
                    # I think that ".sum"'s backward introduces non-contiguous arrays,
                    # and is thus non-compatible with pytorch_genred:
                    # grad = grad.sum(0) 
                    # We replace it with a "handmade hack" :
                    grad = Variable(torch.ones(1, grad.shape[0]).type_as(grad.data)) @ grad
                    grad = grad.view(-1)
                else :
                    # sumindex is "the index that stays in the end", not "the one in the sum"
                    # (It's ambiguous, I know... But it's the convention chosen by Joan, which makes
                    #  sense if we were to expand our model to 3D tensors or whatever.)
                    sumindex_g  = sig[1]  # The sum will be "eventually indexed just like V".
                    signature_g = [sig] + signature[1:] + signature[:1]
                    grad = genconv(backend, aliases, formula_g, signature_g, sumindex_g, *args_g)
                grads.append(grad)

            # increment the Variable counts
            arg_ind += 1 ; var_ind += 1  

        # Grads wrt.  backend, aliases, formula, signature, sum_index, *args
        return (None, None, None, None, None, *grads)