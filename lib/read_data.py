'''
File: read_data.py
File Created: Thursday, 5th January 2023 12:53:43 am

Modified from Osman's code.
--------------
'''
import os
from GLOBAL_VARS import *
import struct
import numpy as np
import scipy.sparse as sparse

def compute_weight(file_flags, N, DIM):
    flags = read_flags(file_flags)
    flags = flags.reshape((N,)*DIM, order='F')
    fluids = np.array(np.where(flags==2)).T
    top_bound = []
    right_bound = []
    for i in range(N):
        top = [fluids[j][0] for j in range(len(fluids)) if fluids[j][1] == i]
        right = [fluids[j][1] for j in range(len(fluids)) if fluids[j][0] == i]
        if len(top) > 0: top_bound.append(np.max(top))
        else:            top_bound.append(0.0)
        if len(right) > 0: right_bound.append(np.max(right))
        else:              right_bound.append(0.0)

    weight = np.zeros((N,)*DIM)
    for (i, j) in fluids:
        weight[i, j] = 1 / (np.min([j, right_bound[i]-j, i, top_bound[j]-i]) + 0.5)
    return weight.ravel(order='F')

def read_flags(file, dtype='int32'):
    len_size_t = 8
    if dtype == 'int32': length = 4
    else: length = 8
    with open(file, 'rb') as f:
        N = struct.unpack('N', f.read(len_size_t))[0]  # First 8 bytes stores length of vector
        b = struct.unpack(f'{N}i', f.read(length * N))
    b = np.array(b, dtype=dtype)
    return b

def load_vector(data_folder_name, normalize = False, dtype='double'):
    if(os.path.exists(data_folder_name)):
        r0 = np.fromfile(data_folder_name, dtype=dtype)
        r1 = np.delete(r0, [0])
        if normalize: return r1/np.linalg.norm(r1)
        else:         return r1
    else:
        print("No file for exist named " + data_folder_name)

def read_ppc(file_active_cells, file_ppc, N, DIM, dtype='int32'):
    active_cells = read_flags(file_active_cells, dtype)
    ppc = np.zeros((N+2)**DIM, dtype=dtype)
    ppc[active_cells] = read_flags(file_ppc)
    ppc = ppc.reshape((N+2,)*DIM)[1:-1, 1:-1].ravel()
    return ppc
"""
template <typename T>
void Serialize(const std::vector<T>& v, const std::string& filename) {
  std::ofstream out(filename, std::ios::out | std::ios::binary);
  size_t v_size = v.size();
  out.write((char*)&v_size, sizeof(size_t));
  out.write((char*)&v[0], v_size * sizeof(T));
  out.close();
}
"""
def readA(dim, filenameA, DIM, dtype='d'):
    N = dim**DIM
    mat_A = np.zeros((N,N), dtype=dtype)
    with open(filenameA, 'rb') as f:
        length = 8
        b = f.read(length)
        val = struct.unpack('N', b)
        for j in range(val[0]):
            lenght = 8
            bj = f.read(lenght)
            ele = struct.unpack('N',bj)
            for k in range(ele[0]):
                len_double = 8
                bk = f.read(len_double)
                elejk = struct.unpack('d',bk)
                mat_A[j][k] = elejk[0]
    return mat_A

"""
template <typename T, int OptionsBitFlag, typename Index>
void Serialize(SparseMatrix<T, OptionsBitFlag, Index>& m, const std::string& filename) {
  typedef Eigen::Triplet<T, Index> Trip;

  std::vector<Trip> res;

  fstream writeFile;
  writeFile.open(filename, ios::binary | ios::out);

  if (writeFile.is_open()) {
    Index rows, cols, nnzs, outS, innS;
    rows = m.rows();
    cols = m.cols();
    nnzs = m.nonZeros();
    outS = m.outerSize();
    innS = m.innerSize();

    writeFile.write((const char*)&(rows), sizeof(Index));
    writeFile.write((const char*)&(cols), sizeof(Index));
    writeFile.write((const char*)&(nnzs), sizeof(Index));
    writeFile.write((const char*)&(outS), sizeof(Index));
    writeFile.write((const char*)&(innS), sizeof(Index));

    writeFile.write((const char*)(m.valuePtr()), sizeof(T) * m.nonZeros());
    writeFile.write((const char*)(m.outerIndexPtr()), sizeof(Index) * m.outerSize());
    writeFile.write((const char*)(m.innerIndexPtr()), sizeof(Index) * m.nonZeros());

    writeFile.close();
  }
}
"""
def readA_sparse(filenameA, dtype='d', sparse_type='csr'):
    '''
    dim: grid points in each dimenstion
    DIM: 2D or 3D
    dtype: 'd', double (8 bytes); 'f', float (4 bytes)
    '''
    cols = []
    outerIdxPtr = []
    rows = []
    if dtype == 'd':
        len_data = 8
    elif dtype == 'f':
        len_data = 4
    #reading the bit files
    with open(filenameA, 'rb') as f:
        length = 4;
        b = f.read(length)
        num_rows = struct.unpack('i', b)[0]
        b = f.read(length)
        num_cols = struct.unpack('i', b)[0]
        b = f.read(length)
        nnz = struct.unpack('i', b)[0]
        b = f.read(length)
        outS = struct.unpack('i', b)[0]
        b = f.read(length)
        innS = struct.unpack('i', b)[0]
        data = [0.0] * nnz
        outerIdxPtr = [0]*outS
        cols = [0]*nnz
        rows = [0]*nnz
        for i in range(nnz):
            b = f.read(len_data)
            data[i] = struct.unpack(dtype, b)[0]
        for i in range(outS): # Index pointer
            length = 4
            b = f.read(length)
            outerIdxPtr[i] = struct.unpack('i', b)[0]
        for i in range(nnz): # Col index
            length = 4
            b = f.read(length)
            cols[i] = struct.unpack('i', b)[0]
    outerIdxPtr = outerIdxPtr + [nnz]
    for ii in range(num_rows):
        rows[outerIdxPtr[ii]:outerIdxPtr[ii+1]] = [ii]*(outerIdxPtr[ii+1] - outerIdxPtr[ii])
    if sparse_type.lower() == 'csr':
        return sparse.csr_matrix((data, (rows, cols)),[num_rows, num_cols], dtype=dtype)
    elif sparse_type.lower() == 'coo':
        return sparse.coo_matrix((data, (rows, cols)), [num_rows, num_cols], dtype=dtype)
    else:
        raise Exception("Sparse type only supports coo or csr")

def compressedMat(A, flags):
    selection = np.where(flags.ravel() == 2)[0]
    return A.tolil()[selection][:, selection].tocsr()
def compressedVec(b, flags):
    selection = np.where(flags.ravel() == 2)[0]
    return b[selection]
def expandVec(b, flags):
    flags = flags.ravel()
    selection = np.where(flags == 2)[0]
    v = np.zeros(flags.shape, b.dtype)
    v[selection] = b
    return v

if __name__ == '__main__':
    frame = 88
    N = 64
    DIM = 3
    prefix = ''
    bc = 'dambreak'
    file_A = os.path.join(DATA_PATH, f"{prefix}{bc}_N{N}_200_{DIM}D", f"A_{frame}.bin")
    file_rhs = os.path.join(DATA_PATH, f"{prefix}{bc}_N{N}_200_{DIM}D", f"div_v_star_{frame}.bin")
    file_sol = os.path.join(DATA_PATH, f"{prefix}{bc}_N{N}_200_{DIM}D", f"pressure_{frame}.bin")
    file_flags = os.path.join(DATA_PATH, f"{prefix}{bc}_N{N}_200_{DIM}D", f"flags_{frame}.bin")
    A = readA_sparse(file_A).tocoo()
    rhs = load_vector(file_rhs)
    sol = load_vector(file_sol)

    flags = read_flags(file_flags)
    r = rhs - A @ sol
    print(np.linalg.norm(r))
    print(A.sum(axis=1).min())
    print(A.shape)

    # with open(f"output/singular_mat/A_{frame}.mtx", 'w') as f:
    #     f.write(f"{A.shape[0]} {A.shape[1]} {A.nnz}\n")
    #     for i in range(len(A.data)):
    #         f.write(f"{A.row[i]+1} {A.col[i]+1} {A.data[i]}\n")
    # with open(f"output/singular_mat/rhs_{frame}.dat", 'w') as f:
    #     for i in range(len(rhs)):
    #         f.write(f"{rhs[i]}\n")
    # with open(f"output/singular_mat/sol_{frame}.dat", 'w') as f:
    #     for i in range(len(rhs)):
    #         f.write(f"{sol[i]}\n")
    # weight = compute_weight(file_flags, N, 2)
    # print(weight)
    # print(A.shape, rhs.shape, sol.shape, flags.shape)

    # print(flags.max(), flags.min())
    # file = os.path.join(path,  "..", "data_dcdm", "train_2D_64", f"A_solid.bin")
    # A = readA_sparse(64, file, DIM=2, dtype='f')
    # print(A)
    # with open("matA_test.txt", 'w') as f:
    #     sys.stdout = f
    #     A.maxprint = np.inf
    #     print(A)
