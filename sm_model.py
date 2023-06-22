import torch
import torch.nn as nn
import torch.nn.functional as F
from model import BaseModel
import math
import smblock # implemented in torch_extension/sm_block_kernel.cu

class SMBlockFunction(torch.autograd.Function):
    @staticmethod
    def forward(ctx, image, x, weights, bias):
        image = F.pad(image, (1,)*4) # 1, N+2, N+2
        x = F.pad(x, (1,)*4) # bs, 1, N+2, N+2
        ctx.save_for_backward(image, x, weights, bias)
        y, = smblock.forward(image, x, weights, bias)
        return y
    @staticmethod
    def backward(ctx, grad_output): # return the same number of outputs as forward function arguments
        image, x, weights, bias = ctx.saved_tensors
        grad_x, grad_w, grad_b, = smblock.backward(grad_output.contiguous(), image, x, weights, bias)
        return None, grad_x, grad_w, grad_b

class SmallSMBlock(nn.Module):
    def __init__(self):
        super().__init__()
        self.weight = nn.Parameter(torch.ones(9, 1, 3, 3))
        self.bias = nn.Parameter(torch.ones(9))
        torch.manual_seed(0)
        self.reset_parameters()
    def reset_parameters(self):
        # Setting a=sqrt(5) in kaiming_uniform is the same as initializing with
        # uniform(-1/sqrt(k), 1/sqrt(k)), where k = weight.size(1) * prod(*kernel_size)
        # For more details see: https://github.com/pytorch/pytorch/issues/15314#issuecomment-477448573
        nn.init.kaiming_uniform_(self.weight, a=math.sqrt(5))
        if self.bias is not None:
            fan_in, _ = nn.init._calculate_fan_in_and_fan_out(self.weight)
            if fan_in != 0:
                bound = 1 / math.sqrt(fan_in)
                nn.init.uniform_(self.bias, -bound, bound)
    def forward(self, image, x):
        return SMBlockFunction.apply(image, x, self.weight, self.bias)

class SmallSMBlockPY(nn.Module):
    def __init__(self):
        super().__init__()
        self.KL = nn.Conv2d(1, 9, kernel_size=3, padding='same', bias=True)
        torch.manual_seed(0)
        nn.init.kaiming_uniform_(self.KL.weight, a=math.sqrt(5))
        if self.KL.bias is not None:
            fan_in, _ = nn.init._calculate_fan_in_and_fan_out(self.KL.weight)
            if fan_in != 0:
                bound = 1 / math.sqrt(fan_in)
                nn.init.uniform_(self.KL.bias, -bound, bound)
    def forward(self, image, x): # 1 x N x N, bs x 1 x N x N
        K = self.KL(image) # 1 x N x N -> 9 x N x N
        K = K.permute((1, 2, 0)) # 9 x N x N -> N x N x 9
        K = K.unflatten(2, (3, 3)) # N x N x 9 -> N x N x 3 x 3
        x = F.pad(x, (1, 1, 1, 1)) # bs x 1 x N x N -> bs x 1 x (N+2) x (N+2)
        x = x.unfold(2, 3, 1).unfold(3, 3, 1) # bs x 1 x (N+2) x (N+2) -> bs x 1 x N x N x 3 x 3
        y = (x * K).sum(dim=(-2, -1))
        return y

class SmallSMBlock3D(nn.Module):
    def __init__(self):
        super().__init__()
        self.KL = nn.Conv3d(1, 27, kernel_size=3, padding='same', bias=True)

    def compiled_for(self, y, image, x, N):
        for i in range(1, N+1):
            for j in range(1, N+1):
                for k in range(1, N+1):
                    print(i, j, k)
                    K = ((self.KL.weight.squeeze() * image[0, i-1:i+2, j-1:j+2, k-1:k+2])).sum(dim=(1, 2, 3)) + self.KL.bias
                    K = K.view(3, 3, 3)
                    xx = x[:, 0, i-1:i+2, j-1:j+2, k-1:k+2]
                    y[:, 0, i-1, j-1, k-1] = (xx * K).sum(dim=(-3, -2, -1))
    def __forward(self, image, x): # 1 x N x N x N, bs x 1 x N x N x N
        y = torch.zeros_like(x)
        N = x.shape[-1]
        x = F.pad(x, (1,)*6) # bs x 1 x N x N x N -> bs x 1 x (N+2) x (N+2) x (N+2)
        image = F.pad(image, (1,)*6)
        self.compiled_for(y, image, x, N)
        return y

    def forward(self, image, x): # 1 x N x N x N, bs x 1 x N x N x N
        K = self.KL(image) # 1 x N x N x N -> 27 x N x N x N
        K = K.permute((1, 2, 3, 0)) # 27 x N x N x N -> N x N x N x 27
        K = K.unflatten(3, (3, 3, 3)) # N x N x N x 27 -> N x N x N x 3 x 3 x 3

        x = F.pad(x, (1, 1, 1, 1, 1, 1)) # bs x 1 x N x N x N -> bs x 1 x (N+2) x (N+2) x (N+2)
        x = x.unfold(2, 3, 1).unfold(3, 3, 1).unfold(4, 3, 1) # bs x 1 x (N+2) x (N+2) x (N+2) -> bs x 1 x N x N x N x 3 x 3 x 3
        y = (x * K).sum(dim=(-3, -2, -1)) # bs x 1 x N x N x N x 3 x 3 x 3, N x N x N x 3 x 3 x 3 -> bs x 1 x N x N x N
        return y

class SmallLinearBlock(nn.Module):
    def __init__(self):
        super().__init__()
        self.KL = nn.Conv2d(1, 9, kernel_size=3, padding='same')
    def forward(self, image):
        K = self.KL(image) # 1 x N x N -> 9 x N x N
        return K.mean()

class SmallLinearBlock3D(nn.Module):
    def __init__(self):
        super().__init__()
        self.KL = nn.Conv3d(1, 27, kernel_size=3, padding='same')
    def forward(self, image):
        K = self.KL(image) # 1 x N x N x N -> 27 x N x N x N
        return K.mean()


# General SmallSM model for any number of coarsening levels
class SmallSMModelDn(BaseModel):
    def __init__(self, n):
        super().__init__()
        self.n = n
        self.pre = nn.ModuleList()
        self.post = nn.ModuleList()
        for _ in range(n):
            self.pre.append(SmallSMBlock())
            self.post.append(SmallSMBlock())
        self.l = SmallSMBlock()
        self.c0 = nn.ModuleList()
        self.c1 = nn.ModuleList()
        for _ in range(n):
            self.c0.append(SmallLinearBlock())
            self.c1.append(SmallLinearBlock())

    def forward(self, image, b):
        x = [self.pre[0](image, b)]
        # x = [F.elu(self.pre[0](image, b))]
        imgs = [image]

        for i in range(1, self.n):
            x.append(F.avg_pool2d(x[-1], (2, 2)))
            imgs.append(F.avg_pool2d(imgs[-1], (2, 2)))
            x[-1] = self.pre[i](imgs[-1], x[-1])
            # x[-1] = F.elu(self.pre[i](imgs[-1], x[-1]))

        x.append(F.avg_pool2d(x[-1], (2, 2)))
        imgs.append(F.avg_pool2d(imgs[-1], (2, 2)))
        x[-1] = self.l(imgs[-1], x[-1])
        # x[-1] = F.elu(self.l(imgs[-1], x[-1]))

        for i in range(self.n, 0, -1):
            x[i] = F.interpolate(x[i], scale_factor=2)
            x[i] = self.post[i-1](imgs[i-1], x[i])
            # x[i] = F.elu(self.post[i-1](imgs[i-1], x[i]))
            x[i-1] = self.c0[i-1](imgs[i-1]) * x[i-1] + self.c1[i-1](imgs[i-1]) * x[i]

        return x[0]

class SmallSMModelDnPY(BaseModel):
    def __init__(self, n):
        super().__init__()
        self.n = n
        self.pre = nn.ModuleList()
        self.post = nn.ModuleList()
        for _ in range(n):
            self.pre.append(SmallSMBlockPY())
            self.post.append(SmallSMBlockPY())
        self.l = SmallSMBlockPY()
        self.c0 = nn.ModuleList()
        self.c1 = nn.ModuleList()
        for _ in range(n):
            self.c0.append(SmallLinearBlock())
            self.c1.append(SmallLinearBlock())

    def forward(self, image, b):
        x = [self.pre[0](image, b)]
        # x = [F.elu(self.pre[0](image, b))]
        imgs = [image]

        for i in range(1, self.n):
            x.append(F.avg_pool2d(x[-1], (2, 2)))
            imgs.append(F.avg_pool2d(imgs[-1], (2, 2)))
            x[-1] = self.pre[i](imgs[-1], x[-1])
            # x[-1] = F.elu(self.pre[i](imgs[-1], x[-1]))

        x.append(F.avg_pool2d(x[-1], (2, 2)))
        imgs.append(F.avg_pool2d(imgs[-1], (2, 2)))
        x[-1] = self.l(imgs[-1], x[-1])
        # x[-1] = F.elu(self.l(imgs[-1], x[-1]))

        for i in range(self.n, 0, -1):
            x[i] = F.interpolate(x[i], scale_factor=2)
            x[i] = self.post[i-1](imgs[i-1], x[i])
            # x[i] = F.elu(self.post[i-1](imgs[i-1], x[i]))
            x[i-1] = self.c0[i-1](imgs[i-1]) * x[i-1] + self.c1[i-1](imgs[i-1]) * x[i]

        return x[0]


# 3D: General SmallSM model for any number of coarsening levels
class SmallSMModelDn3D(BaseModel):
    def __init__(self, n):
        super().__init__()
        self.n = n
        self.pre = nn.ModuleList()
        self.post = nn.ModuleList()
        for _ in range(n):
            self.pre.append(SmallSMBlock3D())
            self.post.append(SmallSMBlock3D())
        self.l = SmallSMBlock3D()
        self.c0 = nn.ModuleList()
        self.c1 = nn.ModuleList()
        for _ in range(n):
            self.c0.append(SmallLinearBlock3D())
            self.c1.append(SmallLinearBlock3D())

    def forward(self, image, b):
        x = [self.pre[0](image, b)]
        imgs = [image]

        for i in range(1, self.n):
            x.append(F.avg_pool3d(x[-1], (2, 2, 2)))
            imgs.append(F.avg_pool3d(imgs[-1], (2, 2, 2)))
            x[-1] = self.pre[i](imgs[-1], x[-1])

        x.append(F.avg_pool3d(x[-1], (2, 2, 2)))
        imgs.append(F.avg_pool3d(imgs[-1], (2, 2, 2)))
        x[-1] = self.l(imgs[-1], x[-1])

        for i in range(self.n, 0, -1):
            x[i] = F.interpolate(x[i], scale_factor=2)
            x[i] = self.post[i-1](imgs[i-1], x[i])
            x[i-1] = self.c0[i-1](imgs[i-1]) * x[i-1] + self.c1[i-1](imgs[i-1]) * x[i]

        return x[0]

# For multiple channels
class MultiSMBlock(nn.Module):
    def __init__(self, nc):
        super().__init__()
        self.KL = nn.Conv2d(1, 9*nc, kernel_size=3, padding='same')
        self.nc = nc
    def forward(self, image, x): # 1 x N x N, bs x 1 x N x N
        K = self.KL(image) # 1 x N x N -> (2 x 9) x N x N
        K = K.unflatten(0, (self.nc, 9)) # (2 x 9) x N x N -> 2 x 9 x N x N
        K = K.permute((0, 2, 3, 1)) # 2 x 9 x N x N -> 2 x N x N x 9
        K = K.unflatten(-1, (3, 3)) # 2 x N x N x 9 -> 2 x N x N x 3 x 3
        x = F.pad(x, (1, 1, 1, 1)) # bs x 1 x N x N -> bs x 1 x (N+2) x (N+2)
        x = x.unfold(2, 3, 1).unfold(3, 3, 1) # bs x 1 x (N+2) x (N+2) -> bs x 1 x N x N x 3 x 3
        y = (x * K).sum(dim=(-2, -1)) # bs x 1 x N x N x 3 x 3, 2 x N x N x 3 x 3 -> bs x 2 x N x N
        return y

# multiple channels
class MultiSMModelD2(BaseModel):
    def __init__(self, nc=3):
        super().__init__()
        self.pre0 = MultiSMBlock(nc)
        self.post0 = MultiSMBlock(nc)
        self.pre1 = MultiSMBlock(nc)
        self.post1 = MultiSMBlock(nc)
        self.l2 = MultiSMBlock(nc)

        self.c00 = SmallLinearBlock()
        self.c01 = SmallLinearBlock()
        self.c10 = SmallLinearBlock()
        self.c11 = SmallLinearBlock()

        self.last = nn.Conv2d(nc, 1, kernel_size=1)

    def forward(self, image, b):
        b0 = F.elu(self.pre0(image, b))

        b1 = F.avg_pool2d(b0, (2, 2))
        image1 = F.max_pool2d(image, (2, 2))
        b1 = F.elu(self.pre1(image1, b1))

        b2 = F.avg_pool2d(b1, (2, 2))
        image2 = F.max_pool2d(image1, (2, 2))
        b2 = F.elu(self.l2(image2, b2))

        b2 = F.interpolate(b2, scale_factor=2)
        b2 = F.elu(self.post1(image1, b2))
        b1 = self.c10(image1) * b1 + self.c11(image1) * b2

        b1 = F.interpolate(b1, scale_factor=2)
        b1 = F.elu(self.post0(image, b1))
        b0 = self.c00(image) * b0 + self.c01(image) * b1

        b0 = self.last(b0)
        return b0

class MultiSMModelD3(BaseModel):
    def __init__(self, nc=3):
        super().__init__()
        self.pre0 = MultiSMBlock(nc)
        self.post0 = MultiSMBlock(nc)
        self.pre1 = MultiSMBlock(nc)
        self.post1 = MultiSMBlock(nc)
        self.pre2 = MultiSMBlock(nc)
        self.post2 = MultiSMBlock(nc)
        self.l3 = MultiSMBlock(nc)

        self.c00 = SmallLinearBlock()
        self.c01 = SmallLinearBlock()
        self.c10 = SmallLinearBlock()
        self.c11 = SmallLinearBlock()
        self.c20 = SmallLinearBlock()
        self.c21 = SmallLinearBlock()

        self.last = nn.Conv2d(nc, 1, kernel_size=1)

    def forward(self, image, b):
        b0 = F.elu(self.pre0(image, b))

        b1 = F.avg_pool2d(b0, (2, 2))
        image1 = F.max_pool2d(image, (2, 2))
        b1 = F.elu(self.pre1(image1, b1))

        b2 = F.avg_pool2d(b1, (2, 2))
        image2 = F.max_pool2d(image1, (2, 2))
        b2 = F.elu(self.pre2(image2, b2))

        b3 = F.avg_pool2d(b2, (2, 2))
        image3 = F.max_pool2d(image2, (2, 2))
        b3 = F.elu(self.l3(image3, b3))

        b3 = F.interpolate(b3, scale_factor=2)
        b3 = F.elu(self.post2(image2, b3))
        b2 = self.c20(image2) * b2 + self.c21(image2) * b3

        b2 = F.interpolate(b2, scale_factor=2)
        b2 = F.elu(self.post1(image1, b2))
        b1 = self.c10(image1) * b1 + self.c11(image1) * b2

        b1 = F.interpolate(b1, scale_factor=2)
        b1 = F.elu(self.post0(image, b1))
        b0 = self.c00(image) * b0 + self.c01(image) * b1

        b0 = self.last(b0)
        return b0


if __name__ == '__main__':
    import os, sys
    path = os.path.dirname(os.path.realpath(__file__))
    sys.path.append(path + "/lib")
    from lib.read_data import *
    import matplotlib.pyplot as plt
    torch.set_default_dtype(torch.float64)
    torch.manual_seed(0)
    torch.backends.cudnn.deterministic = True
    torch.backends.cudnn.benchmark = False
    torch.backends.cudnn.allow_tf32 = True

    N = 256
    frame = 100
    # file_A = os.path.join(path, "data_fluidnet", "dambreak_2D_64", f"A_{frame}.bin")
    file_rhs = os.path.join(DATA_PATH, f"dambreak_N{N}_200", f"div_v_star_{frame}.bin")
    file_sol = os.path.join(DATA_PATH, f"dambreak_N{N}_200", f"pressure_{frame}.bin")
    file_flags = os.path.join(DATA_PATH, f"dambreak_N{N}_200", f"flags_{frame}.bin")
    # A = readA_sparse(64, file_A, DIM=2)
    rhs = torch.tensor(load_vector(file_rhs), dtype=torch.float64)
    flags = torch.tensor(read_flags(file_flags), dtype=torch.float64)
    sol = torch.tensor(load_vector(file_sol), dtype=torch.float64)


    # torch.set_grad_enabled(False) # disable autograd globally

    model = SmallSMBlock().cuda()

    model1 = SmallSMBlockPY().cuda()

    # image = torch.randint(2, 4, (1, 3, 3)).float().cuda()
    # x = torch.randn((1, 1, 3, 3)).cuda()
    image = flags.reshape(1, N, N).cuda()
    x = rhs.reshape(1, 1, N, N).cuda()
    x.requires_grad = True
    x1 = rhs.reshape(1, 1, N, N).cuda()
    x1.requires_grad = True

    y = model(image, x)
    y1 = model1(image, x1)

    print((y - y1).abs().max())

    y.sum().backward()
    y1.sum().backward()

    print((model.bias.grad - model1.KL.bias.grad).abs().max())
    print((x.grad - x1.grad).abs().max())
    # yy = model.forward1(image, x)
    # yyy = model.forward2(image, x)
    # y = model(image, x)
    # print((y - yy).norm())

