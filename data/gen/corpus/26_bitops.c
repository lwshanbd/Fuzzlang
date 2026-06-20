unsigned int reverse_bits(unsigned int x) {
    unsigned int r = 0;
    for (int i = 0; i < 8; ++i) {
        r = (r << 1) | (x & 1u);
        x >>= 1;
    }
    return r;
}
int main(void) {
    return (int)(reverse_bits(1u) & 0xff);
}
