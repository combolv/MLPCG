import os
import torch
from read_data import *

def preprocess(data_folder, f_start, f_end):
    os.makedirs(os.path.join(data_folder, "preprocessed"), exist_ok=True)
    for index in range(f_start, f_end):
        file_rhs = os.path.join(data_folder, f"div_v_star_{index}.bin")
        file_flags = os.path.join(data_folder, f"flags_{index}.bin")
        file_A = os.path.join(data_folder, f"A_{index}.bin")
        rhs = torch.tensor(load_vector(file_rhs), dtype=torch.float32) #.reshape((1,) + (N,)*DIM)
        flags = torch.tensor(read_flags(file_flags), dtype=torch.float32) #.reshape((1,) + (N,)*DIM)
        x = torch.stack([rhs, flags])
        A = readA_sparse(64, file_A, DIM=2).tocoo()
        # Creating tensors from a list of np arrays is slow
        # CSC and CSR do not support stacking for batching, but COO does
        A = torch.sparse_coo_tensor(np.array([A.row, A.col]), A.data, A.shape, dtype=torch.float32)
        torch.save(x, os.path.join(data_folder, "preprocessed", f"x_{index}.pt"))
        torch.save(A, os.path.join(data_folder, "preprocessed", f"A_{index}.pt"))

if __name__ == '__main__':
    folder = os.path.join(os.path.dirname(os.path.relpath(__file__)),
                          "..", "data_fluidnet", "dambreak_2D_64")
    start = 1
    end = 1001
    preprocess(folder, start, end)