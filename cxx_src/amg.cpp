#include <AMGCLSolver.h>
#include <NoMPIAMGCLSolver.h>
#include <BinaryIO.h>
#include <MPIDomain.h>
#include <SolverConfig.h>


void NoMPIAMGCL(){
	std::cout<<"--- No MPI version ---"<<std::endl;
	int N = 128;
	int dim = N*N*N;
	TV rhs(dim,T(0));
	TV x_pcg(dim,T(0));

  	int index_size = x_pcg.size();

	// loading data matrix A and
	IO::Deserialize(rhs, "../test_data/b_N128_3D_" + std::to_string(1) + ".bin");
	Eigen::SparseMatrix<T> Af(dim,dim);
   	IO::Eigen::Deserialize(Af, "../test_data/A_N128_3D_" + std::to_string(1) + ".bin");
	std::cout<<Af.innerSize()<<std::endl;


  	MPIDomain _mpi;
   	cxxopts::Options options("amgcl", "test");
   	SolverConfig config;
    	config.DefineOptions(options);
    	int argc = 1;
    	char timeoutString[] = "runUnitTests";
    	// make a non-const char array
    	char* _argv[] = {timeoutString, NULL};
    	char** argv = (char**)_argv;
    	auto result = options.parse(argc, argv);
    	config.ParseConfig(result);
    	config.max_iter = N*N;//max_it;  // effective N = N - 5 (ref is 36)
    	config.amgcl_rhs_scaling = 1.0;  // effective N = N - 5 (ref is 36)


	T norm = T(0);
	for(auto& e : rhs) norm += e;
	std::cout<<norm<<":norm"<<std::endl;
   	config.tol = 1e-4;  // effective N = N - 5 (ref is 36)
   	std::unique_ptr<AMGCLSolver> _amgcl;
   	_amgcl = std::make_unique<AMGCLSolver>(Af, config, _mpi);

  	Eigen::Matrix<T, Eigen::Dynamic, 1> x_input(rhs.size());
  	Eigen::Matrix<T, Eigen::Dynamic, 1> b_rhs(rhs.size());

  	for(int i = 0; i < index_size; i++) x_input(i) = x_pcg[i];
  	for(int i = 0; i < index_size; i++) b_rhs(i) = rhs[i];
  	_amgcl->Solve(Af,x_input, b_rhs);
}

void AMGCL(){
	std::cout<<"--- MPI version ---"<<std::endl;
	int N = 128;
	int dim = N*N*N;
	TV rhs(dim,T(0));
	TV x_pcg(dim,T(0));

  	int index_size = x_pcg.size();

	// loading data matrix A and
	IO::Deserialize(rhs, "../../data/dambreak_N128_200_3D/div_v_star_" + std::to_string(1) + ".bin");
	Eigen::SparseMatrix<T> Af(dim,dim);
   	IO::Eigen::Deserialize(Af, "../../data/dambreak_N128_200_3D/A_" + std::to_string(1) + ".bin");
	std::cout<<Af.innerSize()<<std::endl;


  	MPIDomain _mpi;
   	cxxopts::Options options("amgcl", "test");
   	SolverConfig config;
    	config.DefineOptions(options);
    	int argc = 1;
    	char timeoutString[] = "runUnitTests";
    	// make a non-const char array
    	char* _argv[] = {timeoutString, NULL};
    	char** argv = (char**)_argv;
    	auto result = options.parse(argc, argv);
    	config.ParseConfig(result);
    	config.max_iter = N*N;//max_it;  // effective N = N - 5 (ref is 36)
    	config.amgcl_rhs_scaling = 1.0;  // effective N = N - 5 (ref is 36)

   	config.tol = 1e-4;  // effective N = N - 5 (ref is 36)
   	std::unique_ptr<NoMPIAMGCLSolver> _amgcl;
   	_amgcl = std::make_unique<NoMPIAMGCLSolver>(Af, config, _mpi);

  	Eigen::Matrix<T, Eigen::Dynamic, 1> x_input(rhs.size());
  	Eigen::Matrix<T, Eigen::Dynamic, 1> b_rhs(rhs.size());

  	for(int i = 0; i < index_size; i++) x_input(i) = x_pcg[i];
  	for(int i = 0; i < index_size; i++) b_rhs(i) = rhs[i];

	// for (int i = 0; i < 100; ++i)
	_amgcl->Solve(Af,x_input, b_rhs);
}
int main(void){
	AMGCL();
	// NoMPIAMGCL();
	return 0;
}