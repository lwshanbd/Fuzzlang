int power(int base, int exp = 2) {
    int r = 1;
    for (int i = 0; i < exp; ++i) r *= base;
    return r;
}
int main() {
    return power(3) + power(2, 3);
}
