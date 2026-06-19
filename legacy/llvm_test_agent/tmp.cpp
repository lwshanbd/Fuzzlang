
#ifdef WIN
void _cdecl win_c_variant(omp_interop_t);

// expected-error@+3 {{function with '#pragma omp declare variant' must have a prototype when 'append_args' is used}}
#pragma omp declare variant(win_c_variant)                     \
   append_args(interop(target)) match(construct={dispatch})
void _cdecl win_c_base() {}
#endif // WIN
