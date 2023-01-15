
# @ = @ = @ = @ = @ = @ = @ = @ = @ = @ = @ = @ = @ = @ = @ = @ = @ = @ = @ = @ = @ = @ = @ = @ =
import torch as tt
import torch.nn as nn
#import torch.nn.functional as ff
import math
# @ = @ = @ = @ = @ = @ = @ = @ = @ = @ = @ = @ = @ = @ = @ = @ = @ = @ = @ = @ = @ = @ = @ = @ =


class RNNX(nn.Module):

    """ Extended versions of RNN 
        - additional parameters defined for output
        - can choose custom activation at each gate and each output (including seperate for last layrt)
        - if output_sizes is None, works same as RNN """
    

    def __init__(self,
                input_size,         # input features
                hidden_sizes,       # hidden features at each layer
                output_sizes=None,  # output features at each layer (if None, same as hidden)
                dropout=0.0,        # dropout after each layer, only if hidden_sizes > 1
                batch_first=False,  # if true, excepts input as (batch_size, seq_len, input_size) else (seq_len, batch_size, input_size)
                stack_output=False, # if true, stack output from all timesteps, else returns a list of outputs
                cell_bias = True, 
                out_bias = True,
                dtype=None,
                device=None,
                ) -> None:
        super().__init__()
        self.input_size = int(input_size)
        self.hidden_sizes = tuple(hidden_sizes)
        self.n_hidden = len(self.hidden_sizes)
        self.n_last = self.n_hidden-1
        if output_sizes is not None:
            self.output_sizes = tuple(output_sizes)
            self.n_output = len(self.output_sizes)
            assert self.n_hidden==self.n_output, f'hidden_sizes should be euqal to output_sizes, {self.n_hidden}!={self.n_output}'
        else:
            self.output_sizes = None
            self.n_output=0
        self.cell_bias=cell_bias
        self.out_bias=out_bias

        self.batch_first = batch_first
        self.batch_dim = (0 if batch_first else 1)
        self.seq_dim = (1 if batch_first else 0)
        self.stack_output = stack_output
        
        # set dropouts
        if hasattr(dropout, '__len__'): # different droupout at each layer
            if len(dropout) < self.n_hidden-1:
                self.dropouts = list(dropout)
                while len(self.dropouts) < self.n_hidden-1: self.dropouts.append(0.0)
            else:
                self.dropouts = list(dropout[0:self.n_hidden-1])
        else:
            self.dropouts = [ dropout for _ in range(self.n_hidden-1) ]
        self.dropouts.append(0.0) # for last layer, no dropout

        # build & initialize internal parameters
        self.parameters_module = self.build_parameters(dtype, device)
        self.reset_parameters() # reset_parameters should be the lass call before exiting __init__

    def _generate_parameters_(n, layer_sizes, has_bias, dtype, device):
        weights = [[] for _ in range(n)]
        for i in range(1, len(layer_sizes)):
            in_features, out_features = layer_sizes[i-1], layer_sizes[i]
            for j in range(n):
                weights[j].append(nn.Linear(in_features + out_features, out_features, 
                            has_bias, dtype=dtype, device=device))
        return weights

    def _build_parameters_(self, hidden_names, output_names, dtype, device):
        if self.n_output>0:
            names=hidden_names
            input_sizes=(self.input_size,) + self.output_sizes[:-1]
            n = len(hidden_names)
            weights = [[] for _ in range(n)]
            for in_features, cat_features, out_features in zip(input_sizes, self.hidden_sizes, self.hidden_sizes):
                for j in range(n):
                    weights[j].append(nn.Linear(in_features + cat_features, out_features, 
                                self.cell_bias, dtype=dtype, device=device))
            for name,weight in zip(hidden_names, weights): setattr(self, name, nn.ModuleList(weight))
            
            names=names+output_names

            n = len(output_names)
            weights = [[] for _ in range(n)]
            for in_features, cat_features, out_features in zip(input_sizes, self.hidden_sizes, self.output_sizes):
                for j in range(n):
                    weights[j].append(nn.Linear(in_features + cat_features, out_features, 
                                self.out_bias, dtype=dtype, device=device))
            for name,weight in zip(output_names, weights): setattr(self, name, nn.ModuleList(weight))
        else:
            names=hidden_names
            n = len(hidden_names)
            weights = [[] for _ in range(n)]
            input_sizes=(self.input_size,) + self.hidden_sizes[:-1]
            for in_features, out_features in zip(input_sizes, self.hidden_sizes):
                for j in range(n):
                    weights[j].append(nn.Linear(in_features + out_features, out_features, 
                                self.cell_bias, dtype=dtype, device=device))
            for name,weight in zip(hidden_names, weights): setattr(self, name, nn.ModuleList(weight))
        return tuple([getattr(self, name) for name in names])

    def _build_activations_(self, activation_arg, name):
        self.modular_activation=None
        def no_act(x): return x
        if activation_arg is None: activation_arg=no_act
        if hasattr(activation_arg, '__len__'):
            # activation_arg is like activation_arg=(nn.Tanh, {})
            actModule = activation_arg[0]
            actArgs = activation_arg[1]
            setattr(self, name, actModule(**actArgs))
            self.modular_activation= True #<--- modular activations
        else:
            # activation_arg is like activation_arg=tt.tanh
            setattr(self, name, activation_arg)
            self.modular_activation= False

    def reset_parameters(self):
        for modulelist in self.parameters_module:
            for hs,m in zip(self.hidden_sizes,modulelist):
                stdv = 1.0 / math.sqrt(hs) if hs > 0 else 0
                for w in m.parameters(): nn.init.uniform_(w, -stdv, stdv)

    def init_hidden(self, batch_size, dtype=None, device=None):
        return tuple([ 
            [tt.zeros(size=(batch_size, hs), dtype=dtype, device=device) for hs in self.hidden_sizes]  \
              for _ in range(self.n_states)  ])

    def forward(self, Xt, h=None, future=0):
        if h is None: h=self.init_hidden(Xt.shape[self.batch_dim], Xt.dtype, Xt.device)
        Ht=[h]
        Yt = [] #<---- outputs at each timestep
        for xt in tt.split(Xt, 1, dim=self.seq_dim): 
            x, h = xt.squeeze(dim=self.seq_dim), Ht[-1]
            y, h_ = self.forward_one(x, h)
            Yt.append(y)
            Ht.append(h_)

        #<--- IMP: future arg will work only when (input_size == hidden_size of the last layer)
        for _ in range(future):
            x, h = Yt[-1], Ht[-1]
            y, h_ = self.forward_one(x, h)
            Yt.append(y)
            Ht.append(h_)

        out = tt.stack(Yt, dim=self.seq_dim) if self.stack_output else Yt
        hidden = Ht[-1]
        return  out, hidden

class ELMANX(RNNX):

    def __init__(self, input_size, hidden_sizes, output_sizes=None, dropout=0, batch_first=False, stack_output=False, cell_bias=True, out_bias=True, dtype=None, device=None,
            activation_gate=tt.sigmoid, activation_out=None, activation_last=None) -> None:
        self.activation_gate = activation_gate
        self.activation_out = activation_out
        self.activation_last = activation_last
        self.n_states=1
        super().__init__(input_size, hidden_sizes, output_sizes, dropout, batch_first, stack_output, cell_bias, out_bias, dtype, device)

    def build_parameters(self, dtype, device):
        pnameL = ('ihL',)
        self._build_activations_(self.activation_gate, 'actG')

        if self.n_output>0: 
            self._build_activations_(self.activation_out, 'actY')
            self._build_activations_(self.activation_last, 'act_')
            onameL = ('iyL',)
            self.forward_one = self.forward_one_y
        else:
            onameL = None
            self.forward_one = self.forward_one_x
        return self._build_parameters_(pnameL, onameL, dtype, device)
        
    def forward_one_x(self, x, s):
        H = []
        h, = s
        for i in range(self.n_hidden):
            xh = tt.concat( (x, h[i]), dim=-1)
            x = self.actG( self.ihL[i]( xh ) )
            H.append(x)
            x = tt.dropout(x, self.dropouts[i], self.training) #<--- dropout only output
        return x, (H,)

    def forward_one_y(self, x, s):
        H = []
        h, = s
        for i in range(self.n_hidden):
            xh = tt.concat( (x, h[i]), dim=-1)
            d = self.actG( self.ihL[i]( xh ) )
            H.append(d)
            if i==self.n_last:
                x = self.act_( self.iyL[i]( xh ) )  
            else:
                x = self.actY( self.iyL[i]( xh ) )
                x = tt.dropout(x, self.dropouts[i], self.training) #<--- dropout only output
        return x, (H,)

class GRUX(RNNX):

    def __init__(self, input_size, hidden_sizes, output_sizes=None, dropout=0, batch_first=False, stack_output=False, cell_bias=True, out_bias=True, dtype=None, device=None,
                activation_r_gate=tt.sigmoid, activation_z_gate=tt.sigmoid, activation_n_gate=tt.sigmoid, activation_out=None, activation_last=None) -> None:
        self.activation_r_gate = activation_r_gate
        self.activation_z_gate = activation_z_gate
        self.activation_n_gate = activation_n_gate
        self.activation_out = activation_out
        self.activation_last = activation_last
        self.n_states=1
        super().__init__(input_size, hidden_sizes, output_sizes, dropout, batch_first, stack_output, cell_bias, out_bias, dtype, device)

    def build_parameters(self, dtype, device):
        pnameL = ('irL', 'izL', 'inL')
        self._build_activations_(self.activation_r_gate, 'actR')
        self._build_activations_(self.activation_z_gate, 'actZ')
        self._build_activations_(self.activation_n_gate, 'actN')

        if self.n_output>0: 
            self._build_activations_(self.activation_out, 'actY')
            self._build_activations_(self.activation_last, 'act_')
            onameL = ('iyL',)
            self.forward_one = self.forward_one_y
        else:
            onameL = None
            self.forward_one = self.forward_one_x
        return self._build_parameters_(pnameL, onameL, dtype, device)

    def forward_one_x(self, x, s):
        H = []
        h, = s
        for i in range(self.n_hidden):
            xh = tt.concat( (x, h[i]), dim=-1)
            R = self.actR( self.irL[i]( xh ) )
            Z = self.actZ( self.izL[i]( xh ) )
            xr = tt.concat( (x, R*h[i]), dim=-1)
            N = self.actN( self.inL[i]( xr ) )
            x = (1-Z) * N + (Z * h[i])  #x = (1-Z) * h[i] + (Z * N) 
            H.append(x)
            x = tt.dropout(x, self.dropouts[i], self.training) #<--- dropout only output
        return x, (H,)

    def forward_one_y(self, x, s):
        H = []
        h, = s
        for i in range(self.n_hidden):
            xh = tt.concat( (x, h[i]), dim=-1)
            R = self.actR( self.irL[i]( xh ) )
            Z = self.actZ( self.izL[i]( xh ) )
            xr = tt.concat( (x, R*h[i]), dim=-1)
            N = self.actN( self.inL[i]( xr ) )
            d = (1-Z) * N + (Z * h[i])  #x = (1-Z) * h[i] + (Z * N) 
            H.append(d)
            if i==self.n_last:
                x = self.act_( self.iyL[i]( xh ) )  
            else:
                x = self.actY( self.iyL[i]( xh ) )
                x = tt.dropout(x, self.dropouts[i], self.training) #<--- dropout only output
        return x, (H,)

class LSTMX(RNNX):

    def __init__(self, input_size, hidden_sizes, output_sizes=None, dropout=0, batch_first=False, stack_output=False, cell_bias=True, out_bias=True, dtype=None, device=None,
                activation_i_gate=tt.sigmoid, activation_f_gate=tt.sigmoid, activation_g_gate=tt.sigmoid, activation_o_gate=tt.sigmoid, activation_cell=tt.tanh, activation_out=None, activation_last=None) -> None:
        self.activation_i_gate = activation_i_gate
        self.activation_f_gate = activation_f_gate
        self.activation_g_gate = activation_g_gate
        self.activation_o_gate = activation_o_gate
        self.activation_out = activation_out
        self.activation_cell = activation_cell
        self.activation_last = activation_last
        self.n_states=2
        super().__init__(input_size, hidden_sizes, output_sizes, dropout, batch_first, stack_output, cell_bias, out_bias, dtype, device)


    def build_parameters(self, dtype, device):
        pnameL = ('iiL', 'ifL', 'igL', 'ioL')
        self._build_activations_(self.activation_i_gate, 'actI')
        self._build_activations_(self.activation_f_gate, 'actF')
        self._build_activations_(self.activation_g_gate, 'actG')
        self._build_activations_(self.activation_o_gate, 'actO')
        self._build_activations_(self.activation_cell, 'actC')

        if self.n_output>0: 
            self._build_activations_(self.activation_out, 'actY')
            self._build_activations_(self.activation_last, 'act_')
            onameL = ('iyL',)
            self.forward_one = self.forward_one_y
        else:
            onameL = None
            self.forward_one = self.forward_one_x
        return self._build_parameters_(pnameL, onameL, dtype, device)
        

    def forward_one_x(self, x, s):
        H,C=[],[]
        h,c = s
        for i in range(len(self.hidden_sizes)):
            xh = tt.concat( (x, h[i]), dim=-1)
            I = self.actI( self.iiL[i]( xh ) )
            F = self.actF( self.ifL[i]( xh ) )
            G = self.actG( self.igL[i]( xh ) )
            O = self.actO( self.ioL[i]( xh ) )
            c_ = F*c[i] + I*G
            x = O * self.actC(c_)
            H.append(x)
            C.append(c_)
            x = tt.dropout(x, self.dropouts[i], self.training) #<--- dropout only output
        return x, (H,C)

    def forward_one_y(self, x, s):
        H,C=[],[]
        h,c = s
        for i in range(len(self.hidden_sizes)):
            xh = tt.concat( (x, h[i]), dim=-1)
            I = self.actI( self.iiL[i]( xh ) )
            F = self.actF( self.ifL[i]( xh ) )
            G = self.actG( self.igL[i]( xh ) )
            O = self.actO( self.ioL[i]( xh ) )
            c_ = F*c[i] + I*G
            d = O * self.actC(c_)
            H.append(d)
            C.append(c_)
            if i==self.n_last:
                x = self.act_( self.iyL[i]( xh ) )  
            else:
                x = self.actY( self.iyL[i]( xh ) )
                x = tt.dropout(x, self.dropouts[i], self.training) #<--- dropout only output
        return x, (H,C)

class JANETX(RNNX):

    def __init__(self, input_size, hidden_sizes, output_sizes=None, dropout=0, batch_first=False, stack_output=False, cell_bias=True, out_bias=True, dtype=None, device=None,
                activation_f_gate=tt.sigmoid, activation_g_gate=tt.sigmoid, activation_out=None, activation_last=None, beta=0.0) -> None:
        self.activation_f_gate = activation_f_gate
        self.activation_g_gate = activation_g_gate
        self.activation_out = activation_out
        self.activation_last = activation_last
        self.beta=beta
        self.n_states=1
        super().__init__(input_size, hidden_sizes, output_sizes, dropout, batch_first, stack_output, cell_bias, out_bias, dtype, device)

    def build_parameters(self, dtype, device):
        pnameL = ('ifL', 'igL')
        self._build_activations_(self.activation_f_gate, 'actF')
        self._build_activations_(self.activation_g_gate, 'actG')
        if self.n_output>0: 
            self._build_activations_(self.activation_out, 'actY')
            self._build_activations_(self.activation_last, 'act_')
            onameL = ('iyL',)
            self.forward_one = self.forward_one_y
        else:
            onameL = None
            self.forward_one = self.forward_one_x
        return self._build_parameters_(pnameL, onameL, dtype, device)


    def forward_one_x(self, x, s):
        H=[]
        h, = s
        for i in range(len(self.hidden_sizes)):
            xh = tt.concat( (x, h[i]), dim=-1)
            F = self.actF( self.ifL[i]( xh ) - self.beta)
            G = self.actG( self.igL[i]( xh ))
            x = F*h[i] + (1-F)*G
            H.append(x)
            x = tt.dropout(x, self.dropouts[i], self.training) #<--- dropout only output
        return x, (H,)

    def forward_one_y(self, x, s):
        H=[]
        h, = s
        for i in range(len(self.hidden_sizes)):
            xh = tt.concat( (x, h[i]), dim=-1)
            F = self.actF( self.ifL[i]( xh ) - self.beta)
            G = self.actG( self.igL[i]( xh ))
            d = F*h[i] + (1-F)*G
            H.append(d)
            if i==self.n_last:
                x = self.act_( self.iyL[i]( xh ) )  
            else:
                x = self.actY( self.iyL[i]( xh ) )
                x = tt.dropout(x, self.dropouts[i], self.training) #<--- dropout only output
        return x, (H,)

class MGUX(RNNX):

    def __init__(self, input_size, hidden_sizes, output_sizes=None, dropout=0, batch_first=False, stack_output=False, cell_bias=True, out_bias=True, dtype=None, device=None,
                activation_f_gate=tt.sigmoid, activation_g_gate=tt.tanh, activation_out=None, activation_last=None) -> None:
        self.activation_f_gate = activation_f_gate
        self.activation_g_gate = activation_g_gate
        self.activation_out = activation_out
        self.activation_last = activation_last
        self.n_states=1
        super().__init__(input_size, hidden_sizes, output_sizes, dropout, batch_first, stack_output, cell_bias, out_bias, dtype, device)

    def build_parameters(self, dtype, device):
        pnameL = ('ifL', 'igL')
        self._build_activations_(self.activation_f_gate, 'actF')
        self._build_activations_(self.activation_g_gate, 'actG')
        if self.n_output>0: 
            self._build_activations_(self.activation_out, 'actY')
            self._build_activations_(self.activation_last, 'act_')
            onameL = ('iyL',)
            self.forward_one = self.forward_one_y
        else:
            onameL = None
            self.forward_one = self.forward_one_x
        return self._build_parameters_(pnameL, onameL, dtype, device)


    def forward_one_x(self, x, s):
        H=[]
        h, = s
        for i in range(len(self.hidden_sizes)):
            xh = tt.concat( (x, h[i]), dim=-1)
            F = self.actF( self.ifL[i]( xh ))
            xf = tt.concat( (x, F*h[i]), dim=-1)
            G = self.actG( self.igL[i]( xf ))
            x = (1-F)*h[i] + F*G
            # or x = F*h[i] + (1-F)*G
            H.append(x)
            x = tt.dropout(x, self.dropouts[i], self.training) #<--- dropout only output
        return x, (H,)

    def forward_one_y(self, x, s):
        H=[]
        h, = s
        for i in range(len(self.hidden_sizes)):
            xh = tt.concat( (x, h[i]), dim=-1)
            F = self.actF( self.ifL[i]( xh ))
            xf = tt.concat( (x, F*h[i]), dim=-1)
            G = self.actG( self.igL[i]( xf ))
            d = (1-F)*h[i] + F*G
            # or x = F*h[i] + (1-F)*G
            H.append(d)
            if i==self.n_last:
                x = self.act_( self.iyL[i]( xh ) )  
            else:
                x = self.actY( self.iyL[i]( xh ) )
                x = tt.dropout(x, self.dropouts[i], self.training) #<--- dropout only output
        return x, (H,)