#include <pybind11/pybind11.h>
#include <pybind11/eigen.h>
#include "AMGCLSolver.h"
#include "BinaryIO.h"

namespace py = pybind11;

using AMGCL = AMGCLSolver<PBackend, SBackend>;

PYBIND11_MODULE(pyamgcl, m) {
    m.doc() = "python binding for AMGCL solver OpenMP version";
    m.def("solve", [](const SpMat& A, const VXT& b, double tol=1e-4, double atol=1e-10, int max_iters=100) {
        VXT x(b.size());
        x.setZero();
        auto info = AMGCL::Solve(A, x, b, tol, atol, max_iters);
        return std::make_tuple(x, info);
    });
}

