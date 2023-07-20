#include <torch/extension.h>

#include <cuda.h>
#include <cuda_runtime.h>

#include <vector>

#define NUM_IMAGES 3
#define KERNEL_SIZE 27
#define WEIGHT_SIZE NUM_IMAGES*KERNEL_SIZE*KERNEL_SIZE
__constant__ unsigned char WEIGHT_BYTES[WEIGHT_SIZE*sizeof(double)];

#define LOCATIONSPERBLOCK 4
#define NUM_THREADS_FORWARD 256
#define NUM_THREADS_BACKWARD 256

namespace {
template <typename scalar_t>
__global__ void sm_linear_3d_cuda_forward_kernel(
    const torch::PackedTensorAccessor32<scalar_t,4,torch::RestrictPtrTraits> image, // 1, N, N, N
    torch::PackedTensorAccessor32<scalar_t,1,torch::RestrictPtrTraits> y,
    const int nBlocks, const int N1, const int N2, const int N3) {

  __shared__ scalar_t z[NUM_THREADS_FORWARD];

  const scalar_t *WEIGHT = (const scalar_t *)(WEIGHT_BYTES);

  const int outerBlock = blockIdx.x / nBlocks;
  const int c = outerBlock;
  // const int c = outerBlock / NUM_IMAGES;
  // const int m = outerBlock % NUM_IMAGES;
  const int innerBlock = blockIdx.x % nBlocks;
  const int location = blockDim.x * innerBlock + threadIdx.x;

  z[threadIdx.x] = 0.0;

  if (location < NUM_IMAGES*N1*N2*N3) {
    const int ij = location % N3;
    const int j = (location/N3) % N2;
    const int i = (location/N3) / N2;

    #pragma unroll 1
    for (int m = 0; m < NUM_IMAGES; ++m) {
      for (int k = 0; k <= 2; ++k) {
        for (int l = 0; l <= 2; ++l) {
          for (int kl = 0; kl <= 2; ++kl) {
            z[threadIdx.x] += WEIGHT[3*(3*(3*(NUM_IMAGES*c+m)+k)+l)+kl] * image[m][i+k][j+l][ij+kl];
          }
        }
      }
    }
  }
  __syncthreads();

  // reduction
  // #pragma unroll
  for (int n = NUM_THREADS_FORWARD; n > 1; n /= 2) {
    if (threadIdx.x < n / 2)
      z[threadIdx.x] += z[threadIdx.x + n / 2];
    __syncthreads();
  }
  if (threadIdx.x == 0) atomicAdd(&y[0], z[0]);
}


template <typename scalar_t>
__global__ void sm_linear_3d_cuda_backward_kernel(
    const torch::PackedTensorAccessor32<scalar_t,1,torch::RestrictPtrTraits> grad_output, // bs, 1, N, N, N
    const torch::PackedTensorAccessor32<scalar_t,4,torch::RestrictPtrTraits> image, // 1, N, N, N
    torch::PackedTensorAccessor32<scalar_t,5,torch::RestrictPtrTraits> grad_w,
    const int nBlocksPerCopy, const int n1, const int n2, const int n3) {

  __shared__ scalar_t d_w[WEIGHT_SIZE];

  const int location = blockIdx.x / nBlocksPerCopy;
  const int innerBlock = blockIdx.x % nBlocksPerCopy;

  const int ij = (location % n3) * LOCATIONSPERBLOCK;
  const int j = ((location/n3) % n2) * LOCATIONSPERBLOCK;
  const int i = ((location/n3) / n2) * LOCATIONSPERBLOCK;

  int p = innerBlock * blockDim.x + threadIdx.x;

  if (p >= WEIGHT_SIZE) return; // Wasted threads

  const int idx = p;
  const int kl = p % 3;
  p /= 3;
  const int l = p % 3;
  p /= 3;
  const int k = p % 3;
  p /= 3;
  const int m = p % NUM_IMAGES;
  const int c = p / NUM_IMAGES;

  d_w[idx] = 0.0;
  #pragma unroll
  for (int _i = 0; _i < LOCATIONSPERBLOCK; ++_i) {
    for (int _j = 0; _j < LOCATIONSPERBLOCK; ++_j) {
      for (int _ij = 0; _ij < LOCATIONSPERBLOCK; ++_ij) {
        d_w[idx] += image[m][i+_i+k][j+_j+l][ij+_ij+kl];
      }
    }
  }
  atomicAdd(&grad_w[c][m][k][l][kl], d_w[idx]);
}

} // namespace

std::vector<torch::Tensor> sm_linear_3d_cuda_forward(
    torch::Tensor image,
    torch::Tensor weights,
    torch::Tensor bias) {

  assert(image.size(0) == NUM_IMAGES);

  if (image.dtype() == torch::ScalarType::Double) {
    cudaMemcpyToSymbol(WEIGHT_BYTES, weights.data_ptr<double>(), WEIGHT_SIZE * sizeof(double));
  } else {
    cudaMemcpyToSymbol(WEIGHT_BYTES, weights.data_ptr<float>(), WEIGHT_SIZE * sizeof(float));
  }

  const int N1 = image.size(1)-2;
  const int N2 = image.size(2)-2;
  const int N3 = image.size(3)-2;
  auto y = torch::zeros({1}, torch::dtype(image.dtype()).device(image.device()));

  const int nThreads = NUM_THREADS_FORWARD;
  const int nBlocks = (N1*N2*N3 + nThreads - 1) / nThreads; // b, i, j, ij

  const dim3 threads(nThreads);
  const dim3 blocks(nBlocks * KERNEL_SIZE);

  AT_DISPATCH_FLOATING_TYPES(image.type(), "sm_linear_3d_forward_cuda", ([&] {
    sm_linear_3d_cuda_forward_kernel<scalar_t><<<blocks, threads>>>(
        image.packed_accessor32<scalar_t,4,torch::RestrictPtrTraits>(),
        y.packed_accessor32<scalar_t,1,torch::RestrictPtrTraits>(),
        nBlocks, N1, N2, N3);
  }));

  y /= KERNEL_SIZE * N1*N2*N3;
  y += bias.mean();
  return {y};
}

std::vector<torch::Tensor> sm_linear_3d_cuda_backward(
    torch::Tensor grad_output,
    torch::Tensor image) {

  assert(image.size(0) == NUM_IMAGES);

  const int N1 = image.size(1) - 2;
  const int N2 = image.size(2) - 2;
  const int N3 = image.size(3) - 2;

  const int nThreads = NUM_THREADS_BACKWARD;
  const int nBlocksPerCopy = (WEIGHT_SIZE + nThreads - 1) / nThreads;
  const int locationsPerBlock = LOCATIONSPERBLOCK;

  assert((N1 % locationsPerBlock == 0) && (N2 % locationsPerBlock == 0) && (N3 % locationsPerBlock == 0)); // Data must be divisible by divisions

  const int n1 = N1 / locationsPerBlock;
  const int n2 = N2 / locationsPerBlock;
  const int n3 = N3 / locationsPerBlock;
  const dim3 threads(nThreads);
  const dim3 blocks(nBlocksPerCopy*n1*n2*n3);

  auto grad_w = torch::zeros({27, NUM_IMAGES, 3, 3, 3}, torch::dtype(image.dtype()).device(image.device()));
  auto grad_b = torch::ones({27}, torch::dtype(image.dtype()).device(image.device())) / KERNEL_SIZE * grad_output;

  AT_DISPATCH_FLOATING_TYPES(grad_output.type(), "sm_linear_3d_cuda_backward", ([&] {
    sm_linear_3d_cuda_backward_kernel<scalar_t><<<blocks, threads>>>(
        grad_output.packed_accessor32<scalar_t,1,torch::RestrictPtrTraits>(),
        image.packed_accessor32<scalar_t,4,torch::RestrictPtrTraits>(),
        grad_w.packed_accessor32<scalar_t,5,torch::RestrictPtrTraits>(),
        nBlocksPerCopy, n1, n2, n3);
  }));
  grad_w /= KERNEL_SIZE * N1 * N2 * N3;
  grad_w *= grad_output;
  return {grad_w, grad_b};
}

int main() {
  int bs = 5;
  int N = 128;
  int num_imgs = 3;
  auto image = torch::ones({num_imgs, N, N, N}, torch::dtype(torch::kFloat32).device(torch::kCUDA));
  auto x = torch::rand({bs, 1, N, N, N}, torch::dtype(torch::kFloat32).device(torch::kCUDA));
  auto weight = torch::rand({27, num_imgs, 3, 3, 3}, torch::dtype(torch::kFloat32).device(torch::kCUDA));
  auto bias = torch::rand({27}, torch::dtype(torch::kFloat32).device(torch::kCUDA));
  // curandState *d_states;
  // cudaMalloc(&d_states, CNT * sizeof(curandState));
  // kernel_setup_randstates_2d<<<1,CNT>>>(d_states, 1,1, 1);
  // cudaDeviceSynchronize();
  cudaEvent_t start, stop;
  cudaEventCreate(&start);
  cudaEventCreate(&stop);

  cudaEventRecord(start);
  for (int i = 0; i < 100; ++i)
    auto y = sm_linear_3d_cuda_forward(image, weight, bias);
  // std::cout << y  << std::endl;
  cudaEventRecord(stop);
  cudaEventSynchronize(stop);
  float milliseconds = 0;
  cudaEventElapsedTime(&milliseconds, start, stop);
  std::cout << "time " << milliseconds/100*1000 << " us" << std::endl;
  // cudaDeviceSynchronize();
}