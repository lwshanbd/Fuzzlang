
void test(void) {
    #pragma OPENCL EXTENSION cl_khr_fp64 : disable
    double d; // expected-error {{type 'double' requires cl_khr_fp64 support}}
}
